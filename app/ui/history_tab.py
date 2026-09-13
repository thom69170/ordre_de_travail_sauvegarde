"""Onglet 'Historique' : liste, modification et suppression des ordres de travail enregistrés."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from app import db, storage
from app.stats import FRENCH_MONTHS, hours_to_hm

ALL_MONTHS = "Tous les mois"


class HistoryTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Année :").pack(side="left")
        self.year_var = tk.StringVar(value="Toutes")
        self.year_combo = ttk.Combobox(top, textvariable=self.year_var, width=8, state="readonly")
        self.year_combo.pack(side="left", padx=(4, 12))
        self.year_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Label(top, text="Mois :").pack(side="left")
        self.month_var = tk.StringVar(value=ALL_MONTHS)
        self.month_combo = ttk.Combobox(
            top, textvariable=self.month_var, width=14, state="readonly",
            values=[ALL_MONTHS] + FRENCH_MONTHS,
        )
        self.month_combo.pack(side="left", padx=4)
        self.month_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Button(top, text="Actualiser", command=self.refresh).pack(side="left", padx=12)

        columns = ("date", "conducteur", "tps", "tte", "ampli", "trajets")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        headings = {
            "date": "Date", "conducteur": "Conducteur", "tps": "TPS",
            "tte": "TTE (travail)", "ampli": "Amplitude", "trajets": "Trajets",
        }
        widths = {"date": 110, "conducteur": 200, "tps": 90, "tte": 110, "ampli": 100, "trajets": 300}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Modifier", command=self.edit_selected).pack(side="left")
        ttk.Button(bottom, text="Ouvrir le fichier source", command=self.open_selected_file).pack(side="left", padx=8)
        ttk.Button(bottom, text="Supprimer", command=self.delete_selected).pack(side="left")

        self.summary_label = ttk.Label(bottom, text="", font=("Segoe UI", 9, "bold"))
        self.summary_label.pack(side="right")

    def refresh(self):
        all_orders = db.list_work_orders()
        years = sorted({wo.date[:4] for wo in all_orders if wo.date}, reverse=True)
        self.year_combo["values"] = ["Toutes"] + years
        if self.year_var.get() not in self.year_combo["values"]:
            self.year_var.set("Toutes")

        start_date = end_date = None
        if self.year_var.get() != "Toutes":
            year = self.year_var.get()
            if self.month_var.get() != ALL_MONTHS:
                month = FRENCH_MONTHS.index(self.month_var.get()) + 1
                start_date = f"{year}-{month:02d}-01"
                end_date = f"{year}-{month:02d}-31"
            else:
                start_date = f"{year}-01-01"
                end_date = f"{year}-12-31"

        for row in self.tree.get_children():
            self.tree.delete(row)

        orders = db.list_work_orders(start_date, end_date)
        total_tte = 0.0
        for wo in orders:
            try:
                display_date = date.fromisoformat(wo.date).strftime("%d/%m/%Y")
            except ValueError:
                display_date = wo.date
            self.tree.insert("", "end", iid=str(wo.id), values=(
                display_date, wo.driver_name, hours_to_hm(wo.tps), hours_to_hm(wo.tte),
                hours_to_hm(wo.ampli), ", ".join(sorted(set(wo.trajets))),
            ))
            total_tte += wo.tte

        self.summary_label.config(
            text=f"{len(orders)} jour(s) · total temps de travail : {hours_to_hm(total_tte)}"
        )

    def _selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def edit_selected(self):
        work_order_id = self._selected_id()
        if work_order_id is None:
            messagebox.showinfo("Sélection", "Sélectionne d'abord un ordre de travail dans la liste.")
            return
        wo = db.get_work_order(work_order_id)
        if wo is None:
            return
        self.app.import_tab.load_for_edit(wo)
        self.app.select_tab("import")

    def open_selected_file(self):
        work_order_id = self._selected_id()
        if work_order_id is None:
            return
        wo = db.get_work_order(work_order_id)
        if not wo or not wo.source_filename:
            messagebox.showinfo("Aucun fichier", "Aucun fichier source associé à cet ordre de travail.")
            return
        from app.ui.import_tab import ImportTab
        ImportTab._open_with_default_app(storage.resolve_source_path(wo.source_filename))

    def delete_selected(self):
        work_order_id = self._selected_id()
        if work_order_id is None:
            return
        wo = db.get_work_order(work_order_id)
        if wo is None:
            return
        try:
            display_date = date.fromisoformat(wo.date).strftime("%d/%m/%Y")
        except ValueError:
            display_date = wo.date
        if not messagebox.askyesno("Confirmer", f"Supprimer l'ordre de travail du {display_date} ?"):
            return
        db.delete_work_order(work_order_id)
        if wo.source_filename:
            storage.delete_source_file(wo.source_filename)
        self.refresh()
        self.app.refresh_other_tabs("history")
