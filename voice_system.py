"""
Offline TTS via pyttsx3 (background thread).
"""

import queue
import sys
import threading
import time


class VoiceSystem:
    def __init__(self, settings: dict):
        self.settings = settings
        self.enabled = bool(
            settings.get("voice_enabled", False)
            and settings.get("tts_enabled", False)
        )
        self._queue = queue.Queue()
        self._last_spoken = ""
        self._last_at = 0.0
        self._recent = []
        self._engine = None
        self._thread = None
        self._speaking = False
        self._state_listeners = []
        self._init_engine()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def add_state_listener(self, callback):
        self._state_listeners.append(callback)

    def _notify_state(self, mode: str):
        for cb in self._state_listeners:
            try:
                cb(mode)
            except Exception:
                pass

    def _set_speaking(self, speaking: bool):
        if self._speaking == speaking:
            return
        self._speaking = speaking
        self._notify_state("speaking" if speaking else "idle")

    def _init_engine(self):
        if not self.enabled:
            return
        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            rate = int(self.settings.get("tts_rate", 175))
            self._engine.setProperty("rate", rate)
            vol = float(self.settings.get("tts_volume", 0.9))
            self._engine.setProperty("volume", max(0.0, min(1.0, vol)))
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        except Exception as exc:
            self.enabled = False
            self._engine = None
            print(
                "[Auty] Voice disabled — install TTS for this Python:\n"
                f"  {sys.executable} -m pip install pyttsx3\n"
                f"  ({type(exc).__name__}: {exc})"
            )

    def _worker(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            if not self._engine:
                continue
            try:
                self._set_speaking(True)
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception:
                pass
            finally:
                if self._queue.empty():
                    self._set_speaking(False)

    def speak(self, text: str, *, force: bool = False) -> bool:
        if not self.enabled or not text or not text.strip():
            return False
        text = text.strip()
        cooldown = float(self.settings.get("tts_cooldown_seconds", 4.0))
        now = time.time()
        if not force and now - self._last_at < cooldown:
            return False
        if not force and text == self._last_spoken:
            return False
        recent_limit = int(self.settings.get("tts_anti_repeat", 5))
        if not force and text in self._recent[-recent_limit:]:
            return False

        self._queue.put(text)
        self._last_spoken = text
        self._last_at = now
        self._recent.append(text)
        if len(self._recent) > recent_limit * 2:
            self._recent = self._recent[-recent_limit:]
        return True

    @property
    def last_spoken(self) -> str:
        return self._last_spoken
