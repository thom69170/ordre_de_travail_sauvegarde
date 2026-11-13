"""Lancement automatique au démarrage de Windows (clé « Run » de l'utilisateur, sans droits
administrateur) : l'app démarre réduite à côté de l'horloge (--tray) pour relever la boîte mail."""
from __future__ import annotations

import sys
from pathlib import Path

from app.paths import base_dir, is_frozen

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "OrdreDeTravail"


def command() -> str:
    if is_frozen():
        return f'"{sys.executable}" --tray'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")  # sans fenêtre de console
    return f'"{pythonw if pythonw.exists() else exe}" "{base_dir() / "main.py"}" --tray'


def is_enabled(value_name: str = VALUE_NAME) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, value_name)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool, value_name: str = VALUE_NAME) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except OSError:
                pass
