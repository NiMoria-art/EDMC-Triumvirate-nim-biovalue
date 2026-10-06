"""Shared black-and-orange styles for the value panels."""
from tkinter import ttk

BACKGROUND = "#111111"
PANEL = "#1d1d1d"
ACCENT = "#ff9b2f"
TEXT = "#f2f2f2"
MUTED = "#b7b7b7"


def configure_styles(widget):
    style = ttk.Style(widget)
    style.configure("Triumvirate.Card.TLabelframe", background=PANEL, foreground=TEXT)
    style.configure(
        "Triumvirate.Card.TLabelframe.Label",
        background=PANEL,
        foreground=ACCENT,
        font=("TkDefaultFont", 9, "bold"),
    )
    style.configure("Triumvirate.Card.TFrame", background=PANEL)
    style.configure("Triumvirate.Card.TLabel", background=PANEL, foreground=TEXT)
    style.configure(
        "Triumvirate.Accent.TLabel",
        background=PANEL,
        foreground=ACCENT,
        font=("TkDefaultFont", 10, "bold"),
    )
    style.configure("Triumvirate.Muted.TLabel", background=PANEL, foreground=MUTED)
    style.configure(
        "Triumvirate.Warning.TLabel",
        background=PANEL,
        foreground="#ff6b35",
        font=("TkDefaultFont", 10, "bold"),
    )
    style.configure("Triumvirate.Card.TCheckbutton", background=PANEL, foreground=TEXT)
    style.map(
        "Triumvirate.Card.TCheckbutton",
        background=[("active", PANEL)],
        foreground=[("active", ACCENT)],
    )
    style.configure(
        "Triumvirate.Treeview",
        background=BACKGROUND,
        fieldbackground=BACKGROUND,
        foreground=TEXT,
        rowheight=24,
    )
    style.configure(
        "Triumvirate.Treeview.Heading",
        background=PANEL,
        foreground=ACCENT,
        font=("TkDefaultFont", 9, "bold"),
    )
    style.map(
        "Triumvirate.Treeview",
        background=[("selected", "#6b3b12")],
        foreground=[("selected", TEXT)],
    )
    return style
