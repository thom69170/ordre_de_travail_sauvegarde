"""Petits utilitaires partagés par les onglets de l'interface."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Palette alignée sur le thème sv-ttk (Fluent / Windows 11) appliqué dans main.py.
BG = "#fafafa"
ACCENT = "#005fb8"
ACCENT_HOVER = "#2f60d8"
SUCCESS = "#0f7b0f"
WARN_BG = "#fdf6e3"
WARN_FG = "#8a5300"
ERROR_FG = "#c42b1c"
CARD_BG = "#ffffff"
BORDER = "#e5e5e5"
TEXT_MUTED = "#636363"


def parse_decimal(text: str) -> float:
    """Convertit une saisie utilisateur ('7,47' ou '7.47' ou '') en float."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return 0.0
    return round(float(text), 2)


def format_decimal(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


class LabeledEntry(ttk.Frame):
    """Un champ 'Label + Entry' empilé verticalement, avec accès pratique à la valeur."""

    def __init__(self, parent, label: str, width: int = 10, **kwargs):
        super().__init__(parent, **kwargs)
        ttk.Label(self, text=label, font=("Segoe UI", 8)).pack(anchor="w")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(fill="x")

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def get_decimal(self) -> float:
        return parse_decimal(self.var.get())

    def set_decimal(self, value: float) -> None:
        self.var.set(format_decimal(value))


class ScrollableFrame(ttk.Frame):
    """Un conteneur avec ascenseur vertical, pour les formulaires plus grands que l'écran."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, background=BG)
        vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfig(window_id, width=e.width)
        )
        self.canvas.configure(yscrollcommand=vscroll.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

    def scroll_to_top(self) -> None:
        """À appeler après avoir remplacé le contenu (ex: changement de filtre) : sans ça,
        le canvas garde son ancienne région/position de défilement, ce qui peut laisser le
        nouveau contenu (plus court) coincé tout en bas d'un grand espace vide."""
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0)


def show_warnings(parent, warnings: list[str]) -> ttk.Frame | None:
    if not warnings:
        return None
    frame = tk.Frame(parent, bg=WARN_BG, padx=10, pady=8)
    for w in warnings:
        tk.Label(frame, text=f"⚠ {w}", bg=WARN_BG, fg=WARN_FG, anchor="w",
                 wraplength=520, justify="left").pack(fill="x")
    return frame
