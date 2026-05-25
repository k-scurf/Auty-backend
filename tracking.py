"""
Face tracking: NMS, IoU + centroid association, stale cleanup, bbox smoothing.
"""

from __future__ import annotations

import time
from enum import Enum

import cv2
import numpy as np

import face_detection
from vision.tracker_bytetrack import ByteTrackAdapter


class TrackState(str, Enum):
    ACTIVE = "ACTIVE"
    LOST = "LOST"
    REMOVED = "REMOVED"


def bbox_iou(box_a, box_b) -> float:
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def bbox_centroid(bbox):
    x, y, w, h = bbox
    return (x + w * 0.5, y + h * 0.5)


def centroid_distance(box_a, box_b) -> float:
    ax, ay = bbox_centroid(box_a)
    bx, by = bbox_centroid(box_b)
    return float(np.hypot(ax - bx, ay - by))


def nms_detections(detections, iou_threshold=0.4):
    """Greedy non-maximum suppression on (x, y, w, h) detections."""
    if len(detections) == 0:
        return []

    boxes = [tuple(int(v) for v in d) for d in detections]
    areas = [w * h for (_, _, w, h) in boxes]
    order = sorted(range(len(boxes)), key=lambda i: areas[i], reverse=True)
    keep = []

    while order:
        i = order.pop(0)
        keep.append(boxes[i])
        remaining = []
        for j in order:
            if bbox_iou(boxes[i], boxes[j]) < iou_threshold:
                remaining.append(j)
        order = remaining

    return keep


def lerp_bbox(old_bbox, new_bbox, alpha=0.3):
    """Smooth box: old * (1-alpha) + new * alpha."""
    ox, oy, ow, oh = old_bbox
    nx, ny, nw, nh = new_bbox
    b = 1.0 - alpha
    return (
        int(ox * b + nx * alpha),
        int(oy * b + ny * alpha),
        int(ow * b + nw * alpha),
        int(oh * b + nh * alpha),
    )


def apply_smooth_bbox(track, new_bbox, alpha):
    prev = track.get("smooth_bbox") or track.get("bbox") or new_bbox
    track["bbox"] = new_bbox
    track["smooth_bbox"] = lerp_bbox(prev, new_bbox, alpha)

    # Light velocity for optional prediction.
    pcx, pcy = bbox_centroid(prev)
    ncx, ncy = bbox_centroid(new_bbox)
    track["velocity"] = (ncx - pcx, ncy - pcy)


def track_quality(track: dict) -> float:
    """Higher = prefer keeping this track when deduplicating."""
    bbox = track.get("smooth_bbox") or track.get("bbox", (0, 0, 0, 0))
    area = float(bbox[2] * bbox[3])
    score = float(track.get("locked_score") or 0.0)
    stable = float(track.get("stable_count", 0))
    return area * (0.35 + max(score, 0.0)) + stable * 500.0


def predict_bbox(track):
    """Shift bbox by last velocity when tracker update fails briefly."""
    bbox = track.get("smooth_bbox") or track.get("bbox")
    if bbox is None:
        return None
    vx, vy = track.get("velocity", (0.0, 0.0))
    x, y, w, h = bbox
    return (int(x + vx), int(y + vy), int(w), int(h))


class FaceTrackManager:
    def __init__(self, settings, face_cascade, create_tracker_fn, new_track_fn):
        self.settings = settings
        self.face_cascade = face_cascade
        self.create_tracker_fn = create_tracker_fn
        self.new_track_fn = new_track_fn
        self.tracks = {}
        self.next_track_id = 0
        self._byte = ByteTrackAdapter()
        self._byte_id_map: dict = {}

    def reset(self):
        self.tracks.clear()
        self.next_track_id = 0
        self._byte_id_map.clear()

    @staticmethod
    def _det_bbox(det):
        if isinstance(det, dict):
            return det["bbox"]
        return det

    def _cfg(self, key, default):
        return self.settings.get(key, default)

    def active_tracks(self):
        return [
            t
            for t in self.tracks.values()
            if t.get("state") == TrackState.ACTIVE
        ]

    def get_track(self, track_id):
        return self.tracks.get(track_id)

    def _init_opencv_tracker(self, track, frame, bbox):
        x, y, w, h = bbox
        tracker = self.create_tracker_fn()
        tracker.init(frame, (int(x), int(y), int(w), int(h)))
        track["tracker"] = tracker
        track["fail_count"] = 0

    def _is_duplicate_detection(self, bbox):
        max_dist = float(self._cfg("max_centroid_dist", 50))
        dup_iou = float(self._cfg("iou_duplicate_threshold", 0.15))

        for track in self.active_tracks():
            ref = track.get("smooth_bbox") or track.get("bbox")
            if ref is None:
                continue
            if centroid_distance(bbox, ref) < max_dist and bbox_iou(bbox, ref) > dup_iou:
                return True
        return False

    def _detection_matches_track(self, det_bbox, track_bbox):
        max_dist = float(self._cfg("max_centroid_dist", 50))
        iou_thresh = float(self._cfg("iou_match_threshold", 0.25))
        iou = bbox_iou(det_bbox, track_bbox)
        dist = centroid_distance(det_bbox, track_bbox)
        return iou >= iou_thresh or dist < max_dist

    def _apply_det_meta(self, track, det):
        if isinstance(det, dict):
            if det.get("kps") is not None:
                track["kps"] = det["kps"]
            track["pose_yaw"] = float(det.get("pose_yaw", 0.0))
            if "score" in det:
                track["last_det_score"] = float(det["score"])
        else:
            kps = getattr(det, "kps", None)
            if kps is not None:
                track["kps"] = kps
            track["pose_yaw"] = float(getattr(det, "pose_yaw", 0.0))
            track["last_det_score"] = float(getattr(det, "score", 0.9))

    def _age_stale_tracks(self, verified_ids: set, *, run_detect: bool):
        """Drop ghost boxes fast; verified tracks tolerate detect gaps."""
        max_missing = int(self._cfg("max_missing_frames", 5))
        max_unverified = int(self._cfg("max_unverified_frames", 2))
        to_remove = []

        for tid, track in list(self.tracks.items()):
            if tid in verified_ids:
                track["missing_frames"] = 0
                continue

            if not track.get("det_verified", False):
                track["missing_frames"] = track.get("missing_frames", 0) + 1
                if track["missing_frames"] >= max_unverified:
                    track["state"] = TrackState.REMOVED
                    to_remove.append(tid)
                continue

            if run_detect:
                track["missing_frames"] = track.get("missing_frames", 0) + 1
                if track["missing_frames"] > max_missing:
                    track["state"] = TrackState.REMOVED
                    to_remove.append(tid)

        for tid in to_remove:
            del self.tracks[tid]
            for bt_id, aid in list(self._byte_id_map.items()):
                if aid == tid:
                    del self._byte_id_map[bt_id]

    def _associate_detections(self, frame, detections):
        alpha = float(self._cfg("bbox_smooth_alpha", 0.3))
        reinit_iou = float(self._cfg("tracker_reinit_iou", 0.15))

        active = self.active_tracks()
        if not detections:
            for track in active:
                track["missing_frames"] = track.get("missing_frames", 0) + 1
            return

        pairs = []
        for di, det in enumerate(detections):
            dbbox = self._det_bbox(det)
            for track in active:
                ref = track.get("smooth_bbox") or track.get("bbox")
                if ref is None:
                    continue
                if not self._detection_matches_track(dbbox, ref):
                    continue
                iou = bbox_iou(dbbox, ref)
                dist = centroid_distance(dbbox, ref)
                pairs.append((iou, -dist, di, track["id"]))

        pairs.sort(key=lambda p: (p[0], p[1]), reverse=True)

        matched_dets = set()
        matched_tids = set()

        for iou, _neg_dist, di, tid in pairs:
            if di in matched_dets or tid in matched_tids:
                continue
            det = detections[di]
            dbbox = self._det_bbox(det)
            track = self.tracks[tid]
            matched_dets.add(di)
            matched_tids.add(tid)

            track["missing_frames"] = 0
            track["last_seen"] = time.time()
            track["state"] = TrackState.ACTIVE
            self._apply_det_meta(track, det)

            ref = track.get("smooth_bbox") or track.get("bbox") or dbbox
            if bbox_iou(dbbox, ref) < reinit_iou:
                self._init_opencv_tracker(track, frame, dbbox)
            apply_smooth_bbox(track, dbbox, alpha)

        for di, det in enumerate(detections):
            if di in matched_dets:
                continue
            dbbox = self._det_bbox(det)
            if self._is_duplicate_detection(dbbox):
                if self._cfg("debug_scores", False):
                    print(f"[tracking] skip duplicate detection {dbbox}")
                continue

            tid = self.next_track_id
            self.next_track_id += 1
            track = self.new_track_fn(tid)
            track["state"] = TrackState.ACTIVE
            track["missing_frames"] = 0
            track["last_seen"] = time.time()
            track["smooth_bbox"] = dbbox
            track["bbox"] = dbbox
            track["velocity"] = (0.0, 0.0)
            self._apply_det_meta(track, det)
            self._init_opencv_tracker(track, frame, dbbox)
            self.tracks[tid] = track

        for track in active:
            if track["id"] not in matched_tids:
                track["missing_frames"] = track.get("missing_frames", 0) + 1

    def _run_detection(self, frame):
        detections = face_detection.detect_faces(
            frame, self.face_cascade, self.settings
        )
        max_det = int(self._cfg("max_face_detections", 3))
        if len(detections) > max_det:
            detections = sorted(
                detections, key=lambda b: b[2] * b[3], reverse=True
            )[:max_det]
        return detections

    def prune_duplicate_identity_tracks(self):
        """Keep one track per locked identity (largest / highest confidence)."""
        if not self._cfg("merge_duplicate_identity_tracks", True):
            return

        active = self.active_tracks()
        best_by_name: dict = {}
        for track in active:
            name = track.get("locked_name", "UNKNOWN")
            if name == "UNKNOWN":
                continue
            q = track_quality(track)
            prev = best_by_name.get(name)
            if prev is None or q > prev[0]:
                best_by_name[name] = (q, track["id"])

        keep_ids = {tid for _, tid in best_by_name.values()}
        to_remove = []
        for track in active:
            name = track.get("locked_name", "UNKNOWN")
            if name != "UNKNOWN" and track["id"] not in keep_ids:
                track["state"] = TrackState.REMOVED
                to_remove.append(track["id"])
                if self._cfg("debug_scores", False):
                    print(f"[tracking] prune duplicate track T{track['id']} ({name})")

        for tid in to_remove:
            self.tracks.pop(tid, None)

    def _update_trackers(self, frame):
        alpha = float(self._cfg("bbox_smooth_alpha", 0.3))
        max_missing = int(self._cfg("max_missing_frames", 10))
        predict_frames = int(self._cfg("predict_frames", 2))

        to_remove = []

        for tid, track in list(self.tracks.items()):
            if track.get("state") == TrackState.REMOVED:
                to_remove.append(tid)
                continue

            tracker = track.get("tracker")
            if tracker is None:
                to_remove.append(tid)
                continue

            ok, bbox = tracker.update(frame)
            if ok:
                x, y, w, h = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
                new_bbox = (x, y, w, h)
                apply_smooth_bbox(track, new_bbox, alpha)
                track["missing_frames"] = 0
                track["fail_count"] = 0
                track["last_seen"] = time.time()
                track["state"] = TrackState.ACTIVE
                track["predict_count"] = 0
            else:
                track["fail_count"] = track.get("fail_count", 0) + 1
                track["missing_frames"] = track.get("missing_frames", 0) + 1
                pred_count = track.get("predict_count", 0)

                if pred_count < predict_frames:
                    predicted = predict_bbox(track)
                    if predicted is not None:
                        apply_smooth_bbox(track, predicted, alpha)
                        track["predict_count"] = pred_count + 1
                        track["state"] = TrackState.ACTIVE
                    else:
                        track["state"] = TrackState.LOST
                else:
                    track["state"] = TrackState.LOST

            if track.get("missing_frames", 0) > max_missing:
                track["state"] = TrackState.REMOVED
                to_remove.append(tid)

        for tid in to_remove:
            del self.tracks[tid]

    def _step_bytetrack(self, frame, frame_count: int):
        detect_interval = int(self._cfg("detect_interval_frames", 15))
        alpha = float(self._cfg("bbox_smooth_alpha", 0.3))
        min_iou = float(self._cfg("tracker_min_det_iou", 0.25))
        require_verified = bool(self._cfg("track_require_verified_det", True))

        run_detect = (frame_count % detect_interval == 0) or not self.tracks
        verified_ids: set = set()

        if run_detect:
            detections = self._run_detection(frame)
            if self._cfg("debug_scores", False) or frame_count % 60 == 0:
                scores = [round(float(d.get("score", 0)), 3) if isinstance(d, dict) else 0.9 for d in detections]
                print(f"[detect] frame={frame_count} found={len(detections)} scores={scores} tracks={len(self.tracks)}")
            xyxy = []
            det_by_idx = []
            for det in detections:
                x, y, w, h = self._det_bbox(det)
                score = float(det.get("score", 0.9)) if isinstance(det, dict) else 0.9
                xyxy.append((x, y, x + w, y + h, score))
                det_by_idx.append(det)

            bt_out = self._byte.update(frame, xyxy) if xyxy else {}

            for bt_id, bbox in bt_out.items():
                best_iou = 0.0
                best_det = None
                for det in det_by_idx:
                    dbbox = self._det_bbox(det)
                    iou = bbox_iou(dbbox, bbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_det = det

                if require_verified and (
                    best_det is None or best_iou < min_iou
                ):
                    continue

                auty_id = self._byte_id_map.get(bt_id)
                if auty_id is None or auty_id not in self.tracks:
                    auty_id = self.next_track_id
                    self.next_track_id += 1
                    track = self.new_track_fn(auty_id)
                    track["det_verified"] = False
                    self.tracks[auty_id] = track
                    self._byte_id_map[bt_id] = auty_id
                else:
                    track = self.tracks[auty_id]

                track["state"] = TrackState.ACTIVE
                track["missing_frames"] = 0
                track["last_seen"] = time.time()
                apply_smooth_bbox(track, bbox, alpha)
                self._apply_det_meta(track, best_det)
                track["det_verified"] = True
                track["stable_count"] = min(
                    track.get("stable_count", 0) + 1, 64
                )
                verified_ids.add(auty_id)

            self._age_stale_tracks(verified_ids, run_detect=True)
        else:
            self._age_stale_tracks(verified_ids, run_detect=False)

        self.prune_duplicate_identity_tracks()

    def step(self, frame, frame_count: int):
        backend = str(self._cfg("tracker_backend", "bytetrack")).lower()
        if backend == "bytetrack":
            self._step_bytetrack(frame, frame_count)
            return

        detect_interval = int(self._cfg("detect_interval_frames", 10))
        run_detect = (frame_count % detect_interval == 0) or not self.tracks

        if run_detect:
            detections = self._run_detection(frame)
            self._associate_detections(frame, detections)

        self._update_trackers(frame)
        self.prune_duplicate_identity_tracks()
