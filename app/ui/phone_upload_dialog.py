"""Boîte de dialogue pour recevoir une photo/PDF envoyé depuis le téléphone (même Wi-Fi)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from PIL import ImageTk

from app.phone_upload import PhoneUploadServer
from app.ui.common import ACCENT, TEXT_MUTED


class PhoneUploadDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        on_file_received: Callable[[Path, bool], None],
        *,
        dialog_title: str = "Recevoir depuis le téléphone",
        waiting_text: str = "En attente d'une photo...",
        received_noun: str = "Photo",
        **server_kwargs,
    ):
        super().__init__(parent)
        self.title(dialog_title)
        self.resizable(False, False)
        self.transient(parent)

        self._on_file_received = on_file_received
        self._waiting_text = waiting_text
        self._received_noun = received_noun
        self._received_count = 0
        self._qr_imgtk = None
        self._server = PhoneUploadServer(self._handle_received, **server_kwargs)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)

        try:
            url = self._server.start()
        except OSError as exc:
            ttk.Label(
                self, text=f"Impossible de démarrer le serveur local :\n{exc}", padding=20
            ).pack()
            return

        self._show_url(url)
        self.grab_set()

    def _build_ui(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Depuis ton téléphone connecté au même Wi-Fi que ce PC, scanne ce QR code\n"
                 "avec l'appareil photo (ou saisis l'adresse ci-dessous dans le navigateur) :",
            justify="left",
        ).pack(anchor="w")

        self.qr_label = tk.Label(frame)
        self.qr_label.pack(pady=12)

        self.url_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.url_var, width=42, state="readonly").pack(fill="x")

        self.status_label = ttk.Label(frame, text=self._waiting_text, foreground=ACCENT)
        self.status_label.pack(anchor="w", pady=(12, 0))

        ttk.Label(
            frame,
            text="Le téléphone doit être sur le même réseau Wi-Fi que ce PC.\n"
                 "Cette réception reste active tant que cette fenêtre est ouverte : tu peux "
                 "envoyer plusieurs documents à la suite avec le même QR code, ils seront "
                 "traités l'un après l'autre.",
            foreground=TEXT_MUTED, justify="left", wraplength=320,
        ).pack(anchor="w", pady=(4, 0))

        ttk.Button(frame, text="Fermer", command=self.close).pack(anchor="e", pady=(16, 0))

    def _show_url(self, url: str):
        self.url_var.set(url)
        try:
            import qrcode

            qr_img = qrcode.make(url, box_size=6, border=2)
            pil_img = qr_img.get_image() if hasattr(qr_img, "get_image") else qr_img
            self._qr_imgtk = ImageTk.PhotoImage(pil_img)
            self.qr_label.config(image=self._qr_imgtk)
        except Exception:  # noqa: BLE001
            self.qr_label.config(
                text="(QR code indisponible - copie l'adresse ci-dessus dans le\n"
                     "navigateur du téléphone)",
                wraplength=320, justify="left",
            )

    def _handle_received(self, path: Path, is_append: bool):
        # Appelé depuis le thread du serveur HTTP : on repasse sur le thread Tk avant de toucher l'UI.
        self.after(0, lambda: self._on_received_ui(path, is_append))

    def _on_received_ui(self, path: Path, is_append: bool):
        self._received_count += 1
        self.status_label.config(
            text=f"{self._received_count} fichier(s) reçu(s) au total (dernier : {path.name}) — "
                 "tu peux continuer à en envoyer d'autres."
        )
        self._on_file_received(path, is_append)

    def close(self):
        self._server.stop()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
