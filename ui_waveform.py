"""
Animated voice waveform for the side panel (idle / listening / speaking).
"""

import math
import tkinter as tk


class WaveformPanel(tk.Frame):
    MODES = ("idle", "listening", "speaking")

    def __init__(self, parent, theme: dict, *, width=332, height=72, bars=28):
        super().__init__(parent, bg=theme["bg_panel"])
        self.theme = theme
        self.width = width
        self.height = height
        self.bars = bars
        self.mode = "idle"
        self._phase = 0.0
        self._levels = [0.12] * bars
        self._job = None

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=theme["bg_card"],
            highlightthickness=1,
            highlightbackground=theme["border"],
            bd=0,
        )
        self.canvas.pack(fill="x")

        self.status_lbl = tk.Label(
            self,
            text="Voice idle",
            font=("Helvetica Neue", 10),
            fg=theme["text_muted"],
            bg=theme["bg_panel"],
            anchor="w",
        )
        self.status_lbl.pack(fill="x", pady=(6, 0))

        self._draw_static()
        self.after(80, self._tick)

    def set_mode(self, mode: str, status_text: str = None):
        if mode not in self.MODES:
            mode = "idle"
        self.mode = mode
        labels = {
            "idle": "Voice idle",
            "listening": "Listening…",
            "speaking": "Auty is speaking",
        }
        self.status_lbl.config(
            text=status_text or labels.get(mode, "Voice"),
            fg=self.theme["accent"] if mode != "idle" else self.theme["text_muted"],
        )

    def _tick(self):
        self._phase += 0.22 if self.mode == "speaking" else 0.14
        target_amp = {"idle": 0.10, "listening": 0.38, "speaking": 0.92}[self.mode]
        import random

        for i in range(self.bars):
            center = abs(i - self.bars / 2) / (self.bars / 2)
            wave = math.sin(self._phase + i * 0.45) * (1.0 - center * 0.35)
            if self.mode == "speaking":
                wave += random.uniform(-0.12, 0.12)
            elif self.mode == "listening":
                wave += math.sin(self._phase * 0.7 + i * 0.2) * 0.15
            target = max(0.06, min(1.0, target_amp * (0.55 + 0.45 * abs(wave))))
            self._levels[i] = self._levels[i] * 0.72 + target * 0.28

        self._draw_bars()
        self._job = self.after(50, self._tick)

    def _draw_static(self):
        self.canvas.delete("all")
        self.canvas.create_rectangle(
            0, 0, self.width, self.height, fill=self.theme["bg_card"], outline=""
        )

    def _draw_bars(self):
        self._draw_static()
        gap = 3
        bar_w = max(2, (self.width - gap * (self.bars + 1)) // self.bars)
        mid = self.height / 2
        accent = self.theme["accent"]
        listen = self.theme["accent_light"]
        muted = self.theme["border"]

        for i, level in enumerate(self._levels):
            x0 = gap + i * (bar_w + gap)
            h = max(4, int(level * (self.height - 12)))
            y0 = mid - h / 2
            y1 = mid + h / 2
            if self.mode == "speaking":
                color = accent
            elif self.mode == "listening":
                color = listen
            else:
                color = muted
            self.canvas.create_rectangle(x0, y0, x0 + bar_w, y1, fill=color, outline="")

    def destroy(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
        super().destroy()
