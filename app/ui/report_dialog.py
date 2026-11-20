"""Fenêtre « Signaler un problème » : crée un rapport de diagnostic (.zip) à envoyer au développeur.

Rien n'est envoyé automatiquement : le rapport est un fichier que l'utilisateur crée, peut ouvrir, et joint
lui-même à un e-mail. Les photos ne sont jointes que si la case est cochée (elles contiennent des données
personnelles)."""
from __future__ import annotations

import subprocess
import sys
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote

from app import diagnostics
from app.ui.common import ACCENT, ERROR_FG, SUCCESS, TEXT_MUTED

CONTACT_EMAIL = "contact@informatiqueetsolution.fr"

INCLUDED = (
    "• la version de l'application, ton système et les modules installés ;\n"
    "• tes réglages SANS aucun secret (jamais de mot de passe ni de clé : seulement « présent / absent ») ;\n"
    "• la liste de tes bulletins et feuilles de prépaie (mois, nombre de lignes, noms de fichiers), sans "
    "montants ni identité ;\n"
    "• le journal des derniers imports : fichiers reçus, type reconnu, ce que l'IA a lu (lignes et "
    "chiffres du document), pages regroupées ou non, erreurs."
)


def open_report_dialog(parent: tk.Misc) -> None:
    ReportDialog(parent.winfo_toplevel())


class ReportDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Signaler un problème")
        self.transient(parent)
        self.resizable(False, False)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, wraplength=560, justify="left",
            text="Décris ce qui ne marche pas, puis crée le rapport : un petit fichier à m'envoyer par "
                 "e-mail. Il m'aide à comprendre exactement ce que l'application a fait. Rien n'est "
                 "envoyé automatiquement.",
        ).pack(anchor="w")

        ttk.Label(frame, text="Que s'est-il passé ? (ce que tu attendais, ce que tu as vu)",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 2))
        self.note = tk.Text(frame, width=70, height=5, wrap="word", font=("Segoe UI", 10))
        self.note.pack(fill="x")

        ttk.Label(frame, text="Ce que contient le rapport", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(12, 2))
        ttk.Label(frame, text=INCLUDED, wraplength=560, justify="left", foreground=TEXT_MUTED).pack(anchor="w")

        photos = len(list(diagnostics._photos_dir().glob("*.jpg")))
        self.photos_var = tk.BooleanVar(value=False)
        photo_row = ttk.Frame(frame)
        photo_row.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(
            photo_row, variable=self.photos_var, state="normal" if photos else "disabled"
        ).pack(side="left", anchor="n")
        # (un libellé séparé : une case à cocher ne passe pas à la ligne)
        ttk.Label(
            photo_row, wraplength=520, justify="left",
            text=f"Joindre les {photos} dernière(s) photo(s) lue(s) (réduites). ATTENTION : un bulletin de paie "
                 "contient ton nom, ton adresse et ton salaire : coche seulement si tu es d'accord."
                 if photos else "Aucune photo récente à joindre.",
        ).pack(side="left", anchor="w")

        self.status = ttk.Label(frame, text="", wraplength=560, justify="left")
        self.status.pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Créer le rapport...", command=self._create).pack(side="left")
        ttk.Button(buttons, text="Fermer", command=self.destroy).pack(side="right")

        self.grab_set()
        self.note.focus_set()

    def _create(self) -> None:
        default = f"rapport_ordres_de_travail_{datetime.now():%Y%m%d-%H%M}.zip"
        desktop = Path.home() / "Desktop"
        path_str = filedialog.asksaveasfilename(
            parent=self, title="Enregistrer le rapport", defaultextension=".zip", initialfile=default,
            initialdir=str(desktop if desktop.exists() else Path.home()), filetypes=[("Rapport (.zip)", "*.zip")],
        )
        if not path_str:
            return
        try:
            target = diagnostics.create_report(
                Path(path_str), self.note.get("1.0", "end"), include_photos=self.photos_var.get()
            )
        except Exception as exc:  # noqa: BLE001
            self.status.config(text=f"Impossible de créer le rapport : {exc}", foreground=ERROR_FG)
            return
        self.status.config(text=f"✓ Rapport créé : {target}", foreground=SUCCESS)
        self._show_in_folder(target)
        if messagebox.askyesno(
            "Rapport créé",
            f"Le rapport est prêt :\n{target}\n\nOuvrir un e-mail pour l'envoyer ? Pense à y JOINDRE le "
            "fichier (glisse-le dans le message : je viens d'ouvrir son dossier).",
            parent=self,
        ):
            subject = "Ordres de travail : rapport de problème"
            body = f"Bonjour,\n\nJe joins le rapport « {target.name} ».\n\n"
            webbrowser.open(f"mailto:{CONTACT_EMAIL}?subject={quote(subject)}&body={quote(body)}")

    @staticmethod
    def _show_in_folder(path: Path) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
        except Exception:  # noqa: BLE001
            pass
