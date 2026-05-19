"""
Voice command listener (microphone → text → intent) using SpeechRecognition.
"""

import re
import threading
import time
from typing import Callable, Optional

# (intent, patterns) — matched case-insensitively on normalized text
COMMAND_PATTERNS = [
    ("whoami", r"\b(who am i|what'?s my name|what do you call me|identify me|recognize me)\b"),
    ("feeling", r"\b(how am i feeling|what'?s my mood|my emotion|how do i look|what emotion)\b"),
    ("greet", r"\b(hello|hi auty|hey auty|greet me|say hello|good (morning|afternoon|evening))\b"),
    ("repeat", r"\b(repeat|say that again|what did you say|say again)\b"),
    ("status", r"\b(status|what are you doing|what'?s your state|how are you)\b"),
    ("help", r"\b(help|what can you do|commands|what can i say)\b"),
    ("mute", r"\b(mute|be quiet|stop talking|silence|shush)\b"),
    ("unmute", r"\b(unmute|speak|talk again|you can talk)\b"),
    ("thanks", r"\b(thanks|thank you|nice|good job)\b"),
]


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_command(text: str) -> Optional[str]:
    norm = normalize_text(text)
    if not norm:
        return None
    for intent, pattern in COMMAND_PATTERNS:
        if re.search(pattern, norm):
            return intent
    # Short fuzzy fallbacks
    if "name" in norm and ("what" in norm or "who" in norm):
        return "whoami"
    if "feel" in norm or "emotion" in norm or "mood" in norm:
        return "feeling"
    return None


class VoiceCommandListener:
    def __init__(
        self,
        settings: dict,
        on_command: Callable[[str, str], None],
        on_state: Optional[Callable[[str], None]] = None,
    ):
        self.settings = settings
        self.enabled = bool(settings.get("voice_commands_enabled", True))
        self.on_command = on_command
        self.on_state = on_state
        self._recognizer = None
        self._mic = None
        self._use_sounddevice = False
        self._running = False
        self._listen_thread = None
        self._continuous = False
        self._last_heard = ""
        self._last_at = 0.0
        self._init_recognizer()

    def _init_recognizer(self):
        if not self.enabled:
            return
        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.energy_threshold = int(
                self.settings.get("voice_energy_threshold", 300)
            )
            self._recognizer.pause_threshold = float(
                self.settings.get("voice_pause_threshold", 0.7)
            )
            try:
                self._mic = sr.Microphone()
                with self._mic as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                self._use_sounddevice = False
            except Exception:
                import sounddevice  # noqa: F401

                self._mic = None
                self._use_sounddevice = True
            print("[Auty] Voice commands ready — tap the mic button or enable always-on.")
        except Exception as exc:
            self.enabled = False
            print(
                "[Auty] Voice commands disabled. Install:\n"
                f"  {__import__('sys').executable} -m pip install SpeechRecognition sounddevice\n"
                f"  Optional: brew install portaudio && pip install pyaudio\n"
                f"  ({type(exc).__name__}: {exc})"
            )

    def _set_state(self, mode: str):
        if self.on_state:
            try:
                self.on_state(mode)
            except Exception:
                pass

    def _listen_once_blocking(self) -> Optional[str]:
        if not self.enabled or not self._recognizer:
            return None
        if self._use_sounddevice:
            return self._listen_sounddevice()
        if not self._mic:
            return None
        import speech_recognition as sr

        timeout = float(self.settings.get("voice_listen_timeout", 4.0))
        phrase_limit = float(self.settings.get("voice_phrase_limit", 6.0))
        try:
            with self._mic as source:
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_limit,
                )
            return self._recognize_audio(audio)
        except sr.WaitTimeoutError:
            return None
        except Exception as exc:
            print(f"[Auty] Listen error: {exc}")
            return None

    def _listen_sounddevice(self) -> Optional[str]:
        import speech_recognition as sr
        import sounddevice as sd

        phrase_limit = float(self.settings.get("voice_phrase_limit", 6.0))
        samplerate = 16000
        frames = int(samplerate * phrase_limit)
        try:
            recording = sd.rec(frames, samplerate=samplerate, channels=1, dtype="int16")
            sd.wait()
            audio_data = sr.AudioData(recording.tobytes(), samplerate, 2)
            return self._recognize_audio(audio_data)
        except Exception as exc:
            print(f"[Auty] Microphone error: {exc}")
            return None

    def _recognize_audio(self, audio) -> Optional[str]:
        import speech_recognition as sr

        lang = str(self.settings.get("voice_language", "en-US"))
        prefer_offline = bool(self.settings.get("voice_prefer_offline", False))

        if prefer_offline:
            try:
                return self._recognizer.recognize_sphinx(audio, language="en-US")
            except Exception:
                pass

        try:
            return self._recognizer.recognize_google(audio, language=lang)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            print(f"[Auty] Speech API error: {exc}")
            try:
                return self._recognizer.recognize_sphinx(audio)
            except Exception:
                return None

    def listen_push_to_talk(self, *, is_speaking: Callable[[], bool] = lambda: False):
        if not self.enabled or self._running:
            return
        if is_speaking():
            return

        def worker():
            self._running = True
            self._set_state("listening")
            text = self._listen_once_blocking()
            self._set_state("idle")
            self._running = False
            if text:
                self._dispatch(text)

        threading.Thread(target=worker, daemon=True, name="auty-ptt").start()

    def _dispatch(self, text: str):
        self._last_heard = text
        self._last_at = time.time()
        intent = parse_command(text)
        if intent:
            self.on_command(intent, text)
        else:
            self.on_command("unknown", text)

    def set_continuous(self, on: bool, *, is_speaking: Callable[[], bool] = lambda: False):
        self._continuous = on
        if on:
            self._start_continuous(is_speaking=is_speaking)
        else:
            self._stop_continuous()

    def _start_continuous(self, *, is_speaking: Callable[[], bool]):
        if self._listen_thread and self._listen_thread.is_alive():
            return

        def loop():
            cooldown = float(self.settings.get("voice_command_cooldown", 1.5))
            while self._continuous and self.enabled:
                if is_speaking():
                    time.sleep(0.2)
                    continue
                self._set_state("listening")
                text = self._listen_once_blocking()
                self._set_state("idle")
                if text:
                    self._dispatch(text)
                    time.sleep(cooldown)
                else:
                    time.sleep(0.15)

        self._listen_thread = threading.Thread(target=loop, daemon=True)
        self._listen_thread.start()

    def _stop_continuous(self):
        self._continuous = False
        self._set_state("idle")
