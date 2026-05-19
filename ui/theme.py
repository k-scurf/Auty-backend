"""Shared colors, fonts, and Tk widget factories for Auty."""

import tkinter as tk

THEME = {
    "bg_root": "#f4fbf8",
    "bg_panel": "#ffffff",
    "bg_card": "#ffffff",
    "header_bg": "#e8faf3",
    "border": "#c5e8dc",
    "border_soft": "#e2f0ea",
    "accent": "#0d9488",
    "accent_light": "#14b8a6",
    "accent_warm": "#f59e0b",
    "success": "#22c55e",
    "text": "#134e4a",
    "text_muted": "#5f7a73",
    "input_bg": "#f8fffc",
    "btn_secondary_bg": "#eef7f3",
    "btn_secondary_fg": "#0f766e",
    "known_bgr": (56, 180, 100),
    "unknown_bgr": (100, 190, 255),
}

FONT = ("Helvetica Neue", 13)
FONT_BOLD = ("Helvetica Neue", 13, "bold")
FONT_TITLE = ("Helvetica Neue", 24, "bold")
FONT_SECTION = ("Helvetica Neue", 11, "bold")
FONT_SMALL = ("Helvetica Neue", 11)

FEED_W, FEED_H = 960, 540
PROCESS_W, PROCESS_H = FEED_W, FEED_H
PREVIEW_SIZE = 320
PREVIEW_ZOOM_SIZE = 520

ENROLL_SAMPLE_COUNT = 12
ENROLL_FRAME_GAP = 3
ENROLL_COOLDOWN_SEC = 5


def make_label(parent, text, *, style="body", anchor=None, **pack_kw):
    styles = {
        "title": (FONT_TITLE, THEME["accent"], THEME["bg_panel"]),
        "section": (FONT_SECTION, THEME["accent_light"], THEME["bg_panel"]),
        "body": (FONT, THEME["text"], THEME["bg_panel"]),
        "muted": (FONT_SMALL, THEME["text_muted"], THEME["bg_panel"]),
        "header_title": (FONT_TITLE, THEME["accent"], THEME["header_bg"]),
        "header_sub": (FONT_SMALL, THEME["text_muted"], THEME["header_bg"]),
        "live": (FONT_BOLD, THEME["success"], THEME["bg_card"]),
        "tagline": (FONT_SMALL, THEME["accent_warm"], THEME["header_bg"]),
    }
    font, fg, bg = styles.get(style, styles["body"])
    kw = {"text": text, "font": font, "fg": fg, "bg": bg}
    if anchor is not None:
        kw["anchor"] = anchor
    lbl = tk.Label(parent, **kw)
    if pack_kw:
        lbl.pack(**pack_kw)
    return lbl


def make_entry(parent, **pack_kw):
    entry = tk.Entry(
        parent,
        width=32,
        font=FONT,
        bg=THEME["input_bg"],
        fg=THEME["text"],
        insertbackground=THEME["text"],
        relief="flat",
        highlightthickness=1,
        highlightbackground=THEME["border"],
        highlightcolor=THEME["accent"],
    )
    if pack_kw:
        entry.pack(**pack_kw)
    return entry


def make_button(parent, text, command, *, secondary=False, **pack_kw):
    if secondary:
        bg = THEME["btn_secondary_bg"]
        fg = THEME["btn_secondary_fg"]
        active_bg = THEME["border_soft"]
        active_fg = THEME["accent"]
    else:
        bg = THEME["accent"]
        fg = "white"
        active_bg = THEME["accent_light"]
        active_fg = "white"
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        font=FONT_BOLD,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=active_fg,
        relief="flat",
        cursor="hand2",
        padx=24,
        pady=12,
        bd=0,
        highlightthickness=0,
    )
    if pack_kw:
        btn.pack(**pack_kw)
    return btn
