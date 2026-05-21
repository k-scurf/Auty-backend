"""Main window layout — feed-first, collapsible dark-glass sidebar."""

from __future__ import annotations

from dataclasses import dataclass, field
import tkinter as tk
from tkinter import ttk

from ui.activity_log import ActivityLogPanel
from ui.theme import (
    COLLAPSE_RAIL_WIDTH,
    SIDEBAR_WIDTH,
    SNAPSHOT_H,
    SNAPSHOT_W,
    THEME,
    SnapshotSlot,
    make_button,
    make_card,
    make_entry,
    make_label,
    make_sidebar_toggle,
    style_notebook,
)


@dataclass
class ShellContext:
    root: tk.Tk
    body: tk.Frame
    feed_container: tk.Frame
    feed_card: tk.Frame
    camera_label: tk.Label
    right_sidebar: tk.Frame
    collapse_rail: tk.Frame
    profile_tab: tk.Frame
    activity_log: ActivityLogPanel
    snapshot: SnapshotSlot
    enroll_section_label: tk.Label
    enroll_hint_label: tk.Label
    preview_hint: tk.Label
    name_entry: tk.Entry
    age_entry: tk.Entry
    status_entry: tk.Entry
    save_btn: tk.Button
    skip_btn: tk.Button
    display_w: int = 0
    display_h: int = 0
    _sidebar_collapsed: bool = field(default=False, repr=False)

    def set_display_size(self, w: int, h: int):
        self.display_w = max(0, w)
        self.display_h = max(0, h)


def build_shell(
    root: tk.Tk,
    *,
    on_snapshot_click=None,
) -> ShellContext:
    root.title("AUTY")
    root.geometry("1440x860")
    root.minsize(1100, 680)
    root.configure(bg=THEME["bg_root"])

    header = tk.Frame(root, bg=THEME["header_bg"], height=52)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)

    header_inner = tk.Frame(header, bg=THEME["header_bg"])
    header_inner.pack(fill="both", expand=True, padx=20, pady=10)

    title_block = tk.Frame(header_inner, bg=THEME["header_bg"])
    title_block.pack(side="left")
    make_label(title_block, "AUTY", style="header_title", anchor="w")
    make_label(
        title_block,
        "Face recognition",
        style="header_sub",
        anchor="w",
        pady=(0, 0),
    )

    live_pill = tk.Frame(
        header_inner,
        bg=THEME["bg_card"],
        padx=10,
        pady=4,
        highlightthickness=1,
        highlightbackground=THEME["border"],
    )
    live_pill.pack(side="right")
    tk.Label(
        live_pill,
        text="\u25cf",
        font=("Helvetica Neue", 10),
        fg=THEME["success"],
        bg=THEME["bg_card"],
    ).pack(side="left")
    make_label(live_pill, " LIVE", style="live", bg=THEME["bg_card"]).pack(side="left")

    tk.Frame(root, bg=THEME["border"], height=1).pack(fill="x")

    body = tk.Frame(root, bg=THEME["bg_root"])
    body.pack(fill="both", expand=True)

    ctx_holder: dict = {}

    def toggle_sidebar():
        ctx = ctx_holder["ctx"]
        ctx._sidebar_collapsed = not ctx._sidebar_collapsed
        if ctx._sidebar_collapsed:
            ctx.right_sidebar.pack_forget()
            ctx.collapse_rail.pack(side="right", fill="y")
            ctx.toggle_btn.config(text="\u203a")
        else:
            ctx.collapse_rail.pack_forget()
            ctx.right_sidebar.pack(
                side="right", fill="y", padx=(0, 12), pady=12
            )
            ctx.toggle_btn.config(text="\u2039")
        _update_display_size(ctx)

    collapse_rail = tk.Frame(body, bg=THEME["bg_panel"], width=COLLAPSE_RAIL_WIDTH)
    collapse_rail.pack_propagate(False)
    make_sidebar_toggle(collapse_rail, "\u203a", toggle_sidebar).pack(expand=True)

    right_sidebar = tk.Frame(
        body,
        bg=THEME["bg_panel"],
        width=SIDEBAR_WIDTH,
        highlightthickness=1,
        highlightbackground=THEME["border_soft"],
    )
    right_sidebar.pack(side="right", fill="y", padx=(0, 12), pady=12)
    right_sidebar.pack_propagate(False)

    toggle_btn = make_sidebar_toggle(right_sidebar, "\u2039", toggle_sidebar)
    toggle_btn.place(relx=0.0, rely=0.5, anchor="w", x=0)

    sidebar_inner = tk.Frame(right_sidebar, bg=THEME["bg_panel"])
    sidebar_inner.pack(fill="both", expand=True, padx=(16, 12), pady=12)

    notebook = ttk.Notebook(sidebar_inner)
    style_notebook(notebook)
    notebook.pack(fill="both", expand=True)

    profile_tab = tk.Frame(notebook, bg=THEME["bg_panel"])
    log_tab = tk.Frame(notebook, bg=THEME["bg_panel"])
    notebook.add(profile_tab, text="Profile")
    notebook.add(log_tab, text="Log")

    enroll_section_label = make_label(
        profile_tab,
        "NEW FRIEND",
        style="section",
        anchor="w",
        pady=(8, 4),
    )
    enroll_hint_label = make_label(
        profile_tab,
        "Turn slowly left, right, and up while we capture poses.",
        style="caption",
        anchor="w",
        pady=(0, 10),
    )

    snapshot = SnapshotSlot(
        profile_tab,
        SNAPSHOT_W,
        SNAPSHOT_H,
        on_click=on_snapshot_click,
    )
    snapshot.pack(anchor="center", pady=(0, 8))

    preview_hint = make_label(
        profile_tab,
        "Click snapshot to enlarge",
        style="caption",
        anchor="center",
    )
    preview_hint.pack_forget()

    make_label(profile_tab, "NAME", style="section", anchor="w", pady=(8, 4))
    name_entry = make_entry(profile_tab, fill="x", pady=(0, 8))

    make_label(profile_tab, "AGE", style="section", anchor="w", pady=(0, 4))
    age_entry = make_entry(profile_tab, fill="x", pady=(0, 8))

    make_label(profile_tab, "STATUS", style="section", anchor="w", pady=(0, 4))
    status_entry = make_entry(profile_tab, fill="x", pady=(0, 12))

    btn_row = tk.Frame(profile_tab, bg=THEME["bg_panel"])
    btn_row.pack(fill="x", pady=(0, 8))
    save_btn = make_button(
        btn_row, "Save profile", lambda: None, side="left", expand=True, fill="x", padx=(0, 6)
    )
    skip_btn = make_button(
        btn_row,
        "Not now",
        lambda: None,
        secondary=True,
        side="left",
        expand=True,
        fill="x",
        padx=(6, 0),
    )

    activity_log = ActivityLogPanel(log_tab)
    activity_log.pack(fill="both", expand=True, padx=4, pady=8)

    feed_container = tk.Frame(body, bg=THEME["bg_root"])
    feed_container.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)

    _, feed_card = make_card(feed_container, padx=1, pady=1, fill="both", expand=True)
    camera_label = tk.Label(feed_card, bg="#000000", bd=0)
    camera_label.place(relx=0.5, rely=0.5, anchor="center")

    ctx = ShellContext(
        root=root,
        body=body,
        feed_container=feed_container,
        feed_card=feed_card,
        camera_label=camera_label,
        right_sidebar=right_sidebar,
        collapse_rail=collapse_rail,
        profile_tab=profile_tab,
        activity_log=activity_log,
        snapshot=snapshot,
        enroll_section_label=enroll_section_label,
        enroll_hint_label=enroll_hint_label,
        preview_hint=preview_hint,
        name_entry=name_entry,
        age_entry=age_entry,
        status_entry=status_entry,
        save_btn=save_btn,
        skip_btn=skip_btn,
    )
    ctx_holder["ctx"] = ctx

    def _on_feed_configure(event):
        if event.widget is feed_card:
            _update_display_size(ctx)

    feed_card.bind("<Configure>", _on_feed_configure)
    collapse_rail.pack_forget()

    return ctx


def _update_display_size(ctx: ShellContext):
    pad = 8
    w = max(64, ctx.feed_card.winfo_width() - pad * 2)
    h = max(64, ctx.feed_card.winfo_height() - pad * 2)
    aspect = 16 / 9
    if w / h > aspect:
        dh = h
        dw = int(h * aspect)
    else:
        dw = w
        dh = int(w / aspect)
    ctx.set_display_size(dw, dh)
