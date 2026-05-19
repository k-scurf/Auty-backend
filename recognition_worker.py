"""
Run ArcFace embedding extraction off the UI thread so the camera stays smooth.
"""

import queue
import threading
from typing import Optional, Tuple

import numpy as np

import recognition as rec


class RecognitionWorker:
    def __init__(self):
        self._jobs = queue.Queue(maxsize=1)
        self._results = queue.Queue()
        self._pending_ids = set()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auty-rec")
        self._thread.start()

    def submit(self, track_id: int, aligned_bgr: np.ndarray) -> bool:
        if track_id in self._pending_ids:
            return False
        try:
            self._jobs.put_nowait((track_id, aligned_bgr.copy()))
            self._pending_ids.add(track_id)
            return True
        except queue.Full:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                pass
            try:
                self._jobs.put_nowait((track_id, aligned_bgr.copy()))
                self._pending_ids.add(track_id)
                return True
            except queue.Full:
                return False

    def poll(self) -> list[Tuple[int, Optional[np.ndarray]]]:
        out = []
        while True:
            try:
                tid, embedding = self._results.get_nowait()
                self._pending_ids.discard(tid)
                out.append((tid, embedding))
            except queue.Empty:
                break
        return out

    def _loop(self):
        while True:
            track_id, aligned = self._jobs.get()
            try:
                embedding = rec.extract_embedding(
                    aligned, already_aligned=rec.is_aligned_crop(aligned)
                )
            except Exception:
                embedding = None
            self._results.put((track_id, embedding))
