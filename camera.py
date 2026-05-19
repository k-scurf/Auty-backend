"""
Video capture — read, flip, and resize to processing resolution.
"""

import cv2


class CameraStream:
    def __init__(self, settings: dict, process_width: int, process_height: int):
        self.cap = cv2.VideoCapture(int(settings["camera_index"]))
        self.process_width = process_width
        self.process_height = process_height

    def read(self):
        """Returns (ok, bgr_frame) at process resolution, mirrored."""
        ret, frame = self.cap.read()
        if not ret:
            return False, None
        frame = cv2.flip(frame, 1)
        frame = cv2.resize(
            frame,
            (self.process_width, self.process_height),
            interpolation=cv2.INTER_LINEAR,
        )
        return True, frame

    def release(self):
        self.cap.release()
