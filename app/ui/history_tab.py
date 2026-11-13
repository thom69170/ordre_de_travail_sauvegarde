"""Onglet 'Historique' : liste des ordres de travail enregistrés (tableau triable), détail du jour
sélectionné, modification, suppression et export."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app import db, storage
from app.models import split_trajet
from app.stats import FRENCH_MONTHS, SHORT_WEEKDAYS, format_km, hours_to_hm, long_date
from app.ui.common import BG, TEXT_MUTED, WARN_BG, WARN_FG

ALL_MONTHS = "Tous les mois"
ZEBRA_BG = "#f1f1f1"
DETAIL_WIDTH = 350


def _parse(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


def _display_date(iso: str) -> str:
    d = _parse(iso)
    return d.strftime("%d/%m/%Y") if d else iso


def _hm_or_blank(value: float) -> str:
    """Les Feuilles de Route n'ont ni TPS ni TAD : une case vide plutôt qu'un « 0h00 » trompeur."""
    return hours_to_hm(value) if value else ""


def _trajets_summary(trajets: list[str]) -> str:
    """Résumé qui tient dans une colonne : nombre de trajets et numéros de ligne. La liste
    complète est dans le panneau de détail."""
    if not trajets:
        return ""
    lignes: list[str] = []
    for trajet in trajets:
        ligne = split_trajet(trajet)[0]
        if ligne and ligne not in lignes:
            lignes.append(ligne)
    text = f"{len(trajets)} trajet{'s' if len(trajets) > 1 else ''}"
    if lignes:
        text += f" · ligne{'s' if len(lignes) > 1 else ''} {', '.join(lignes)}"
    return text


class HistoryTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._orders = []
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

        # Résumé de la liste affichée, en haut à droite (il ne tenait pas à côté des boutons du bas
        # sur une petite fenêtre).
        self.summary_label = ttk.Label(top, text="", font=("Segoe UI", 9, "bold"), anchor="e")
        self.summary_label.pack(side="right")

        # Empaquetée avant le tableau (avec side="bottom") pour garder cette barre toujours
        # visible, même quand la liste ne tient pas dans la fenêtre (petit écran, ou mise à
        # l'échelle Windows élevée) : sinon le tableau (fill="both", expand=True) prend toute la
        # place disponible en premier et repousse ces boutons hors de la fenêtre.
        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Modifier", command=self.edit_selected).pack(side="left")
        ttk.Button(bottom, text="Ouvrir le fichier source", command=self.open_selected_file).pack(side="left", padx=8)
        ttk.Button(bottom, text="Supprimer", command=self.delete_selected).pack(side="left")
        ttk.Button(
            bottom, text="Exporter la liste (Excel)...", command=self.export_csv
        ).pack(side="left", padx=8)

        # Tableau à gauche, détail du jour sélectionné à droite.
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        body.bind("<Configure>", self._on_body_resize)

        self.detail = ttk.LabelFrame(body, text="Détail du jour", padding=12, width=DETAIL_WIDTH)
        self.detail.pack(side="right", fill="y", padx=(10, 0))
        self.detail.pack_propagate(False)
        self._build_detail()

        table = ttk.Frame(body)
        table.pack(side="left", fill="both", expand=True)
        self.columns = (
            "date", "conducteur", "tte", "ampli", "tps", "km", "repas", "derniere_minute", "trajets",
        )
        self.tree = ttk.Treeview(table, columns=self.columns, show="headings", selectmode="browse")
        self._headings = {
            "date": "Date", "conducteur": "Conducteur", "tps": "TPS",
            "tte": "Travail (TTE)", "ampli": "Amplitude", "km": "Km",
            "derniere_minute": "Dern. minute", "repas": "Repas",
            "trajets": "Trajets",
        }
        # Largeur souhaitée et largeur minimale de chaque colonne (voir _fit_columns).
        self._widths = {
            "date": (125, 108), "conducteur": (150, 90), "tte": (105, 84), "ampli": (90, 70),
            "tps": (70, 50), "km": (65, 46), "repas": (95, 62), "derniere_minute": (95, 80),
            "trajets": (240, 110),
        }
        for col in self.columns:
            self.tree.heading(col, text=self._headings[col], command=lambda c=col: self._sort_by(c))
            self.tree.column(
                col, width=self._widths[col][0], minwidth=40, stretch=False,
                anchor="w" if col in ("date", "conducteur", "trajets") else "center",
            )
        self._sort_column, self._sort_reverse = "date", True
        self.tree.tag_configure("odd", background=ZEBRA_BG)
        self.tree.tag_configure("last_minute", background=WARN_BG)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------------ détail du jour

    def _build_detail(self):
        d = self.detail
        self.detail_title = ttk.Label(d, text="", font=("Segoe UI Semibold", 12), wraplength=DETAIL_WIDTH - 30)
        self.detail_title.pack(anchor="w")
        self.detail_sub = ttk.Label(d, text="", foreground=TEXT_MUTED, font=("Segoe UI", 9),
                                    wraplength=DETAIL_WIDTH - 30)
        self.detail_sub.pack(anchor="w", pady=(0, 6))
        self.detail_flag = tk.Label(d, text="", bg=WARN_BG, fg=WARN_FG, anchor="w", padx=8, pady=4,
                                    font=("Segoe UI", 9))
        self.detail_grid = ttk.Frame(d)
        self.detail_grid.pack(fill="x", pady=(4, 8))
        self.detail_grid.columnconfigure(1, weight=1)
        self.detail_list_title = ttk.Label(d, text="", font=("Segoe UI Semibold", 9))
        self.detail_list_title.pack(anchor="w")
        text_frame = ttk.Frame(d)
        text_frame.pack(fill="both", expand=True, pady=(2, 0))
        self.detail_text = tk.Text(
            text_frame, wrap="word", height=6, relief="flat", borderwidth=0, background=BG,
            font=("Segoe UI", 9), spacing1=1, spacing3=3, cursor="arrow", highlightthickness=0,
        )
        self.detail_text.tag_configure("heading", font=("Segoe UI Semibold", 9), spacing1=10)
        self.detail_text.tag_configure("muted", foreground=TEXT_MUTED)
        text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=text_scroll.set, state="disabled")
        text_scroll.pack(side="right", fill="y")
        self.detail_text.pack(side="left", fill="both", expand=True)

    def _show_detail(self):
        selected = self._selected_id()
        wo = next((o for o in self._orders if o.id == selected), None)
        for child in self.detail_grid.winfo_children():
            child.destroy()
        self.detail_flag.pack_forget()
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if wo is None:
            self.detail_title.config(text="Aucun jour sélectionné")
            self.detail_sub.config(text="Clique sur une ligne du tableau pour voir son détail.")
            self.detail_list_title.config(text="")
            self.detail_text.configure(state="disabled")
            return

        d = _parse(wo.date)
        self.detail_title.config(text=long_date(d).capitalize() if d else wo.date)
        self.detail_sub.config(text=" · ".join(
            part for part in (wo.driver_name, f"matricule {wo.matricule}" if wo.matricule else "") if part
        ))
        if wo.last_minute_change:
            self.detail_flag.config(text="⚠ Changement de dernière minute")
            self.detail_flag.pack(fill="x", pady=(0, 4), before=self.detail_grid)

        meals = " + ".join(n for n, due in (("midi", wo.repas_midi), ("soir", wo.repas_soir)) if due)
        rows = [("Temps de travail (TTE)", hours_to_hm(wo.tte)), ("Amplitude", hours_to_hm(wo.ampli))]
        if wo.tps:
            rows.append(("TPS", hours_to_hm(wo.tps)))
        if wo.tad:
            rows.append(("TAD", hours_to_hm(wo.tad)))
        if wo.km_totaux:
            km = format_km(wo.km_totaux)
            if wo.km_hlp:
                km += f" (dont {format_km(wo.km_hlp)} HLP)"
            rows.append(("Kilomètres", km))
        if wo.indem_coup:
            rows.append(("Indemnité coupure", hours_to_hm(wo.indem_coup)))
        if wo.indem_ampl:
            rows.append(("Indemnité amplitude", hours_to_hm(wo.indem_ampl)))
        rows.append(("Repas dus", meals or "aucun"))
        for i, (label, value) in enumerate(rows):
            ttk.Label(self.detail_grid, text=label, foreground=TEXT_MUTED, font=("Segoe UI", 9)).grid(
                row=i, column=0, sticky="w", pady=1)
            ttk.Label(self.detail_grid, text=value, font=("Segoe UI Semibold", 9)).grid(
                row=i, column=1, sticky="e", pady=1)

        count = len(wo.trajets)
        self.detail_list_title.config(text=f"Trajets ({count})" if count else "Aucun trajet enregistré")
        for index, trajet in enumerate(wo.trajets, start=1):
            self.detail_text.insert("end", f"{index}. ", "muted")
            self.detail_text.insert("end", trajet + "\n")
        if wo.notes.strip():
            self.detail_text.insert("end", "Notes\n", "heading")
            self.detail_text.insert("end", wo.notes.strip() + "\n")
        self.detail_text.configure(state="disabled")

    # ------------------------------------------------------------------ tableau

    def _on_body_resize(self, event):
        # Petite fenêtre : panneau de détail un peu plus étroit, pour laisser la place au tableau.
        detail_width = 300 if event.width < 1000 else DETAIL_WIDTH
        if int(self.detail.cget("width")) != detail_width:
            self.detail.config(width=detail_width)
            self.detail_title.config(wraplength=detail_width - 30)
            self.detail_sub.config(wraplength=detail_width - 30)
        self._table_width = event.width - detail_width - 10 - 20  # marge + ascenseur
        self._fit_columns()

    def _fit_columns(self):
        """Répartit la largeur disponible entre les colonnes affichées : rien ne dépasse du cadre.
        La place en trop va aux Trajets ; s'il en manque, les colonnes de chiffres se resserrent
        d'abord (jusqu'à leur largeur minimale), les Trajets seulement en dernier."""
        available = getattr(self, "_table_width", 0)
        shown = list(self.tree["displaycolumns"])
        if available <= 0 or not shown or shown == ["#all"]:
            return
        widths = {c: self._widths[c][0] for c in shown}
        missing = sum(widths.values()) - available
        if missing <= 0:
            widths["trajets"] -= missing
        else:
            for group in ([c for c in shown if c != "trajets"], ["trajets"]):
                slack = {c: widths[c] - self._widths[c][1] for c in group}
                total = sum(slack.values())
                if missing <= 0 or total <= 0:
                    continue
                cut = min(missing, total)
                for c in group:
                    widths[c] -= round(cut * slack[c] / total)
                missing -= cut
        for c in shown:
            self.tree.column(c, width=max(40, widths[c]))

    def _sort_by(self, column: str):
        """Clic sur un en-tête : trie sur cette colonne ; un second clic inverse l'ordre."""
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            # Première fois : les plus récents / les plus grands d'abord, sauf pour le texte.
            self._sort_column, self._sort_reverse = column, column != "conducteur"
        self.refresh()

    def _sort_key(self, wo):
        return {
            "date": wo.date, "conducteur": wo.driver_name.lower(), "tps": wo.tps, "tte": wo.tte,
            "ampli": wo.ampli, "km": wo.km_totaux, "derniere_minute": int(bool(wo.last_minute_change)),
            "repas": int(bool(wo.repas_midi)) + int(bool(wo.repas_soir)), "trajets": len(wo.trajets),
        }[self._sort_column]

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

        previous_selection = self._selected_id()
        for row in self.tree.get_children():
            self.tree.delete(row)

        orders = db.list_work_orders(start_date, end_date)
        orders.sort(key=lambda wo: wo.date, reverse=True)  # à égalité : le plus récent d'abord
        orders.sort(key=self._sort_key, reverse=self._sort_reverse)
        self._orders = orders

        # La colonne Conducteur n'a d'intérêt que s'il y a plusieurs conducteurs dans la liste.
        several_drivers = len({wo.driver_name.strip().lower() for wo in orders if wo.driver_name.strip()}) > 1
        self.tree["displaycolumns"] = [c for c in self.columns if c != "conducteur" or several_drivers]
        self._fit_columns()
        for col in self.columns:
            arrow = (" ▼" if self._sort_reverse else " ▲") if col == self._sort_column else ""
            self.tree.heading(col, text=self._headings[col] + arrow)

        total_tte = 0.0
        for index, wo in enumerate(orders):
            d = _parse(wo.date)
            display_date = f"{SHORT_WEEKDAYS[d.weekday()]} {d:%d/%m/%Y}" if d else wo.date
            if wo.last_minute_change:
                tags = ("last_minute",)
            else:
                tags = ("odd",) if index % 2 else ()
            self.tree.insert("", "end", iid=str(wo.id), values=(
                display_date, wo.driver_name, hours_to_hm(wo.tte), hours_to_hm(wo.ampli),
                _hm_or_blank(wo.tps), f"{wo.km_totaux:.0f}" if wo.km_totaux else "",
                " + ".join(
                    name for name, due in (("midi", wo.repas_midi), ("soir", wo.repas_soir)) if due
                ),
                "Oui" if wo.last_minute_change else "",
                _trajets_summary(wo.trajets),
            ), tags=tags)
            total_tte += wo.tte

        # On garde le jour sélectionné s'il est toujours là, sinon le premier de la liste.
        ids = [str(wo.id) for wo in orders]
        if ids:
            keep = str(previous_selection) if str(previous_selection) in ids else ids[0]
            self.tree.selection_set(keep)
            self.tree.see(keep)
        self._show_detail()

        last_minute_count = sum(1 for wo in orders if wo.last_minute_change)
        summary_text = f"{len(orders)} jour{'s' if len(orders) != 1 else ''} · {hours_to_hm(total_tte)} de travail"
        if last_minute_count:
            summary_text += f" · {last_minute_count} dernière minute"
        meal_count = sum(int(wo.repas_midi) + int(wo.repas_soir) for wo in orders)
        if meal_count:
            summary_text += f" · {meal_count} repas"
        self.summary_label.config(text=summary_text)

    def export_csv(self):
        """Exporte les OT actuellement affichés (selon le filtre année/mois) dans un fichier
        CSV qui s'ouvre dans Excel."""
        if not self._orders:
            messagebox.showinfo("Export", "Aucun ordre de travail à exporter pour ce filtre.")
            return
        name = "ordres_de_travail"
        if self.year_var.get() != "Toutes":
            name += f"_{self.year_var.get()}"
            if self.month_var.get() != ALL_MONTHS:
                name += f"-{FRENCH_MONTHS.index(self.month_var.get()) + 1:02d}"
        path_str = filedialog.asksaveasfilename(
            title="Exporter les ordres de travail", defaultextension=".csv",
            initialfile=f"{name}.csv", filetypes=[("Fichier Excel / CSV", "*.csv")],
        )
        if not path_str:
            return
        from app import backup

        try:
            # L'export garde son ordre habituel (du plus récent au plus ancien), quel que soit le
            # tri affiché dans le tableau.
            ordered = sorted(self._orders, key=lambda wo: wo.date, reverse=True)
            backup.export_work_orders_csv(ordered, Path(path_str))
        except OSError as exc:
            messagebox.showerror(
                "Export impossible",
                f"Impossible d'écrire ce fichier (est-il ouvert dans Excel ?) :\n{exc}",
            )
            return
        messagebox.showinfo(
            "Export terminé", f"{len(self._orders)} ordre(s) de travail exporté(s) dans :\n{path_str}"
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
        if not messagebox.askyesno("Confirmer", f"Supprimer l'ordre de travail du {_display_date(wo.date)} ?"):
            return
        db.delete_work_order(work_order_id)
        if wo.source_filename:
            storage.delete_source_file(wo.source_filename)
        self.refresh()
        self.app.refresh_other_tabs("history")
