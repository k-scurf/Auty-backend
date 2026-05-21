"""ByteTrack multi-face association via boxmot."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from vision.config import get_cfg


class ByteTrackAdapter:
    """Associates detections to persistent track IDs."""

    def __init__(self):
        self._tracker = None
        self._init_tracker()

    def _init_tracker(self):
        try:
            from boxmot.trackers.bytetrack.bytetrack import ByteTrack

            self._tracker = ByteTrack(
                track_thresh=float(get_cfg("bytetrack_track_thresh", 0.5)),
                match_thresh=float(get_cfg("bytetrack_match_thresh", 0.8)),
                track_buffer=int(get_cfg("bytetrack_track_buffer", 30)),
            )
        except Exception as exc:
            print(f"[vision] ByteTrack unavailable ({exc}); using IoU association.")
            self._tracker = None

    def update(
        self, frame, detections_xyxy_scored: List[Tuple[float, float, float, float, float]]
    ) -> Dict[int, Tuple[int, int, int, int]]:
        """
        Input: list of (x1,y1,x2,y2,score) in pixel coords.
        Returns: byte_track_id -> (x,y,w,h)
        """
        if not detections_xyxy_scored:
            if self._tracker is not None:
                try:
                    self._tracker.update(np.empty((0, 6), dtype=np.float32), frame)
                except Exception:
                    pass
            return {}

        rows = [
            [x1, y1, x2, y2, score, 0.0]
            for x1, y1, x2, y2, score in detections_xyxy_scored
        ]
        dets = np.array(rows, dtype=np.float32)

        if self._tracker is None:
            return {i: self._xyxy_to_xywh(d[:4]) for i, d in enumerate(rows)}

        try:
            tracks = self._tracker.update(dets, frame)
        except Exception:
            return {i: self._xyxy_to_xywh(d[:4]) for i, d in enumerate(rows)}

        out = {}
        for row in tracks:
            if len(row) < 5:
                continue
            x1, y1, x2, y2, tid = row[:5]
            out[int(tid)] = self._xyxy_to_xywh((x1, y1, x2, y2))
        return out

    @staticmethod
    def _xyxy_to_xywh(box) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = box
        return int(x1), int(y1), int(max(1, x2 - x1)), int(max(1, y2 - y1))
