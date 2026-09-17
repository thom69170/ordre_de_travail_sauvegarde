"""Onglet 'Heures sup.' : suivi des heures supplémentaires relevées sur les feuilles de
prépaie (jamais recalculées par l'app - voir app/payslip_parser.py)."""
from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app import db, storage
from app.models import Payslip
from app.payslip_parser import extract_payslip
from app.ui.common import LabeledEntry, TEXT_MUTED, format_decimal

FILE_TYPES = [
    ("PDF", "*.pdf"),
    ("Tous les fichiers", "*.*"),
]


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _parse_date(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    for sep in ("/", "-", "."):
        parts = text.split(sep)
        if len(parts) == 3:
            try:
                d, m, y = (int(p) for p in parts)
                if y < 100:
                    y += 2000
                return date(y, m, d).isoformat()
            except ValueError:
                continue
    raise ValueError(f"Date non reconnue : {text!r}")


class PayslipTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_path: Path | None = None
        self.current_details_json: str = ""
        self.editing_id: int | None = None
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        self.choose_btn = ttk.Button(
            top, text="Importer une feuille de prépaie...", command=self.choose_file
        )
        self.choose_btn.pack(side="left")
        self.phone_btn = ttk.Button(
            top, text="Recevoir depuis le téléphone...", command=self._open_phone_upload_dialog
        )
        self.phone_btn.pack(side="left", padx=(8, 0))
        self.file_label = ttk.Label(top, text="Aucun fichier sélectionné", foreground=TEXT_MUTED)
        self.file_label.pack(side="left", padx=10)

        form = ttk.LabelFrame(self, text="Heures sup. relevées", padding=10)
        form.pack(fill="x", padx=12, pady=(0, 8))

        row1 = ttk.Frame(form)
        row1.pack(fill="x", pady=(0, 8))
        self.start_entry = LabeledEntry(row1, "Début période (JJ/MM/AAAA)", width=14)
        self.start_entry.pack(side="left", padx=(0, 10))
        self.end_entry = LabeledEntry(row1, "Fin période (JJ/MM/AAAA)", width=14)
        self.end_entry.pack(side="left", padx=(0, 20))
        self.back_btn = ttk.Button(row1, text="← Retour à la liste", command=self._back_to_list)
        self.reset_btn = ttk.Button(row1, text="Réinitialiser", command=self.reset_form)
        self.reset_btn.pack(side="left", padx=(0, 6))
        self.save_btn = ttk.Button(row1, text="Enregistrer", command=self.save)
        self.save_btn.pack(side="left")

        row2 = ttk.Frame(form)
        row2.pack(fill="x")
        self.hs25_entry = LabeledEntry(row2, "HS 25% (ce mois)", width=10)
        self.hs25_entry.set_decimal(0.0)
        self.hs25_entry.pack(side="left", padx=(0, 10))
        self.hs50_entry = LabeledEntry(row2, "HS 50% (ce mois)", width=10)
        self.hs50_entry.set_decimal(0.0)
        self.hs50_entry.pack(side="left", padx=(0, 20))
        self.cumul25_entry = LabeledEntry(row2, "Cumul annuel HS 25%", width=10)
        self.cumul25_entry.set_decimal(0.0)
        self.cumul25_entry.pack(side="left", padx=(0, 10))
        self.cumul50_entry = LabeledEntry(row2, "Cumul annuel HS 50%", width=10)
        self.cumul50_entry.set_decimal(0.0)
        self.cumul50_entry.pack(side="left", padx=(0, 20))
        self.details_btn = ttk.Button(
            row2, text="Voir tous les détails...", command=self._show_details_dialog
        )
        self.details_btn.pack(side="left")

        self.warnings_holder = ttk.Frame(self)
        self.warnings_holder.pack(fill="x", padx=12)

        columns = ("periode", "hs25", "hs50", "cumul25", "cumul50")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        headings = {
            "periode": "Période", "hs25": "HS 25%", "hs50": "HS 50%",
            "cumul25": "Cumul annuel 25%", "cumul50": "Cumul annuel 50%",
        }
        widths = {"periode": 220, "hs25": 90, "hs50": 90, "cumul25": 130, "cumul50": 130}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Modifier", command=self.edit_selected).pack(side="left")
        ttk.Button(
            bottom, text="Ouvrir le fichier source", command=self.open_selected_file
        ).pack(side="left", padx=8)
        ttk.Button(bottom, text="Supprimer", command=self.delete_selected).pack(side="left")

        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    # ------------------------------------------------------------- import

    def choose_file(self):
        path_str = filedialog.askopenfilename(
            title="Choisir une feuille de prépaie", filetypes=FILE_TYPES
        )
        if not path_str:
            return
        self._load_file(Path(path_str))

    def _open_phone_upload_dialog(self):
        from app.ui.phone_upload_dialog import PhoneUploadDialog

        PhoneUploadDialog(
            self.winfo_toplevel(),
            on_file_received=self._load_file,
            dialog_title="Recevoir une feuille de prépaie depuis le téléphone",
            waiting_text="En attente d'une feuille de prépaie...",
            received_noun="Fichier",
            page_title="Heures sup.",
            instruction="Choisis le PDF de ta feuille de prépaie, puis envoie-le au PC.",
            choose_label="Choisir un fichier PDF",
            accept=".pdf,application/pdf",
            capture=False,
            allowed_suffixes=frozenset({".pdf"}),
            default_suffix=".pdf",
        )

    def _load_file(self, path: Path):
        try:
            result = extract_payslip(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erreur", f"Impossible de lire ce fichier :\n{exc}")
            return

        self.reset_form(keep_file_dialog_open=True)
        self.current_path = path
        self.file_label.config(text=path.name)
        self.start_entry.set(_fmt_date(result.period_start))
        self.end_entry.set(_fmt_date(result.period_end))
        self.hs25_entry.set_decimal(result.hs_25)
        self.hs50_entry.set_decimal(result.hs_50)
        self.cumul25_entry.set_decimal(result.cumul_hs_25)
        self.cumul50_entry.set_decimal(result.cumul_hs_50)
        if result.recap or result.compteurs:
            self.current_details_json = json.dumps(
                {"recap": result.recap, "compteurs": result.compteurs}, ensure_ascii=False
            )

        for child in self.warnings_holder.winfo_children():
            child.destroy()
        if result.warnings:
            from app.ui.common import show_warnings
            frame = show_warnings(self.warnings_holder, result.warnings)
            if frame:
                frame.pack(fill="x", pady=6)

    def open_selected_file(self):
        payslip_id = self._selected_id()
        if payslip_id is None:
            return
        p = db.get_payslip(payslip_id)
        if not p or not p.source_filename:
            messagebox.showinfo("Aucun fichier", "Aucun fichier source associé à ce relevé.")
            return
        self._open_with_default_app(storage.resolve_payslip_path(p.source_filename))

    @staticmethod
    def _open_with_default_app(path: Path):
        try:
            if sys.platform == "win32":
                import os
                os.startfile(str(path))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{exc}")

    # ------------------------------------------------------------- actions

    def edit_selected(self):
        payslip_id = self._selected_id()
        if payslip_id is None:
            messagebox.showinfo("Sélection", "Sélectionne d'abord un relevé dans la liste.")
            return
        p = db.get_payslip(payslip_id)
        if p is None:
            return
        self.reset_form()
        self.editing_id = p.id
        self.current_path = None
        self.file_label.config(
            text=f"(fichier existant : {p.source_filename or 'aucun'})"
        )
        self.start_entry.set(_fmt_date(p.period_start))
        self.end_entry.set(_fmt_date(p.period_end))
        self.hs25_entry.set_decimal(p.hs_25)
        self.hs50_entry.set_decimal(p.hs_50)
        self.cumul25_entry.set_decimal(p.cumul_hs_25)
        self.cumul50_entry.set_decimal(p.cumul_hs_50)
        self.current_details_json = p.details_json
        self.save_btn.config(text="Mettre à jour")
        self.back_btn.pack(side="left", padx=(0, 6), before=self.reset_btn)

    def _back_to_list(self):
        self.reset_form()

    def _selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def delete_selected(self):
        payslip_id = self._selected_id()
        if payslip_id is None:
            return
        p = db.get_payslip(payslip_id)
        if p is None:
            return
        if not messagebox.askyesno(
            "Confirmer",
            f"Supprimer le relevé du {_fmt_date(p.period_start)} au {_fmt_date(p.period_end)} ?",
        ):
            return
        db.delete_payslip(payslip_id)
        if p.source_filename:
            storage.delete_payslip_file(p.source_filename)
        self.refresh()

    def reset_form(self, keep_file_dialog_open: bool = False):
        self.editing_id = None
        self.current_path = None
        self.current_details_json = ""
        if not keep_file_dialog_open:
            self.file_label.config(text="Aucun fichier sélectionné")
        self.start_entry.set("")
        self.end_entry.set("")
        self.hs25_entry.set_decimal(0.0)
        self.hs50_entry.set_decimal(0.0)
        self.cumul25_entry.set_decimal(0.0)
        self.cumul50_entry.set_decimal(0.0)
        for child in self.warnings_holder.winfo_children():
            child.destroy()
        self.save_btn.config(text="Enregistrer")
        self.back_btn.pack_forget()

    def save(self):
        try:
            start_iso = _parse_date(self.start_entry.get())
            end_iso = _parse_date(self.end_entry.get())
        except ValueError as exc:
            messagebox.showerror("Date invalide", str(exc))
            return
        if not start_iso:
            messagebox.showerror("Date invalide", "La date de début de période est obligatoire.")
            return

        target_id = self.editing_id
        if target_id is None:
            existing = db.get_payslip_by_period(start_iso)
            if existing is not None:
                if not messagebox.askyesno(
                    "Relevé existant",
                    f"Un relevé existe déjà pour la période commençant le "
                    f"{_fmt_date(start_iso)}. Le remplacer ?",
                ):
                    return
                target_id = existing.id

        p = Payslip(
            id=target_id,
            period_start=start_iso,
            period_end=end_iso,
            hs_25=self.hs25_entry.get_decimal(),
            hs_50=self.hs50_entry.get_decimal(),
            cumul_hs_25=self.cumul25_entry.get_decimal(),
            cumul_hs_50=self.cumul50_entry.get_decimal(),
            details_json=self.current_details_json,
        )

        if self.current_path is not None:
            p.source_filename = storage.store_payslip_file(self.current_path, start_iso)
        elif target_id is not None:
            previous = db.get_payslip(target_id)
            if previous:
                p.source_filename = previous.source_filename

        if target_id is None:
            db.insert_payslip(p)
        else:
            db.update_payslip(p)

        messagebox.showinfo("Enregistré", f"Relevé du {_fmt_date(start_iso)} enregistré.")
        self.reset_form()
        self.refresh()

    def _show_details_dialog(self):
        if not self.current_details_json:
            messagebox.showinfo(
                "Aucun détail",
                "Aucun détail disponible pour ce relevé (importe/sélectionne d'abord une "
                "feuille de prépaie).",
            )
            return
        try:
            details = json.loads(self.current_details_json)
        except (json.JSONDecodeError, TypeError):
            messagebox.showerror("Erreur", "Détails illisibles pour ce relevé.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Tous les détails de la feuille de prépaie")
        dialog.transient(self.winfo_toplevel())

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(frame, columns=("label", "value"), show="tree headings", height=24)
        tree.heading("label", text="Libellé")
        tree.heading("value", text="Valeur")
        tree.column("#0", width=0, stretch=False)
        tree.column("label", width=260, anchor="w")
        tree.column("value", width=100, anchor="w")
        tree.tag_configure("section", font=("Segoe UI", 9, "bold"))
        tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll.pack(side="left", fill="y")
        tree.config(yscrollcommand=scroll.set)

        recap = details.get("recap") or {}
        compteurs = details.get("compteurs") or {}
        if recap:
            tree.insert("", "end", values=("Récapitulatif du mois", ""), tags=("section",))
            for label, value in recap.items():
                tree.insert("", "end", values=(label, format_decimal(value)))
        if compteurs:
            tree.insert("", "end", values=("Compteurs (cumuls annuels)", ""), tags=("section",))
            for label, value in compteurs.items():
                tree.insert("", "end", values=(label, format_decimal(value)))

        ttk.Button(dialog, text="Fermer", command=dialog.destroy).pack(pady=(0, 12))

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for p in db.list_payslips():
            periode = f"{_fmt_date(p.period_start)} — {_fmt_date(p.period_end)}"
            self.tree.insert("", "end", iid=str(p.id), values=(
                periode, format_decimal(p.hs_25), format_decimal(p.hs_50),
                format_decimal(p.cumul_hs_25), format_decimal(p.cumul_hs_50),
            ))
