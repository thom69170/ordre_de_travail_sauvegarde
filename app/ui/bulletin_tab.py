"""Onglet 'Bulletins de paie' : import des bulletins de paie (PDF), chiffres clés par mois, détail
ligne par ligne, et comparaison avec la feuille de prépaie du mois précédent.

Lecture locale du texte du PDF (voir app/bulletin_parser.py) : ni OCR ni IA, rien n'est envoyé
sur internet, et aucun montant n'est calculé par l'app - seulement recopié du document."""
from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from dataclasses import asdict
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app import db, storage
from app.bulletin_parser import (
    SECTION_AUTRES,
    SECTION_BRUT,
    SECTION_COTISATIONS,
    BulletinError,
    extract_bulletin,
    is_bulletin,
)
from app.models import Bulletin
from app.stats import FRENCH_MONTHS
from app.ui.common import TEXT_MUTED, WARN_BG, WARN_FG, show_warnings

FILE_TYPES = [
    ("Bulletins de paie (PDF ou ZIP)", "*.pdf *.zip"),
    ("Tous les fichiers", "*.*"),
]

SECTION_TITLES = {
    SECTION_BRUT: ("Éléments de revenu brut", "Quantité", "Valeur unitaire", "Montant"),
    SECTION_COTISATIONS: ("Cotisations et contributions sociales", "Base", "Taux", "Part salarié"),
    SECTION_AUTRES: ("Autres éléments de paie", "Quantité", "Valeur unitaire", "Montant"),
}


def _fmt_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or ""


def _month_label(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso or ""
    return f"{FRENCH_MONTHS[d.month - 1]} {d.year}"


def _of_month(iso: str) -> str:
    """"d'août 2026" / "de juillet 2026", pour l'intérieur d'une phrase."""
    label = _month_label(iso).lower()
    return ("d'" if label[:1] in "aeiouéèêô" else "de ") + label


def _money(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


class BulletinTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._phone_dialog = None
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Button(
            top, text="Importer un bulletin de paie...", command=self.choose_files
        ).pack(side="left")
        ttk.Button(
            top, text="Recevoir depuis le téléphone...", command=self._open_phone_upload_dialog
        ).pack(side="left", padx=(8, 0))
        self.status_label = ttk.Label(top, text="", foreground=TEXT_MUTED)
        self.status_label.pack(side="left", padx=10)

        ttk.Label(
            self,
            text="Les chiffres sont recopiés tels quels du bulletin (lecture locale du PDF, sans "
                 "IA). Plusieurs bulletins peuvent être sélectionnés d'un coup, ou reçus dans un "
                 "fichier .zip (qui peut aussi contenir des feuilles de prépaie).",
            foreground=TEXT_MUTED, padding=(12, 0, 12, 6), wraplength=1000, justify="left",
        ).pack(anchor="w")

        self.warnings_holder = ttk.Frame(self)
        self.warnings_holder.pack(fill="x", padx=12)

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Voir le détail...", command=self.show_details).pack(side="left")
        ttk.Button(
            bottom, text="Comparer à la feuille de prépaie...", command=self.compare_selected
        ).pack(side="left", padx=8)
        ttk.Button(
            bottom, text="Ouvrir le fichier", command=self.open_selected_file
        ).pack(side="left")
        ttk.Button(bottom, text="Supprimer", command=self.delete_selected).pack(side="left", padx=8)
        self.summary_label = ttk.Label(bottom, text="", font=("Segoe UI", 9, "bold"))
        self.summary_label.pack(side="right")

        columns = ("mois", "paye_le", "net", "brut", "net_fiscal", "heures")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        for col, text, width in (
            ("mois", "Mois", 170), ("paye_le", "Payé le", 110), ("net", "Net payé (€)", 130),
            ("brut", "Salaire brut (€)", 140), ("net_fiscal", "Net fiscal (€)", 130),
            ("heures", "Heures déclarées", 130),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.bind("<Double-1>", lambda e: self.show_details())
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    # ------------------------------------------------------------- import

    def choose_files(self):
        paths = filedialog.askopenfilenames(
            title="Choisir un ou plusieurs bulletins de paie (PDF ou fichier .zip)",
            filetypes=FILE_TYPES,
        )
        if paths:
            self.app.import_documents([Path(p) for p in paths], "bulletin")

    def _open_phone_upload_dialog(self):
        from app.ui.phone_upload_dialog import PhoneUploadDialog

        if self._phone_dialog is not None and self._phone_dialog.winfo_exists():
            self._phone_dialog.deiconify()
            self._phone_dialog.lift()
            self._phone_dialog.focus_force()
            return
        self._phone_dialog = PhoneUploadDialog(
            self.winfo_toplevel(),
            on_file_received=lambda path, _append=False, _total=1: self.app.import_documents(
                [path], "bulletin"
            ),
            dialog_title="Recevoir un bulletin de paie depuis le téléphone",
            waiting_text="En attente d'un bulletin de paie... (tu peux en envoyer plusieurs)",
            received_noun="Fichier",
            page_title="Bulletins de paie",
            instruction="Choisis le ou les PDF de tes bulletins de paie (ou un fichier .zip qui en "
                        "contient plusieurs), puis envoie-les au PC.",
            choose_label="Choisir un fichier PDF ou ZIP",
            accept=".pdf,.zip,application/pdf,application/zip,application/x-zip-compressed",
            capture=False,
            multiple=True,
            allowed_suffixes=frozenset({".pdf", ".zip"}),
            default_suffix=".pdf",
        )

    def import_files(self, paths: list[Path], extra_messages: list[str] | None = None) -> None:
        """Importe directement les bulletins donnés (déjà reconnus comme tels par
        MainWindow.import_documents) : pas de formulaire à valider, c'est un PDF numérique relu
        avec recoupements. extra_messages : avertissements venus de l'aiguillage (fichiers ignorés,
        zip illisible...), affichés avec les nôtres."""
        errors: list[str] = list(extra_messages or [])
        warnings: list[str] = []
        parsed: list[tuple[Path, object]] = []
        for path in paths:
            try:
                data = extract_bulletin(path)
            except BulletinError as exc:
                errors.append(f"{path.name} : {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name} : lecture impossible ({exc}).")
                continue
            if not data.period_start:
                errors.append(f"{path.name} : période du bulletin introuvable.")
                continue
            parsed.append((path, data))

        # Un même mois présent plusieurs fois : on garde le bulletin le plus détaillé.
        best: dict[str, tuple] = {}
        for item in parsed:
            path, data = item
            rank = (len(data.lines), path.stat().st_size if path.exists() else 0)
            if data.period_start not in best or rank > best[data.period_start][0]:
                best[data.period_start] = (rank, item)
        for path, data in parsed:
            winner = best[data.period_start][1][0]
            if winner is not path:
                errors.append(
                    f"{_month_label(data.period_start)} : « {path.name} » ignoré (doublon de "
                    f"« {winner.name} »)."
                )
        parsed = [item for _rank, item in best.values()]

        # Une seule question pour tous les bulletins déjà importés (un zip peut en contenir 12).
        existing_months = [
            _month_label(d.period_start) for _p, d in parsed
            if db.get_bulletin_by_period(d.period_start) is not None
        ]
        replace_existing = True
        if existing_months:
            replace_existing = messagebox.askyesno(
                "Bulletins déjà importés",
                f"{len(existing_months)} bulletin(s) déjà importé(s) : {', '.join(existing_months)}."
                "\n\nLes remplacer ? (Non : ils sont ignorés.)",
            )

        imported: list[str] = []
        for path, data in parsed:
            existing = db.get_bulletin_by_period(data.period_start)
            if existing is not None:
                if not replace_existing:
                    continue
                if existing.source_filename:
                    storage.delete_bulletin_file(existing.source_filename)
            bulletin = Bulletin(
                id=existing.id if existing else None,
                period_start=data.period_start, period_end=data.period_end,
                payment_date=data.payment_date, net_paye=data.net_paye, brut=data.brut,
                net_fiscal=data.net_fiscal, heures=data.heures,
                source_filename=storage.store_bulletin_file(path, data.period_start),
                details_json=json.dumps({
                    "lines": [asdict(line) for line in data.lines], "cumuls": data.cumuls,
                    "absences": data.absences, "payment_mode": data.payment_mode,
                }, ensure_ascii=False),
            )
            if existing:
                db.update_bulletin(bulletin)
            else:
                db.insert_bulletin(bulletin)
            imported.append(_month_label(data.period_start))
            warnings += [f"{_month_label(data.period_start)} : {w}" for w in data.warnings]

        self.refresh()
        for child in self.warnings_holder.winfo_children():
            child.destroy()
        frame = show_warnings(self.warnings_holder, errors + warnings)
        if frame:
            frame.pack(fill="x", pady=(0, 6))
        if imported:
            self.status_label.config(text=f"{len(imported)} importé(s) : " + ", ".join(imported))
        elif paths or errors:
            self.status_label.config(text="Aucun bulletin importé.")

    # ------------------------------------------------------------- actions

    def _selected(self) -> Bulletin | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Sélection", "Sélectionne d'abord un bulletin dans la liste.")
            return None
        return db.get_bulletin(int(selection[0]))

    def open_selected_file(self):
        bulletin = self._selected()
        if bulletin is None:
            return
        path = storage.resolve_bulletin_path(bulletin.source_filename)
        if not bulletin.source_filename or not path.exists():
            messagebox.showinfo("Aucun fichier", "Le fichier de ce bulletin est introuvable.")
            return
        try:
            if sys.platform == "win32":
                import os

                os.startfile(str(path))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{exc}")

    def delete_selected(self):
        bulletin = self._selected()
        if bulletin is None:
            return
        if not messagebox.askyesno(
            "Confirmer", f"Supprimer le bulletin {_of_month(bulletin.period_start)} ?"
        ):
            return
        db.delete_bulletin(bulletin.id)
        if bulletin.source_filename:
            storage.delete_bulletin_file(bulletin.source_filename)
        self.refresh()

    def show_details(self):
        bulletin = self._selected()
        if bulletin is None:
            return
        try:
            details = json.loads(bulletin.details_json) if bulletin.details_json else {}
        except (json.JSONDecodeError, TypeError):
            details = {}

        dialog = tk.Toplevel(self)
        dialog.title(f"Bulletin de paie : {_month_label(bulletin.period_start)}")
        dialog.transient(self.winfo_toplevel())
        dialog.geometry("980x640")
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)

        header = (
            f"Net payé : {_money(bulletin.net_paye)} €"
            + (f" le {_fmt_date(bulletin.payment_date)}" if bulletin.payment_date else "")
            + (f" par {details.get('payment_mode', '').lower()}" if details.get("payment_mode") else "")
            + f"   ·   Salaire brut : {_money(bulletin.brut)} €   ·   Net fiscal : "
              f"{_money(bulletin.net_fiscal)} €   ·   Heures déclarées : {_number(bulletin.heures)}"
        )
        ttk.Label(frame, text=header, font=("Segoe UI", 10, "bold"), wraplength=940,
                  justify="left").pack(anchor="w")
        absences = details.get("absences") or []
        if absences:
            ttk.Label(
                frame, text="Absences indiquées : " + " ; ".join(absences), foreground=TEXT_MUTED,
                wraplength=940, justify="left",
            ).pack(anchor="w", pady=(4, 0))

        ttk.Button(frame, text="Fermer", command=dialog.destroy).pack(side="bottom", anchor="e", pady=(12, 0))

        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True, pady=(12, 0))
        columns = ("label", "quantity", "rate", "amount", "employer")
        tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="none")
        for col, text, width, anchor in (
            ("label", "Libellé", 420, "w"), ("quantity", "Quantité / Base", 120, "e"),
            ("rate", "Valeur unit. / Taux", 130, "e"), ("amount", "Montant / Part salarié", 140, "e"),
            ("employer", "Part employeur", 120, "e"),
        ):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor=anchor)
        tree.tag_configure("section", font=("Segoe UI", 9, "bold"), background="#eef3f9")
        tree.tag_configure("total", font=("Segoe UI", 9, "bold"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        tree.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        lines = details.get("lines") or []
        for section, (title, _q, _r, _a) in SECTION_TITLES.items():
            section_lines = [l for l in lines if l.get("section") == section]
            if not section_lines:
                continue
            tree.insert("", "end", values=(title, "", "", "", ""), tags=("section",))
            for line in section_lines:
                label = line.get("label", "")
                is_total = label.upper().startswith(("SALAIRE BRUT", "TOTAL", "NET A PAYER"))
                tree.insert("", "end", values=(
                    "   " + label, _number(line.get("quantity")), _number(line.get("rate"), 4),
                    _money(line.get("amount")), _money(line.get("employer")),
                ), tags=("total",) if is_total else ())
        cumuls = details.get("cumuls") or {}
        if cumuls:
            tree.insert("", "end", values=("Cumuls (pied du bulletin)", "", "", "", ""), tags=("section",))
            for label, value in cumuls.items():
                tree.insert("", "end", values=("   " + label, "", "", _money(value), ""))
        self._details_dialog = dialog

    def compare_selected(self):
        """Compare les éléments variables payés sur ce bulletin à ceux annoncés par la feuille de
        prépaie du mois précédent."""
        bulletin = self._selected()
        if bulletin is None:
            return
        from app.payroll_check import check_bulletin

        check = check_bulletin(bulletin)
        month, previous = _of_month(bulletin.period_start), _of_month(check.period_start)

        dialog = tk.Toplevel(self)
        dialog.title(f"Bulletin {month} comparé à la feuille de prépaie {previous}")
        dialog.transient(self.winfo_toplevel())
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"Le bulletin {month} paie les éléments variables (heures indemnisées, primes, "
                 f"repas) relevés sur la feuille de prépaie {previous}. L'app compare seulement "
                 "les quantités, sans calculer de montant.",
            wraplength=760, justify="left",
        ).pack(anchor="w")

        if check.lines:
            columns = ("label", "prepaie", "bulletin", "diff", "result")
            tree = ttk.Treeview(
                frame, columns=columns, show="headings", height=len(check.lines), selectmode="none"
            )
            for col, text, width in (
                ("label", "Élément", 260),
                ("prepaie", f"Prépaie {_month_label(check.period_start).lower()}", 150),
                ("bulletin", f"Bulletin {_month_label(bulletin.period_start).lower()}", 150),
                ("diff", "Écart", 90),
                ("result", "Résultat", 110),
            ):
                tree.heading(col, text=text)
                tree.column(col, width=width, anchor="w")
            tree.tag_configure("ecart", background=WARN_BG)

            def fmt(value, unit):
                if value is None:
                    return "—"
                return f"{_number(value)} h" if unit == "h" else f"{value:g}"

            for line in check.lines:
                diff = line.diff
                if diff is None:
                    diff_text = "—"
                elif not diff:
                    diff_text = "0"
                elif line.unit == "h":
                    diff_text = f"{diff:+.2f}".replace(".", ",") + " h"
                else:
                    diff_text = f"{diff:+g}"
                tree.insert("", "end", values=(
                    line.label, fmt(line.ot_value, line.unit), fmt(line.payslip_value, line.unit),
                    diff_text, "✓ identique" if line.status == "ok" else "⚠ écart",
                ), tags=() if line.status == "ok" else ("ecart",))
            tree.pack(fill="x", pady=(12, 0))
            for line in check.lines:
                if line.comment:
                    ttk.Label(
                        frame, text=f"• {line.label} : {line.comment}", wraplength=760,
                        justify="left",
                    ).pack(anchor="w", pady=(8, 0))

        for note in check.notes:
            tk.Label(
                frame, text=f"⚠ {note}", bg=WARN_BG, fg=WARN_FG, anchor="w", justify="left",
                wraplength=740, padx=10, pady=8,
            ).pack(fill="x", pady=(12, 0))
        ttk.Button(frame, text="Fermer", command=dialog.destroy).pack(anchor="e", pady=(16, 0))
        self._compare_dialog = dialog

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        bulletins = db.list_bulletins()
        for b in bulletins:
            self.tree.insert("", "end", iid=str(b.id), values=(
                _month_label(b.period_start), _fmt_date(b.payment_date), _money(b.net_paye),
                _money(b.brut), _money(b.net_fiscal), _number(b.heures),
            ))
        self.summary_label.config(text=f"{len(bulletins)} bulletin(s)" if bulletins else "")
