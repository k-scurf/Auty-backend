"""Scrollable activity log — known vs unknown entries with timestamps."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ui.theme import FONT_SMALL, THEME, make_button, make_label


class ActivityLogPanel(tk.Frame):
  MAX_LINES = 200

  def __init__(self, parent, **kwargs):
    super().__init__(parent, bg=THEME["bg_panel"], **kwargs)
    self._lines: list[str] = []

    header = tk.Frame(self, bg=THEME["bg_panel"])
    header.pack(fill="x", pady=(0, 8))
    make_label(header, "ACTIVITY LOG", style="section", anchor="w", side="left")
    make_button(
      header,
      "Clear",
      self.clear,
      secondary=True,
      side="right",
    )

    log_outer = tk.Frame(self, bg=THEME["border"], padx=1, pady=1)
    log_outer.pack(fill="both", expand=True)

    inner = tk.Frame(log_outer, bg=THEME["bg_inset"])
    inner.pack(fill="both", expand=True)

    self._scroll = tk.Scrollbar(inner, orient="vertical")
    self._scroll.pack(side="right", fill="y")

    self._text = tk.Text(
      inner,
      height=14,
      width=36,
      font=FONT_SMALL,
      bg=THEME["bg_inset"],
      fg=THEME["text"],
      insertbackground=THEME["text"],
      relief="flat",
      wrap="word",
      state="disabled",
      yscrollcommand=self._scroll.set,
      highlightthickness=0,
      bd=0,
      padx=10,
      pady=8,
    )
    self._text.pack(side="left", fill="both", expand=True)
    self._scroll.config(command=self._text.yview)

    self._text.tag_configure("known", foreground=THEME["accent"])
    self._text.tag_configure("unknown", foreground=THEME["accent_warm"])
    self._text.tag_configure("meta", foreground=THEME["text_muted"])
    self._text.tag_configure("time", foreground=THEME["text_muted"])

    make_label(
      self,
      "Known = matched database · Unknown = no match",
      style="caption",
      anchor="w",
      pady=(8, 0),
    )

  def clear(self):
    self._lines.clear()
    self._text.configure(state="normal")
    self._text.delete("1.0", "end")
    self._text.configure(state="disabled")

  def log_known(self, name: str, confidence: float = 0.0, *, when: float | None = None):
    pct = int(round(confidence * 100)) if confidence and confidence > 0 else 0
    detail = f"{name}" + (f"  ({pct}%)" if pct else "")
    self._append("KNOWN", detail, when=when, tag="known")

  def log_unknown(self, *, when: float | None = None, track_id: int | None = None):
    detail = "No match in database"
    if track_id is not None:
      detail += f"  · track {track_id}"
    self._append("UNKNOWN", detail, when=when, tag="unknown")

  def log_enrolled(self, name: str, *, when: float | None = None):
    self._append("ENROLLED", name, when=when, tag="known")

  def _append(self, kind: str, detail: str, *, when: float | None, tag: str):
    ts = time.localtime(when or time.time())
    stamp = time.strftime("%H:%M:%S", ts)
    line = f"{stamp}  {kind:<8}  {detail}\n"
    self._lines.append(line)
    if len(self._lines) > self.MAX_LINES:
      self._lines = self._lines[-self.MAX_LINES :]

    self._text.configure(state="normal")
    self._text.insert("end", stamp + "  ", "time")
    self._text.insert("end", f"{kind:<8}  ", tag)
    self._text.insert("end", detail + "\n", "meta")
    self._text.configure(state="disabled")
    self._text.see("end")
