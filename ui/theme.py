"""Shared dark-glass colors, fonts, and Tk widget factories for Auty."""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

THEME = {
    "bg_root": "#0b0f14",
    "bg_panel": "#121820",
    "bg_card": "#1a222d",
    "bg_inset": "#0f141c",
    "header_bg": "#0b0f14",
    "border": "#2a3544",
    "border_soft": "#1e2836",
    "accent": "#2dd4bf",
    "accent_light": "#5eead4",
    "accent_warm": "#f59e0b",
    "success": "#34d399",
    "text": "#e2e8f0",
    "text_muted": "#94a3b8",
    "input_bg": "#0f141c",
    "btn_secondary_bg": "#1e2836",
    "btn_secondary_fg": "#e2e8f0",
    "btn_primary_bg": "#2dd4bf",
    "btn_primary_fg": "#0b0f14",
    "btn_radius_border": "#3d4f63",
    "known_bgr": (45, 212, 191),
    "unknown_bgr": (251, 146, 60),
}

# PIL HUD overlays (RGBA)
HUD_KNOWN = {
    "border": (45, 212, 191, 255),
    "glow": (45, 212, 191, 45),
    "accent": (226, 232, 240, 255),
    "muted": (148, 163, 184, 255),
    "bar": (45, 212, 191, 255),
    "label": (100, 116, 139, 255),
    "fill": (18, 24, 32, 215),
}
HUD_UNKNOWN = {
    "border": (251, 146, 60, 255),
    "glow": (251, 146, 60, 50),
    "accent": (254, 215, 170, 255),
    "muted": (180, 160, 140, 255),
    "bar": (251, 146, 60, 255),
    "label": (148, 130, 115, 255),
    "fill": (22, 18, 16, 215),
}

FONT = ("Helvetica Neue", 13)
FONT_BOLD = ("Helvetica Neue", 13, "bold")
FONT_TITLE = ("Helvetica Neue", 22, "bold")
FONT_SECTION = ("Helvetica Neue", 10, "bold")
FONT_SMALL = ("Helvetica Neue", 11)
FONT_CAPTION = ("Helvetica Neue", 10)

FEED_W, FEED_H = 960, 540
PROCESS_W, PROCESS_H = FEED_W, FEED_H
SIDEBAR_WIDTH = 360
COLLAPSE_RAIL_WIDTH = 44
SNAPSHOT_W, SNAPSHOT_H = 280, 350
PREVIEW_ZOOM_SIZE = 520

ENROLL_SAMPLE_COUNT = 12
ENROLL_FRAME_GAP = 3
ENROLL_COOLDOWN_SEC = 5


def make_label(parent, text, *, style="body", anchor=None, bg=None, **pack_kw):
    styles = {
        "title": (FONT_TITLE, THEME["text"], bg or THEME["bg_panel"]),
        "section": (FONT_SECTION, THEME["accent"], bg or THEME["bg_panel"]),
        "body": (FONT, THEME["text"], bg or THEME["bg_panel"]),
        "muted": (FONT_SMALL, THEME["text_muted"], bg or THEME["bg_panel"]),
        "caption": (FONT_CAPTION, THEME["text_muted"], bg or THEME["bg_panel"]),
        "header_title": (FONT_TITLE, THEME["text"], bg or THEME["header_bg"]),
        "header_sub": (FONT_SMALL, THEME["text_muted"], bg or THEME["header_bg"]),
        "live": (FONT_BOLD, THEME["success"], bg or THEME["bg_card"]),
    }
    font, fg, default_bg = styles.get(style, styles["body"])
    kw = {"text": text, "font": font, "fg": fg, "bg": bg or default_bg}
    if anchor is not None:
        kw["anchor"] = anchor
    lbl = tk.Label(parent, **kw)
    if pack_kw:
        lbl.pack(**pack_kw)
    return lbl


def make_entry(parent, **pack_kw):
    entry = tk.Entry(
        parent,
        width=28,
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
    """Pill-style button with a thin border ring."""
    if secondary:
        ring = THEME["btn_radius_border"]
        face = THEME["bg_card"]
        fg = THEME["btn_secondary_fg"]
        active_face = THEME["btn_secondary_bg"]
        active_fg = THEME["text"]
    else:
        ring = THEME["btn_primary_bg"]
        face = THEME["btn_primary_bg"]
        fg = THEME["btn_primary_fg"]
        active_face = THEME["accent_light"]
        active_fg = THEME["btn_primary_fg"]

    outer = tk.Frame(parent, bg=ring, padx=1, pady=1)
    btn = tk.Button(
        outer,
        text=text,
        command=command,
        font=("Helvetica Neue", 12, "bold"),
        bg=face,
        fg=fg,
        activebackground=active_face,
        activeforeground=active_fg,
        relief="flat",
        cursor="hand2",
        padx=20,
        pady=12,
        bd=0,
        highlightthickness=0,
    )
    btn.pack(fill="both", expand=True)
    if pack_kw:
        outer.pack(**pack_kw)
    btn._auty_outer = outer  # noqa: SLF001 — keep ref for layout
    return btn


def make_card(parent, *, padx=2, pady=2, fill=None, expand=False):
    """Bordered outer + inner card frame."""
    outer = tk.Frame(parent, bg=THEME["border"], padx=padx, pady=pady)
    inner = tk.Frame(outer, bg=THEME["bg_card"])
    inner.pack(fill="both", expand=True)
    pack_kw = {}
    if fill:
        pack_kw["fill"] = fill
    if expand:
        pack_kw["expand"] = True
    if pack_kw:
        outer.pack(**pack_kw)
    return outer, inner


def make_sidebar_toggle(parent, text, command):
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=("Helvetica Neue", 14, "bold"),
        bg=THEME["bg_panel"],
        fg=THEME["text_muted"],
        activebackground=THEME["bg_card"],
        activeforeground=THEME["accent"],
        relief="flat",
        cursor="hand2",
        width=2,
        padx=4,
        pady=8,
        bd=0,
        highlightthickness=0,
    )


class SnapshotSlot:
    """Fixed-size enrollment snapshot with uniform cover-fit display."""

    def __init__(self, parent, width: int, height: int, *, on_click=None):
        self.width = width
        self.height = height
        self._photo = None
        self._on_click = on_click

        self.outer = tk.Frame(parent, bg=THEME["border"], padx=1, pady=1)
        self.frame = tk.Frame(self.outer, bg=THEME["bg_inset"], width=width, height=height)
        self.frame.pack()
        self.frame.pack_propagate(False)

        self.canvas = tk.Canvas(
            self.frame,
            width=width,
            height=height,
            bg=THEME["bg_inset"],
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()
        self.placeholder_id = self.canvas.create_text(
            width // 2,
            height // 2,
            text="Waiting for face…",
            fill=THEME["text_muted"],
            font=FONT_CAPTION,
            width=width - 24,
        )
        self.image_id = None
        if on_click:
            self.canvas.bind("<Button-1>", lambda e: on_click())
            self.canvas.config(cursor="hand2")

    def pack(self, **kw):
        self.outer.pack(**kw)

    def set_image(self, photo: ImageTk.PhotoImage):
        """Display a PhotoImage; keep a reference on this slot."""
        self._photo = photo
        if self.image_id is not None:
            self.canvas.delete(self.image_id)
        self.canvas.delete(self.placeholder_id)
        self.placeholder_id = None
        self.image_id = self.canvas.create_image(
            self.width // 2,
            self.height // 2,
            image=photo,
            anchor="center",
        )

    def clear(self, placeholder: str = "Waiting for face…"):
        self._photo = None
        if self.image_id is not None:
            self.canvas.delete(self.image_id)
            self.image_id = None
        if self.placeholder_id is not None:
            self.canvas.delete(self.placeholder_id)
        self.placeholder_id = self.canvas.create_text(
            self.width // 2,
            self.height // 2,
            text=placeholder,
            fill=THEME["text_muted"],
            font=FONT_CAPTION,
            width=self.width - 24,
        )
        self.canvas.config(cursor="arrow")

    @property
    def photo(self):
        return self._photo


def style_notebook(notebook: ttk.Notebook):
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Auty.TNotebook",
        background=THEME["bg_panel"],
        borderwidth=0,
        tabmargins=[2, 4, 2, 0],
    )
    style.configure(
        "Auty.TNotebook.Tab",
        background=THEME["bg_card"],
        foreground=THEME["text_muted"],
        padding=[14, 8],
        font=FONT_SECTION,
    )
    style.map(
        "Auty.TNotebook.Tab",
        background=[("selected", THEME["bg_panel"])],
        foreground=[("selected", THEME["accent"])],
    )
    notebook.configure(style="Auty.TNotebook")
