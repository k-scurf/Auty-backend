"""
Run ArcFace embedding extraction off the UI thread so the camera stays smooth.
"""

import queue
import threading
from typing import Optional, Tuple

import numpy as np

import recognition as rec


class RecognitionWorker:
    def __init__(self, max_queue: int = 2):
        self._jobs: queue.Queue = queue.Queue(maxsize=max_queue)
        self._results = queue.Queue()
        self._pending_ids = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auty-rec")
        self._thread.start()

    def submit(self, track_id: int, aligned_bgr: np.ndarray) -> bool:
        if self._stop.is_set() or track_id in self._pending_ids:
            return False
        job = (track_id, aligned_bgr.copy())
        try:
            self._jobs.put_nowait(job)
            self._pending_ids.add(track_id)
            return True
        except queue.Full:
            try:
                dropped = self._jobs.get_nowait()
                self._pending_ids.discard(dropped[0])
            except queue.Empty:
                pass
            try:
                self._jobs.put_nowait(job)
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

    def shutdown(self):
        self._stop.set()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass

    def _loop(self):
        while not self._stop.is_set():
            job = self._jobs.get()
            if job is None:
                continue
            track_id, aligned = job
            try:
                embedding = rec.extract_embedding(
                    aligned, already_aligned=rec.is_aligned_crop(aligned)
                )
            except Exception:
                embedding = None
            self._results.put((track_id, embedding))
