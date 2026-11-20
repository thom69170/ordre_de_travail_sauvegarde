"""Fenêtre principale : assemble les onglets Importer / Historique / Statistiques / Heures sup. /
Bulletins de paie / Paramètres."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.bulletin_tab import BulletinTab
from app.ui.history_tab import HistoryTab
from app.ui.import_tab import ImportTab
from app.ui.payslip_tab import PayslipTab
from app.ui.settings_tab import SettingsTab
from app.ui.stats_tab import StatsTab

APP_TITLE = "Ordres de travail"


class MainWindow(ttk.Frame):
    def __init__(self, root: tk.Tk, single=None):
        super().__init__(root)
        self.root = root
        self.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # Bandeau du bas, visible seulement quand la réception par e-mail a quelque chose à dire
        # (OT enregistrés, OT à relire, erreur de connexion) ; un clic ouvre l'onglet Importer.
        self.mail_status = tk.Label(self, text="", anchor="w", padx=12, pady=5, cursor="hand2")
        self.mail_status.bind("<Button-1>", lambda _e: self.select_tab("import"))
        self._mail_status_alert = False

        self.import_tab = ImportTab(self.notebook, self)
        self.history_tab = HistoryTab(self.notebook, self)
        self.stats_tab = StatsTab(self.notebook, self)
        self.payslip_tab = PayslipTab(self.notebook, self)
        self.bulletin_tab = BulletinTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)

        self.notebook.add(self.import_tab, text="Importer")
        self.notebook.add(self.history_tab, text="Historique")
        self.notebook.add(self.stats_tab, text="Statistiques")
        self.notebook.add(self.payslip_tab, text="Heures sup.")
        self.notebook.add(self.bulletin_tab, text="Bulletins de paie")
        self.notebook.add(self.settings_tab, text="Paramètres")

        self._tab_ids = {
            "import": self.import_tab, "history": self.history_tab,
            "stats": self.stats_tab, "payslip": self.payslip_tab,
            "bulletin": self.bulletin_tab, "settings": self.settings_tab,
        }

        # Réception des OT par e-mail (option, désactivée par défaut : ne fait rien sans réglages).
        from app.ui.mail_watcher import MailWatcher

        self.mail_watcher = MailWatcher(self)
        self.mail_watcher.start()

        # Veille à côté de l'horloge : fermer la fenêtre la cache (si la réception par e-mail est
        # active) au lieu de quitter ; voir app/ui/tray.py. single : verrou "une seule copie".
        from app.ui.tray import TrayController

        self.tray = TrayController(self, single)
        self.tray.refresh()
        root.protocol("WM_DELETE_WINDOW", self.tray.on_close)

    def set_mail_status(self, text: str, alert: bool = False) -> None:
        from app.ui.common import SUCCESS, WARN_BG, WARN_FG

        self._mail_status_alert = alert
        if not text:
            self.mail_status.pack_forget()
            return
        # alerte = quelque chose à faire ou un problème ; sinon simple information
        bg, fg = (WARN_BG, WARN_FG) if alert else ("#e8f5e9", SUCCESS)
        self.mail_status.config(text=text, bg=bg, fg=fg)
        if not self.mail_status.winfo_ismapped():
            self.mail_status.pack(side="bottom", fill="x", before=self.notebook)

    def mail_status_is_error(self) -> bool:
        return self._mail_status_alert

    def select_tab(self, name: str):
        widget = self._tab_ids.get(name)
        if widget is not None:
            self.notebook.select(widget)

    def import_documents(self, paths, origin: str) -> None:
        """Point d'entrée unique pour importer des documents de paie, quel que soit l'onglet où
        ils ont été choisis ou reçus : les .zip sont ouverts, chaque PDF est reconnu (bulletin de
        paie / feuille de prépaie) et envoyé à l'onglet qui sait le lire. origin : "bulletin" ou
        "payslip" (l'onglet d'où vient l'import, qui affiche les messages d'erreur)."""
        from pathlib import Path

        from app import payroll_vision, zip_import

        paths = [Path(p) for p in paths]
        has_zip = any(p.suffix.lower() == ".zip" for p in paths)
        expanded = zip_import.expand_documents(paths)
        errors = list(expanded.errors)
        photos = [p for p in expanded.files if payroll_vision.is_image(p)]
        if photos:
            # Photos : lues par l'IA (quelques secondes chacune), donc en arrière-plan ; la suite de
            # l'import reprend ici quand elles sont toutes lues.
            if not payroll_vision.available():
                errors += [f"{p.name} : la lecture d'une photo nécessite une clé Gemini (onglet Paramètres)."
                           for p in photos]
                expanded.files = [p for p in expanded.files if p not in photos]
                photos = []
            elif not self._confirm_photo_upload():
                expanded.cleanup()
                return
        if photos:
            self._read_photos(photos, expanded, errors, origin, has_zip)
        else:
            self._dispatch_documents(expanded, errors, origin, has_zip)

    def _confirm_photo_upload(self) -> bool:
        """Une photo de bulletin contient des données personnelles (nom, adresse, salaire) : elle est
        envoyée à Google pour être lue. Accord demandé une fois, retenu ensuite."""
        from tkinter import messagebox

        from app import config

        cfg = config.load_config()
        if cfg.get("payroll_photos_ok"):
            return True
        if not messagebox.askyesno(
            "Lire une photo de document de paie ?",
            "Pour lire une photo, l'application l'envoie à Google (IA Gemini). Un bulletin de paie "
            "contient des informations personnelles (nom, adresse, salaire).\n\nUn PDF numérique, "
            "lui, est lu uniquement sur ton PC.\n\nAutoriser l'envoi des photos de bulletins et de "
            "feuilles de prépaie à Gemini ? (Cet accord est retenu ; tu peux le retirer dans "
            "Paramètres.)",
        ):
            return False
        cfg["payroll_photos_ok"] = True
        config.save_config(cfg)
        return True

    def _read_photos(self, photos, expanded, errors, origin, has_zip) -> None:
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from app import payroll_vision

        count = len(photos)
        self.set_mail_status(f"⏳ Lecture de {count} photo{'s' if count > 1 else ''} par l'IA... "
                             "(quelques secondes par photo)")
        self.root.config(cursor="watch")
        failures: list[str] = []

        def work(path):
            try:
                payroll_vision.prefetch(path)
            except payroll_vision.PhotoError as exc:
                failures.append(f"{path.name} : {exc}")
                return path
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name} : lecture impossible ({exc}).")
                return path
            return None

        def run():
            with ThreadPoolExecutor(max_workers=3) as pool:
                failed = [p for p in pool.map(work, photos) if p is not None]
            self.root.after(0, lambda: finish(failed))

        def finish(failed):
            self.root.config(cursor="")
            self.set_mail_status("")
            expanded.files = [p for p in expanded.files if p not in failed]
            self._dispatch_documents(expanded, errors + failures, origin, has_zip)

        threading.Thread(target=run, daemon=True).start()

    def _dispatch_documents(self, expanded, errors, origin, has_zip) -> None:
        from app import zip_import

        try:
            bulletins, prepaies = [], []
            for path in expanded.files:
                kind = zip_import.classify(path)
                if kind == zip_import.KIND_BULLETIN:
                    bulletins.append(path)
                elif kind == zip_import.KIND_PREPAIE:
                    prepaies.append(path)
                else:
                    errors.append(f"{path.name} : ni un bulletin de paie ni une feuille de prépaie reconnus.")

            origin_is_bulletin = origin == "bulletin"
            if bulletins or origin_is_bulletin:
                self.bulletin_tab.import_files(bulletins, errors if origin_is_bulletin else [])
            if prepaies or not origin_is_bulletin:
                if len(prepaies) == 1 and not has_zip:
                    # Une seule feuille de prépaie : le formulaire habituel, à relire avant d'enregistrer.
                    self.payslip_tab.review_single(prepaies[0], [] if origin_is_bulletin else errors)
                else:
                    self.payslip_tab.import_many(prepaies, [] if origin_is_bulletin else errors)

            if bulletins and prepaies:
                self.select_tab(origin)
            elif bulletins:
                self.select_tab("bulletin")
            elif prepaies:
                self.select_tab("payslip")
            else:
                self.select_tab(origin)
        finally:
            expanded.cleanup()

    def mark_update_available(self) -> None:
        self.notebook.tab(self.settings_tab, text="Paramètres 🔵 MàJ")

    def reload_all_data(self) -> None:
        """Après une restauration de sauvegarde : tout ce qui est affiché vient de l'ancienne
        base et doit être relu."""
        self.import_tab.reset_form()
        self.history_tab.refresh()
        self.stats_tab.refresh()
        self.payslip_tab.reset_form()
        self.payslip_tab.refresh()
        self.bulletin_tab.refresh()

    def refresh_other_tabs(self, source: str):
        if source != "history":
            self.history_tab.refresh()
        if source != "stats":
            self.stats_tab.refresh()
        if source != "import":
            self.import_tab._maybe_show_ocr_banner()
