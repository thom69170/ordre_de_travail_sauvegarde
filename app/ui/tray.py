"""Veille dans la zone de notification (à côté de l'horloge) : quand la réception des OT par e-mail
est active, fermer la fenêtre la cache au lieu de quitter - plus de bouton dans la barre des
tâches, l'app continue de relever la boîte. Menu de l'icône : Ouvrir / Relever / Quitter."""
from __future__ import annotations

import queue

from app import mail_import
from app.paths import icon_path

POLL_MS = 300


def pystray_available() -> bool:
    try:
        import pystray  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class TrayController:
    def __init__(self, app, single=None):
        self.app = app
        self.root = app.root
        self.single = single  # SingleInstance : une 2e copie lancée demande à afficher la fenêtre
        self.icon = None
        self._events: queue.Queue = queue.Queue()
        self._told_once = False
        self.root.after(POLL_MS, self._pump)

    # ------------------------------------------------------------------ état

    def wanted(self) -> bool:
        s = mail_import.get_settings()
        return bool(s["enabled"] and mail_import.is_configured(s) and s.get("tray", True))

    @property
    def active(self) -> bool:
        return self.icon is not None

    def refresh(self) -> None:
        """À appeler au démarrage et quand les réglages changent."""
        if self.wanted() and not self.active:
            self._start()
        elif not self.wanted() and self.active:
            self.stop()
            self.show()  # plus de veille possible : la fenêtre ne doit pas rester cachée

    def _start(self) -> None:
        if not pystray_available():
            return
        import pystray
        from PIL import Image

        path = icon_path()
        image = Image.open(path).convert("RGBA").resize((64, 64)) if path else Image.new("RGBA", (64, 64), "#0067c0")
        menu = pystray.Menu(
            pystray.MenuItem("Ouvrir Ordres de travail", lambda *_: self._events.put("show"), default=True),
            pystray.MenuItem("Relever la boîte mail maintenant", lambda *_: self._events.put("check")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda *_: self._events.put("quit")),
        )
        self.icon = pystray.Icon(
            "OrdreDeTravail", image, "Ordres de travail — réception des OT par e-mail active", menu
        )
        self.icon.run_detached()

    def stop(self) -> None:
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ fenêtre

    def is_hidden(self) -> bool:
        return self.root.state() == "withdrawn"

    def hide(self) -> None:
        self.root.withdraw()
        if not self._told_once:
            self._told_once = True
            self.notify(
                "Ordres de travail reste actif ici, à côté de l'horloge : il continue de relever "
                "ta boîte mail. Clic droit sur l'icône → Quitter pour le fermer vraiment."
            )

    def show(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def on_close(self) -> None:
        """Croix de la fenêtre."""
        if self.active:
            self.hide()
        else:
            self.quit()

    def quit(self) -> None:
        self.stop()
        self.root.destroy()

    def notify(self, message: str, title: str = "Ordres de travail") -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:  # noqa: BLE001
                pass

    def set_tooltip(self, text: str) -> None:
        if self.icon is not None:
            try:
                self.icon.title = text[:120]
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ événements (fil d'affichage)

    def _pump(self) -> None:
        """Les clics de l'icône arrivent dans le fil de pystray : on les traite ici, dans celui de Tk."""
        try:
            if self.single is not None and self.single.show_requested():
                self.show()
            while True:
                try:
                    event = self._events.get_nowait()
                except queue.Empty:
                    break
                if event == "show":
                    self.show()
                elif event == "check":
                    self.app.mail_watcher.check_now()
                elif event == "quit":
                    self.quit()
                    return
        finally:
            try:
                self.root.after(POLL_MS, self._pump)
            except Exception:  # noqa: BLE001
                pass  # fenêtre déjà détruite
