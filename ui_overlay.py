"""
Futuristic HUD profile cards — compact name / age / status layout.
"""

import os
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ui.theme import HUD_KNOWN, HUD_UNKNOWN

THEME_KNOWN = HUD_KNOWN
THEME_UNKNOWN = HUD_UNKNOWN


def resolve_status(name, profiles):
    if name == "UNKNOWN":
        return "UNKNOWN"
    prof = profiles.get(name, {})
    raw = str(prof.get("status", "")).strip()
    if not raw:
        return "FRIEND"
    upper = raw.upper()
    if "OWNER" in upper:
        return "OWNER"
    return upper


def profile_fields(name, profiles):
    """Name, age, status for HUD display."""
    if name == "UNKNOWN":
        return "Unknown", "—", "UNKNOWN"
    prof = profiles.get(name, {})
    display_name = str(prof.get("name", name)).strip() or name
    age = str(prof.get("age", "")).strip() or "—"
    status = resolve_status(name, profiles)
    return display_name, age, status


class HUDRenderer:
    def __init__(self, settings: dict, capture_folder: str = "captures"):
        self.settings = settings
        self.capture_folder = capture_folder
        self._ui = {}
        self._font_path = self._resolve_font_path()
        self._font_cache = {}
        self._fonts = None

    def _resolve_font_path(self):
        for p in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ):
            if os.path.exists(p):
                return p
        return "/System/Library/Fonts/Supplemental/Arial.ttf"

    def _load_fonts(self):
        """Readable sizes — scaled via hud_card_width in _fonts_for_card."""
        return self._fonts_for_card(int(self._cfg("hud_card_width", 300)))

    def _fonts_for_card(self, card_w):
        if card_w in getattr(self, "_font_cache", {}):
            return self._font_cache[card_w]
        if not hasattr(self, "_font_cache"):
            self._font_cache = {}
        scale = card_w / 240.0
        try:
            fonts = {
                "name": ImageFont.truetype(self._font_path, max(14, int(17 * scale))),
                "row": ImageFont.truetype(self._font_path, max(10, int(13 * scale))),
                "label": ImageFont.truetype(self._font_path, max(9, int(11 * scale))),
                "tiny": ImageFont.truetype(self._font_path, max(8, int(10 * scale))),
            }
        except OSError:
            d = ImageFont.load_default()
            fonts = {"name": d, "row": d, "label": d, "tiny": d}
        self._font_cache[card_w] = fonts
        return fonts

    def _cfg(self, key, default):
        return self.settings.get(key, default)

    def _ui_state(self, track_id):
        if track_id not in self._ui:
            self._ui[track_id] = {
                "card_x": None,
                "card_y": None,
                "fade": 0.0,
                "pulse": 0.0,
                "last_snapshot_at": 0.0,
            }
        return self._ui[track_id]

    def _target_card_pos(self, bbox, frame_w, frame_h, card_w, card_h):
        x, y, w, h = bbox
        gap = 10
        cx, cy = x + w + gap, y
        if cx + card_w > frame_w - 8:
            cx = max(8, x - card_w - gap)
        cy = max(8, min(cy, frame_h - card_h - 8))
        return int(cx), int(cy)

    def _smooth_pos(self, track_id, target_x, target_y):
        alpha = float(self._cfg("hud_smooth_alpha", 0.25))
        st = self._ui_state(track_id)
        if st["card_x"] is None:
            st["card_x"], st["card_y"] = float(target_x), float(target_y)
        else:
            st["card_x"] = st["card_x"] * (1 - alpha) + target_x * alpha
            st["card_y"] = st["card_y"] * (1 - alpha) + target_y * alpha
        return int(st["card_x"]), int(st["card_y"])

    def _draw_row(self, draw, x, y, label, value, fonts, theme, fade, *, label_w=48):
        draw.text((x, y), label, fill=(*theme["label"][:3], int(200 * fade)), font=fonts["label"])
        draw.text(
            (x + label_w, y),
            value,
            fill=(*theme["accent"][:3], int(230 * fade)),
            font=fonts["row"],
        )

    def _draw_card_pil(self, frame, cx, cy, track, profiles, frame_count, brain_ctx=None):
        tid = track["id"]
        locked = track.get("locked_name", "UNKNOWN")
        known = locked != "UNKNOWN"
        theme = THEME_KNOWN if known else THEME_UNKNOWN
        memory_line = ""
        user_feeling = "—"
        if brain_ctx is not None:
            theme = brain_ctx.track_themes.get(tid, theme)
            memory_line = brain_ctx.memory_lines.get(tid, "")
            user_feeling = brain_ctx.user_feelings.get(tid, "—")
        score = track.get("locked_score")
        conf_pct = int(score * 100) if score is not None and score >= 0 else 0

        display_name, age, status = profile_fields(locked, profiles)

        card_w = int(self._cfg("hud_card_width", 300))
        card_h = int(self._cfg("hud_card_height", 140))
        scale = card_w / 240.0
        pad = int(14 * scale)
        radius = int(12 * scale)
        fonts = self._fonts_for_card(card_w)

        fh, fw = frame.shape[:2]
        cx, cy = self._smooth_pos(tid, cx, cy)
        cx = max(4, min(cx, fw - card_w - 4))
        cy = max(4, min(cy, fh - card_h - 4))

        st = self._ui_state(tid)
        st["fade"] = min(1.0, st["fade"] + 0.1) if self._cfg("hud_fade_in", True) else 1.0
        fade = st["fade"]

        if self._cfg("hud_pulse_on_recognize", True) and known:
            st["pulse"] = (st["pulse"] + 0.12) % (2 * np.pi)
        pulse = 1.0 + 0.04 * np.sin(st["pulse"]) if known else 1.0

        overlay = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        x1, y1 = cx, cy
        x2, y2 = cx + card_w, cy + card_h

        for expand in (4, 1):
            draw.rounded_rectangle(
                (x1 - expand, y1 - expand, x2 + expand, y2 + expand),
                radius=radius + expand,
                fill=(*theme["glow"][:3], int(theme["glow"][3] * fade * 0.85)),
            )

        fill = theme.get("fill", (18, 24, 32, 215))
        draw.rounded_rectangle(
            (x1, y1, x2, y2), radius=radius, fill=(*fill[:3], int(fill[3] * fade))
        )
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=radius,
            outline=(*theme["border"][:3], int(240 * fade)),
            width=2,
        )

        # Accent strip under top edge
        draw.rectangle(
            (x1 + 1, y1 + 1, x2 - 1, y1 + 3),
            fill=(*theme["border"][:3], int(180 * fade)),
        )

        row_y = y1 + pad
        # Name + small confidence badge on the right
        draw.text(
            (x1 + pad, row_y),
            display_name,
            fill=(*theme["accent"][:3], int(255 * fade)),
            font=fonts["name"],
        )
        conf_text = f"{conf_pct}%"
        draw.text(
            (x2 - pad - int(34 * scale), row_y + 2),
            conf_text,
            fill=(*theme["muted"][:3], int(200 * fade)),
            font=fonts["tiny"],
        )

        row_y += int(24 * scale)
        label_w = int(52 * scale)
        self._draw_row(draw, x1 + pad, row_y, "Age", age, fonts, theme, fade, label_w=label_w)
        row_y += int(22 * scale)
        self._draw_row(draw, x1 + pad, row_y, "Status", status, fonts, theme, fade, label_w=label_w)
        if self._cfg("user_emotion_enabled", False):
            row_y += int(22 * scale)
            self._draw_row(
                draw, x1 + pad, row_y, "Feeling", user_feeling, fonts, theme, fade, label_w=label_w
            )

        if memory_line:
            row_y += int(20 * scale)
            draw.text(
                (x1 + pad, row_y),
                memory_line[:42],
                fill=(*theme["muted"][:3], int(180 * fade)),
                font=fonts["tiny"],
            )

        bar_h = max(5, int(6 * scale))
        bar_y = y2 - pad - bar_h
        bar_x1, bar_x2 = x1 + pad, x2 - pad
        draw.rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h), fill=(30, 38, 48, int(200 * fade)))
        fill_w = int((bar_x2 - bar_x1) * (conf_pct / 100.0) * pulse)
        if fill_w > 0:
            draw.rectangle(
                (bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                fill=(*theme["bar"][:3], int(255 * fade)),
            )

        if self._cfg("hud_scan_line", True):
            scan_y = y1 + pad + (frame_count % max(1, card_h - 2 * pad))
            draw.line(
                (x1 + pad, scan_y, x2 - pad, scan_y),
                fill=(*theme["border"][:3], int(50 * fade)),
                width=1,
            )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        base = Image.fromarray(rgb).convert("RGBA")
        composed = Image.alpha_composite(base, overlay)
        return cv2.cvtColor(np.array(composed.convert("RGB")), cv2.COLOR_RGB2BGR)

    def _draw_bbox(self, frame, bbox, known):
        x, y, w, h = [int(v) for v in bbox]
        color = (0, 220, 180) if known else (80, 140, 255)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

    def _maybe_snapshot_unknown(self, track, frame, bbox):
        if not self._cfg("hud_unknown_auto_snapshot", True):
            return
        if track.get("locked_name", "UNKNOWN") != "UNKNOWN":
            return
        interval = float(self._cfg("hud_unknown_snapshot_interval", 30))
        st = self._ui_state(track["id"])
        now = time.time()
        if now - st["last_snapshot_at"] < interval:
            return
        x, y, w, h = [int(v) for v in bbox]
        crop = frame[max(0, y) : y + h, max(0, x) : x + w]
        if crop.size == 0:
            return
        path = os.path.join(self.capture_folder, f"unknown_{track['id']}_{int(now)}.jpg")
        cv2.imwrite(path, crop)
        st["last_snapshot_at"] = now

    def draw_all(
        self,
        frame,
        tracks,
        profiles,
        frame_count,
        brain_ctx=None,
        primary_track_id=None,
    ):
        if not self._cfg("hud_enabled", True):
            return frame

        card_w = int(self._cfg("hud_card_width", 300))
        card_h = int(self._cfg("hud_card_height", 140))
        fh, fw = frame.shape[:2]
        primary_only = bool(self._cfg("hud_primary_only", True))
        active_ids = {t["id"] for t in tracks}

        for tid in list(self._ui.keys()):
            if tid not in active_ids:
                del self._ui[tid]

        for track in tracks:
            if primary_only and primary_track_id is not None:
                if track["id"] != primary_track_id:
                    continue
            if track.get("missing_frames", 0) > 0:
                continue
            if bool(self._cfg("track_require_verified_det", True)) and not track.get(
                "det_verified", False
            ):
                continue
            bbox = track.get("smooth_bbox") or track.get("bbox")
            if not bbox:
                continue
            known = track.get("locked_name", "UNKNOWN") != "UNKNOWN"
            if self._cfg("hud_draw_bbox", True):
                self._draw_bbox(frame, bbox, known)
            tx, ty = self._target_card_pos(bbox, fw, fh, card_w, card_h)
            frame = self._draw_card_pil(
                frame, tx, ty, track, profiles, frame_count, brain_ctx=brain_ctx
            )
            self._maybe_snapshot_unknown(track, frame, bbox)

        return frame
