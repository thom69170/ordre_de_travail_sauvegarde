"""Onglet 'Paramètres' : configuration optionnelle d'une clé API Gemini pour une lecture
(OCR) bien plus précise que le moteur local Tesseract."""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from app import config
from app.ui.common import ACCENT, ERROR_FG, SUCCESS, WARN_BG, WARN_FG, ScrollableFrame

API_KEY_URL = "https://aistudio.google.com/app/apikey"


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()
        self._refresh_status()

    def _build_ui(self):
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        form = scroll.inner

        intro = ttk.LabelFrame(form, text="Lecture automatique par IA (Gemini) — optionnel", padding=14)
        intro.pack(fill="x", padx=14, pady=14)
        ttk.Label(
            intro,
            text=(
                "Par défaut, l'app lit tes photos/PDF avec un moteur OCR local (Tesseract), "
                "gratuit mais parfois imprécis. En renseignant une clé API Gemini (l'IA de "
                "Google), la lecture devient bien plus fiable : elle comprend directement le "
                "document au lieu de reconnaître des caractères un par un.\n\n"
                "C'est entièrement facultatif : sans clé, l'app continue de fonctionner "
                "normalement avec l'OCR local."
            ),
            wraplength=780, justify="left",
        ).pack(anchor="w")

        warn = tk.Frame(form, bg=WARN_BG, padx=12, pady=10)
        warn.pack(fill="x", padx=14, pady=(0, 14))
        tk.Label(
            warn,
            text=(
                "⚠ Confidentialité : si tu configures une clé, tes photos d'ordres de travail "
                "seront envoyées aux serveurs de Google (API Gemini) pour être analysées, au "
                "lieu de rester traitées uniquement sur ta machine. Ne configure une clé que si "
                "cela te convient. Tu peux la supprimer à tout moment (bouton plus bas) pour "
                "revenir à une lecture 100% locale."
            ),
            bg=WARN_BG, fg=WARN_FG, wraplength=780, justify="left", anchor="w",
        ).pack(fill="x")

        tuto = ttk.LabelFrame(form, text="Comment obtenir une clé API (gratuit)", padding=14)
        tuto.pack(fill="x", padx=14, pady=(0, 14))
        steps = [
            "Clique sur le bouton ci-dessous pour ouvrir la page Google AI Studio dans ton navigateur.",
            "Connecte-toi avec un compte Google (personnel, ça ne nécessite pas de carte bancaire "
            "pour le niveau gratuit).",
            "Clique sur le bouton \"Create API key\" (\"Créer une clé API\").",
            "Choisis ou crée un projet Google Cloud quand c'est demandé (les valeurs par défaut "
            "conviennent).",
            "Copie la clé générée (elle commence par \"AIza...\").",
            "Reviens ici, colle-la dans le champ ci-dessous, puis clique sur \"Tester puis "
            "enregistrer\".",
        ]
        for i, step in enumerate(steps, start=1):
            row = ttk.Frame(tuto)
            row.pack(fill="x", pady=3, anchor="w")
            ttk.Label(row, text=f"{i}.", width=3, font=("Segoe UI", 9, "bold")).pack(side="left", anchor="n")
            ttk.Label(row, text=step, wraplength=740, justify="left").pack(side="left", anchor="w")

        ttk.Button(
            tuto, text="Ouvrir aistudio.google.com/app/apikey pour créer une clé",
            command=lambda: webbrowser.open(API_KEY_URL),
        ).pack(anchor="w", pady=(8, 0))

        key_frame = ttk.LabelFrame(form, text="Ta clé API Gemini", padding=14)
        key_frame.pack(fill="x", padx=14, pady=(0, 14))

        entry_row = ttk.Frame(key_frame)
        entry_row.pack(fill="x")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(entry_row, textvariable=self.key_var, show="•", width=60)
        self.key_entry.pack(side="left", fill="x", expand=True)
        self._shown = False
        self.toggle_btn = ttk.Button(entry_row, text="Afficher", command=self._toggle_visibility, width=10)
        self.toggle_btn.pack(side="left", padx=(6, 0))

        btn_row = ttk.Frame(key_frame)
        btn_row.pack(fill="x", pady=(10, 0))
        self.test_save_btn = ttk.Button(btn_row, text="Tester puis enregistrer", command=self._test_and_save)
        self.test_save_btn.pack(side="left")
        ttk.Button(btn_row, text="Supprimer la clé (revenir à l'OCR local)", command=self._clear_key).pack(
            side="left", padx=8
        )

        self.status_label = ttk.Label(key_frame, text="", wraplength=780, justify="left")
        self.status_label.pack(anchor="w", pady=(10, 0))

        ttk.Label(
            form,
            text="La clé est enregistrée localement en clair dans %LOCALAPPDATA%\\OrdreDeTravail\\config.json "
                 "(comme le reste des données de l'app) : elle n'est jamais partagée ailleurs que vers l'API "
                 "Gemini elle-même.",
            wraplength=780, justify="left", foreground="#666",
        ).pack(anchor="w", padx=14, pady=(0, 14))

    def _toggle_visibility(self):
        self._shown = not self._shown
        self.key_entry.config(show="" if self._shown else "•")
        self.toggle_btn.config(text="Masquer" if self._shown else "Afficher")

    def _refresh_status(self):
        existing = config.get_gemini_api_key()
        if existing:
            masked = existing[:6] + "…" + existing[-4:] if len(existing) > 12 else "••••"
            self.status_label.config(
                text=f"✓ Clé Gemini active ({masked}) : la lecture automatique utilise Gemini.",
                foreground=SUCCESS,
            )
            self.key_var.set(existing)
        else:
            self.status_label.config(
                text="Aucune clé configurée : la lecture automatique utilise l'OCR local (Tesseract).",
                foreground="#666",
            )

    def _test_and_save(self):
        key = self.key_var.get().strip()
        if not key:
            self.status_label.config(text="Saisis une clé avant de tester.", foreground=ERROR_FG)
            return
        self.test_save_btn.config(state="disabled")
        self.status_label.config(text="Test de la clé en cours...", foreground=ACCENT)
        self.update_idletasks()
        threading.Thread(target=self._test_and_save_worker, args=(key,), daemon=True).start()

    def _test_and_save_worker(self, key: str):
        from app import gemini_engine

        ok, message = gemini_engine.test_api_key(key)
        self.after(0, lambda: self._on_test_result(key, ok, message))

    def _on_test_result(self, key: str, ok: bool, message: str):
        self.test_save_btn.config(state="normal")
        if ok:
            config.set_gemini_api_key(key)
            self.status_label.config(text=f"✓ {message} — enregistrée.", foreground=SUCCESS)
            self.app.refresh_other_tabs("settings")
        else:
            self.status_label.config(text=f"✗ Échec : {message}", foreground=ERROR_FG)

    def _clear_key(self):
        config.set_gemini_api_key(None)
        self.key_var.set("")
        self._refresh_status()
        self.app.refresh_other_tabs("settings")
