"""Regroupe les fichiers d'un même envoi du téléphone.

La page web du téléphone envoie les fichiers un par un, chacun avec le nombre total de fichiers de
l'envoi (X-Total) et un indicateur « suite » (X-Append) pour tous sauf le premier. Pour les
bulletins de paie, les deux pages doivent être lues ENSEMBLE : sans ce regroupement, la 2e page,
traitée seule, aurait pu remplacer la 1re ou être ignorée.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

WAIT_MS = 20000  # attente maximale d'un fichier manquant (connexion coupée...) avant d'importer le reste


class PhoneBatch:
    def __init__(self, widget, deliver: Callable[[list[Path]], None], wait_ms: int = WAIT_MS):
        self._widget = widget
        self._deliver = deliver
        self._wait_ms = wait_ms
        self._files: list[Path] = []
        self._expected = 1
        self._timer = None

    def add(self, path: Path, is_append: bool = False, batch_total: int = 1) -> None:
        """À brancher comme on_file_received de la fenêtre du QR code (fil d'affichage)."""
        if not is_append and self._files:
            self._flush()  # un nouvel envoi commence : le précédent, incomplet, est livré tel quel
        if not is_append:
            self._expected = max(1, batch_total)
        self._files.append(path)
        if len(self._files) >= self._expected:
            self._flush()
        else:
            self._cancel_timer()
            self._timer = self._widget.after(self._wait_ms, self._flush)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            try:
                self._widget.after_cancel(self._timer)
            except Exception:  # noqa: BLE001
                pass
            self._timer = None

    def _flush(self) -> None:
        self._cancel_timer()
        files, self._files = self._files, []
        if files:
            self._deliver(files)
