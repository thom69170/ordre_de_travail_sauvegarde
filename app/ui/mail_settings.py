"""Section des Paramètres : réception des ordres de travail par e-mail (voir app/mail_import.py)."""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from app import autostart, mail_import
from app.ui.common import ACCENT, ERROR_FG, SUCCESS, TEXT_MUTED


def _fmt_event(event: dict) -> str:
    try:
        when = datetime.fromisoformat(event["time"]).strftime("%d/%m %H:%M")
    except (KeyError, ValueError):
        when = "?"
    return f"{when}  {event.get('text', '')}"


class MailSettingsFrame(ttk.LabelFrame):
    def __init__(self, parent, app):
        super().__init__(parent, text="Réception des ordres de travail par e-mail — optionnel", padding=14)
        self.app = app
        self._shown = False
        self._build()
        self._load()

    def _build(self):
        ttk.Label(
            self,
            text=(
                "Envoie la photo de ton ordre de travail (plusieurs pages = plusieurs pièces jointes "
                "dans le même e-mail) à une boîte mail réservée à cet usage : l'application, quand elle "
                "est ouverte, la relève toute seule, lit l'OT et l'enregistre. Si la lecture n'est pas "
                "parfaitement nette, l'OT t'attend dans l'onglet Importer pour relecture. "
                "Un e-mail = un ordre de travail."
            ),
            wraplength=780, justify="left",
        ).pack(anchor="w")

        grid = ttk.Frame(self)
        grid.pack(fill="x", pady=(10, 0))
        grid.columnconfigure(1, weight=1)

        self.enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            grid, text="Activer la réception par e-mail", variable=self.enabled_var
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.address_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar(value="993")
        self.interval_var = tk.StringVar(value=str(mail_import.DEFAULT_INTERVAL_MINUTES))

        ttk.Label(grid, text="Adresse de la boîte dédiée").grid(row=1, column=0, sticky="w", pady=3)
        address_entry = ttk.Entry(grid, textvariable=self.address_var)
        address_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=3)
        address_entry.bind("<FocusOut>", self._suggest_host)

        ttk.Label(grid, text="Mot de passe (d'application)").grid(row=2, column=0, sticky="w", pady=3)
        self.password_entry = ttk.Entry(grid, textvariable=self.password_var, show="•")
        self.password_entry.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=3)
        self.toggle_btn = ttk.Button(grid, text="Afficher", width=10, command=self._toggle_password)
        self.toggle_btn.grid(row=2, column=2, padx=(6, 0))

        ttk.Label(grid, text="Serveur IMAP / port").grid(row=3, column=0, sticky="w", pady=3)
        host_row = ttk.Frame(grid)
        host_row.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=3)
        ttk.Entry(host_row, textvariable=self.host_var).pack(side="left", fill="x", expand=True)
        ttk.Entry(host_row, textvariable=self.port_var, width=6).pack(side="left", padx=(6, 0))

        ttk.Label(grid, text="Expéditeur(s) autorisé(s)").grid(row=4, column=0, sticky="w", pady=3)
        self.senders_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.senders_var).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=3)
        ttk.Label(
            grid, foreground=TEXT_MUTED, wraplength=640, justify="left",
            text="Ton adresse personnelle, depuis laquelle tu envoies les photos (plusieurs : sépare par "
                 "une virgule). Les e-mails venant de toute autre adresse sont ignorés.",
        ).grid(row=5, column=1, columnspan=2, sticky="w", padx=(10, 0))

        ttk.Label(grid, text="Relever la boîte toutes les").grid(row=6, column=0, sticky="w", pady=(8, 3))
        interval_row = ttk.Frame(grid)
        interval_row.grid(row=6, column=1, sticky="w", padx=(10, 0), pady=(8, 3))
        ttk.Spinbox(interval_row, from_=1, to=120, width=5, textvariable=self.interval_var).pack(side="left")
        ttk.Label(interval_row, text="minutes (uniquement quand l'application est ouverte)").pack(side="left", padx=6)

        from app.ui.tray import pystray_available

        self.tray_var = tk.BooleanVar(value=True)
        self.autostart_var = tk.BooleanVar()
        ttk.Checkbutton(
            self, variable=self.tray_var, state="normal" if pystray_available() else "disabled",
            text="Garder l'application en veille à côté de l'horloge quand je ferme la fenêtre "
                 "(pas de bouton dans la barre des tâches ; clic droit sur l'icône → Quitter pour la fermer)",
        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(
            self, variable=self.autostart_var,
            text="Lancer l'application au démarrage de Windows, directement en veille à côté de l'horloge",
        ).pack(anchor="w", pady=(4, 0))
        if not pystray_available():
            ttk.Label(
                self, foreground=ERROR_FG, wraplength=780,
                text="La veille à côté de l'horloge nécessite le module « pystray » : relance l'application "
                     "avec « Ordres de travail.bat » pour qu'il s'installe.",
            ).pack(anchor="w")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(10, 0))
        self.save_btn = ttk.Button(buttons, text="Enregistrer", command=self._save)
        self.save_btn.pack(side="left")
        self.test_btn = ttk.Button(buttons, text="Tester la connexion", command=self._test)
        self.test_btn.pack(side="left", padx=8)
        self.check_btn = ttk.Button(buttons, text="Relever maintenant", command=self._check_now)
        self.check_btn.pack(side="left")

        self.status = ttk.Label(self, text="", wraplength=780, justify="left")
        self.status.pack(anchor="w", pady=(8, 0))

        ttk.Label(self, text="Dernières activités", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 2))
        self.log_label = ttk.Label(self, text="", wraplength=780, justify="left", foreground=TEXT_MUTED)
        self.log_label.pack(anchor="w")

        ttk.Label(
            self, foreground=TEXT_MUTED, wraplength=780, justify="left",
            text=(
                "Conseils : utilise une boîte vraiment dédiée à cet usage, avec un mot de passe "
                "d'application (pas ton mot de passe principal) et l'accès IMAP activé. Le mot de passe "
                "est enregistré en clair sur ce PC dans config.json, comme la clé Gemini, et n'est pas "
                "inclus dans les sauvegardes. Les e-mails ne sont jamais supprimés ni déplacés ; les "
                "photos au format HEIC (iPhone) ne sont pas lues : envoie-les en JPEG."
            ),
        ).pack(anchor="w", pady=(10, 0))

    # ------------------------------------------------------------------ réglages

    def _load(self):
        s = mail_import.get_settings()
        self.enabled_var.set(bool(s["enabled"]))
        self.address_var.set(s["address"])
        self.password_var.set(s["password"])
        self.host_var.set(s["host"])
        self.port_var.set(str(s["port"]))
        self.senders_var.set(", ".join(s["allowed_senders"]))
        self.interval_var.set(str(s["interval_minutes"]))
        self.tray_var.set(bool(s.get("tray", True)))
        self.autostart_var.set(autostart.is_enabled())
        self._refresh_log()

    def _collect(self) -> dict:
        s = mail_import.get_settings()
        try:
            port = int(self.port_var.get().strip() or 993)
        except ValueError:
            port = 993
        try:
            interval = int(self.interval_var.get().strip())
        except ValueError:
            interval = mail_import.DEFAULT_INTERVAL_MINUTES
        s.update(
            enabled=self.enabled_var.get(), address=self.address_var.get().strip(),
            password=self.password_var.get(), host=self.host_var.get().strip(), port=port,
            allowed_senders=mail_import.parse_senders(self.senders_var.get()),
            interval_minutes=max(1, min(interval, 120)), tray=self.tray_var.get(),
        )
        return s

    def _problem(self, s: dict) -> str:
        if not s["address"] or "@" not in s["address"]:
            return "Saisis l'adresse de la boîte dédiée."
        if not s["password"]:
            return "Saisis le mot de passe d'application de la boîte."
        if not s["host"]:
            return "Saisis le serveur IMAP (par exemple imap.gmail.com)."
        if not s["allowed_senders"]:
            return ("Indique au moins une adresse d'expéditeur autorisée (la tienne) : "
                    "sans elle, n'importe qui connaissant l'adresse pourrait envoyer des documents.")
        return ""

    def _suggest_host(self, _event=None):
        if not self.host_var.get().strip():
            self.host_var.set(mail_import.guess_host(self.address_var.get()))

    def _toggle_password(self):
        self._shown = not self._shown
        self.password_entry.config(show="" if self._shown else "•")
        self.toggle_btn.config(text="Masquer" if self._shown else "Afficher")

    def _say(self, text: str, color: str):
        self.status.config(text=text, foreground=color)

    def _refresh_log(self):
        events = mail_import.recent_events(8)
        self.log_label.config(text="\n".join(_fmt_event(e) for e in events) or "Rien pour l'instant.")

    def _save(self, quiet: bool = False) -> bool:
        self._suggest_host()
        s = self._collect()
        if s["enabled"]:
            problem = self._problem(s)
            if problem:
                self._say(problem, ERROR_FG)
                return False
        mail_import.save_settings(s)
        try:
            autostart.set_enabled(self.autostart_var.get())
        except OSError as exc:
            self._say(f"Réglages enregistrés, mais le lancement au démarrage de Windows a échoué : {exc}", ERROR_FG)
            self.app.mail_watcher.reconfigure(first_delay_ms=500)
            self.app.tray.refresh()
            return True
        self.app.mail_watcher.reconfigure(first_delay_ms=500)
        self.app.tray.refresh()
        if not quiet:
            self._say("✓ Réglages enregistrés." + (
                " La boîte sera relevée dans un instant, puis toutes les "
                f"{s['interval_minutes']} minutes." if s["enabled"] else " La réception est désactivée."), SUCCESS)
        return True

    # ------------------------------------------------------------------ test et relève

    def _test(self):
        self._suggest_host()
        s = self._collect()
        problem = self._problem(s)
        if problem:
            self._say(problem, ERROR_FG)
            return
        self.test_btn.config(state="disabled")
        self._say("Test de la connexion...", ACCENT)

        def worker():
            ok, message = mail_import.test_connection(s)
            self.after(0, lambda: self._test_done(ok, message))

        threading.Thread(target=worker, daemon=True).start()

    def _test_done(self, ok: bool, message: str):
        self.test_btn.config(state="normal")
        self._say(("✓ " if ok else "✗ ") + message, SUCCESS if ok else ERROR_FG)

    def _check_now(self):
        s = self._collect()
        problem = self._problem(s)
        if problem:
            self._say(problem, ERROR_FG)
            return
        if not self._save(quiet=True):
            return
        if not mail_import.is_configured(mail_import.get_settings()):
            self._say("Réglages incomplets.", ERROR_FG)
            return
        self.check_btn.config(state="disabled")
        self._say("Relève de la boîte en cours...", ACCENT)
        self.app.mail_watcher.check_now(self._check_done)

    def _check_done(self, summary: str, error: str):
        self.check_btn.config(state="normal")
        self._refresh_log()
        if error:
            self._say("✗ " + error, ERROR_FG)
        else:
            self._say("✓ " + summary, SUCCESS)
