"""Fenêtre principale : assemble les onglets Importer / Historique / Statistiques."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.history_tab import HistoryTab
from app.ui.import_tab import ImportTab
from app.ui.stats_tab import StatsTab

APP_TITLE = "Ordres de travail"


class MainWindow(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        self.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.import_tab = ImportTab(self.notebook, self)
        self.history_tab = HistoryTab(self.notebook, self)
        self.stats_tab = StatsTab(self.notebook, self)

        self.notebook.add(self.import_tab, text="Importer")
        self.notebook.add(self.history_tab, text="Historique")
        self.notebook.add(self.stats_tab, text="Statistiques")

        self._tab_ids = {"import": self.import_tab, "history": self.history_tab, "stats": self.stats_tab}

    def select_tab(self, name: str):
        widget = self._tab_ids.get(name)
        if widget is not None:
            self.notebook.select(widget)

    def refresh_other_tabs(self, source: str):
        if source != "history":
            self.history_tab.refresh()
        if source != "stats":
            self.stats_tab.refresh()
