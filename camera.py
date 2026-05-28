"""
Video capture — read, flip, and resize to processing resolution.
"""

import glob
import os
import sys

import cv2


def local_camera_enabled(settings: dict) -> bool:
    """True when this machine should open a USB/system camera (not cloud/API-only)."""
    env = os.environ.get("AUTY_USE_LOCAL_CAMERA", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    if os.environ.get("AUTY_HEADLESS", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        return False
    if settings.get("use_local_camera") is False:
        return False
    idx = settings.get("camera_index")
    if idx is None or (isinstance(idx, (int, float)) and int(idx) < 0):
        return False
    if sys.platform == "linux" and not glob.glob("/dev/video*"):
        return False
    return True

# ── macOS: prevent startup freeze ────────────────────────────────────────────
# cv2.VideoCapture() requests camera permission via the system dialog when
# called from a background thread — but macOS will NOT show that dialog off
# the main thread, so the call hangs until it times out (can be several
# seconds).  Setting this env var tells AVFoundation to skip the auth request
# entirely; the user grants permission once in
#   System Settings → Privacy & Security → Camera → enable Terminal (or IDE).
if sys.platform == "darwin":
    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")


class CameraStream:
    def __init__(self, settings: dict, process_width: int, process_height: int):
        self.process_width = process_width
        self.process_height = process_height
        self._settings = settings
        self._index = int(settings.get("camera_index", 0))
        self.cap = None
        self.opened = False
        self._read_fail_streak = 0
        self.enabled = local_camera_enabled(settings)
        if not self.enabled:
            print(
                "[Auty] Local camera disabled (headless/API mode). "
                "Use the browser or iPad camera with /api/recognize-frame."
            )
            return
        self._open()

    def _open(self) -> bool:
        """Open camera; on macOS prefer AVFoundation (more reliable than default backend)."""
        # Always release the previous handle before opening a new one.
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        index = self._index
        if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
            self.cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        else:
            self.cap = cv2.VideoCapture(index)

        # Non-macOS fallback: if the default backend failed, try any available one.
        if not self.cap.isOpened() and sys.platform != "darwin":
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = cv2.VideoCapture(index)

        self.opened = bool(self.cap is not None and self.cap.isOpened())
        if not self.opened:
            print(
                f"[Auty] Could not open camera (index {index}). "
                "On macOS: System Settings → Privacy & Security → Camera → enable Terminal or your IDE. "
                "Try another index in data/settings.json (camera_index: 1)."
            )
            return False

        print(f"[Auty] Camera opened (index {index})")
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        # Two reads is enough to flush AVFoundation's initial empty frame.
        # Keeping this short avoids blocking the boot thread for a full second.
        for _ in range(2):
            self.cap.read()
        self._read_fail_streak = 0
        return True

    def read(self):
        """Returns (ok, bgr_frame) at process resolution, mirrored."""
        if not self.enabled or not self.opened:
            return False, None

        frame = None
        for _ in range(3):
            ret, raw = self.cap.read()
            if ret and raw is not None and raw.size > 0:
                frame = raw
                break

        if frame is None:
            self._read_fail_streak += 1
            if self._read_fail_streak >= 12:
                print(
                    f"[Auty] Camera read failing ({self._read_fail_streak}x) — reopening index {self._index}…"
                )
                self._open()
            return False, None

        self._read_fail_streak = 0
        frame = cv2.flip(frame, 1)
        frame = cv2.resize(
            frame,
            (self.process_width, self.process_height),
            interpolation=cv2.INTER_LINEAR,
        )
        return True, frame

    def release(self):
        if not self.enabled:
            return
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        self.opened = False
