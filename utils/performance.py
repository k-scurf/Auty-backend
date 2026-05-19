"""Lightweight performance helpers."""

import time


class DebouncedSaver:
    def __init__(self, save_fn, delay_seconds: float = 5.0):
        self._save_fn = save_fn
        self._delay = delay_seconds
        self._dirty = False
        self._last_save = 0.0

    def mark_dirty(self):
        self._dirty = True

    def maybe_flush(self, force: bool = False):
        if not self._dirty and not force:
            return
        now = time.time()
        if force or (now - self._last_save) >= self._delay:
            self._save_fn()
            self._dirty = False
            self._last_save = now
