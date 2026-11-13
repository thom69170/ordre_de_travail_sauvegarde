"""Une seule copie de l'application à la fois (Windows).

Indispensable quand l'app reste en veille à côté de l'horloge : une 2e copie lancée par erreur
relèverait la même boîte mail en parallèle. La 2e copie prévient donc la 1re (qui se remet au
premier plan) puis se ferme. Les noms dépendent du dossier de données, pour qu'un environnement de
test isolé ne gêne pas l'application réelle."""
from __future__ import annotations

import hashlib
import sys

from app.paths import data_dir

ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0


def _names() -> tuple[str, str]:
    tag = hashlib.sha1(str(data_dir()).lower().encode("utf-8")).hexdigest()[:12]
    return f"Local\\OrdreDeTravail_{tag}_lock", f"Local\\OrdreDeTravail_{tag}_show"


class SingleInstance:
    def __init__(self):
        self._mutex = None
        self._event = None
        self._k32 = None
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateEventW.restype = wintypes.HANDLE
        k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k32.OpenEventW.restype = wintypes.HANDLE
        k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k32.SetEvent.argtypes = [wintypes.HANDLE]
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32

    def acquire(self) -> bool:
        """True si c'est la première copie. Sinon, prévient la copie déjà lancée et renvoie False."""
        if self._k32 is None:
            return True
        import ctypes

        lock_name, show_name = _names()
        self._mutex = self._k32.CreateMutexW(None, False, lock_name)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            other = self._k32.OpenEventW(EVENT_MODIFY_STATE, False, show_name)
            if other:
                self._k32.SetEvent(other)
                self._k32.CloseHandle(other)
            return False
        self._event = self._k32.CreateEventW(None, False, False, show_name)  # remise à zéro auto
        return True

    def show_requested(self) -> bool:
        """Une autre copie a été lancée et demande qu'on remette la fenêtre au premier plan."""
        if self._k32 is None or not self._event:
            return False
        return self._k32.WaitForSingleObject(self._event, 0) == WAIT_OBJECT_0
