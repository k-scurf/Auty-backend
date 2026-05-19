"""
Screen-only visual effects: idle scan, attention ring, greeting bar.
"""

import cv2
import numpy as np


class UIEffects:
    def __init__(self, settings: dict):
        self.settings = settings

    def draw(
        self,
        frame,
        state: str,
        mood: str,
        active_bbox=None,
        greeting_line: str = "",
        frame_count: int = 0,
    ):
        if not self.settings.get("ui_effects_enabled", True):
            return frame

        fh, fw = frame.shape[:2]

        if state in ("IDLE", "DETECTING") and self.settings.get("idle_scan_enabled", True):
            y = int((frame_count * 3) % fh)
            cv2.line(frame, (0, y), (fw, y), (0, 180, 160), 1, cv2.LINE_AA)
            overlay = frame.copy()
            cv2.line(overlay, (0, y), (fw, y), (0, 255, 220), 2, cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

        if active_bbox and state in ("Tracking", "Greeting", "Conversing", "Alert"):
            x, y, w, h = [int(v) for v in active_bbox]
            cx, cy = x + w // 2, y + h // 2
            radius = int(max(w, h) * 0.65)
            color = (0, 220, 180) if state != "ALERT" else (80, 140, 255)
            cv2.circle(frame, (cx, cy), radius, color, 2, cv2.LINE_AA)
            pulse = 1.0 + 0.08 * np.sin(frame_count * 0.15)
            cv2.circle(
                frame,
                (cx, cy),
                int(radius * pulse),
                color,
                1,
                cv2.LINE_AA,
            )

        if greeting_line and self.settings.get("greeting_bar_enabled", True):
            bar_h = 36
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (fw, bar_h), (14, 24, 32), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
            cv2.putText(
                frame,
                greeting_line[:80],
                (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 230, 200),
                1,
                cv2.LINE_AA,
            )

        return frame
