"""
Local LLM replies via Ollama (no API key, runs on your Mac).
"""

import json
import urllib.error
import urllib.request


class LocalConversation:
    def __init__(self, settings: dict):
        self.settings = settings
        self.enabled = bool(settings.get("local_llm_enabled", False))
        self.base_url = str(settings.get("ollama_base_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = str(settings.get("ollama_model", "llama3.2"))
        self.timeout = float(settings.get("ollama_timeout_seconds", 15.0))
        self._last_reply = ""
        self._last_at = 0.0

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2.0):
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def reply(
        self,
        user_context: str,
        name: str,
        mood: str,
        memory_snippet: str = "",
    ) -> str:
        if not self.enabled:
            return ""
        cooldown = float(self.settings.get("ollama_cooldown_seconds", 12.0))
        import time

        now = time.time()
        if now - self._last_at < cooldown:
            return self._last_reply

        system = (
            "You are Auty, a friendly face-recognition assistant on a computer screen. "
            "Keep replies to one short spoken sentence. No markdown."
        )
        prompt = (
            f"Person: {name}. Auty mood: {mood}. "
            f"{memory_snippet} "
            f"Context: {user_context}. "
            "Say something brief and natural."
        )
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"num_predict": 60, "temperature": 0.7},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = str(data.get("response", "")).strip()
            if text:
                self._last_reply = text
                self._last_at = now
            return text
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, KeyError):
            return ""

    @property
    def last_reply(self) -> str:
        return self._last_reply
