"""Fenêtre principale : assemble les onglets Importer / Historique / Statistiques / Paramètres."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.history_tab import HistoryTab
from app.ui.import_tab import ImportTab
from app.ui.settings_tab import SettingsTab
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
        self.settings_tab = SettingsTab(self.notebook, self)

        self.notebook.add(self.import_tab, text="Importer")
        self.notebook.add(self.history_tab, text="Historique")
        self.notebook.add(self.stats_tab, text="Statistiques")
        self.notebook.add(self.settings_tab, text="Paramètres")

        self._tab_ids = {
            "import": self.import_tab, "history": self.history_tab,
            "stats": self.stats_tab, "settings": self.settings_tab,
        }

    def select_tab(self, name: str):
        widget = self._tab_ids.get(name)
        if widget is not None:
            self.notebook.select(widget)

    def mark_update_available(self) -> None:
        self.notebook.tab(self.settings_tab, text="Paramètres 🔵 MàJ")

    def refresh_other_tabs(self, source: str):
        if source != "history":
            self.history_tab.refresh()
        if source != "stats":
            self.stats_tab.refresh()
        if source != "import":
            self.import_tab._maybe_show_ocr_banner()
