"""Résolution des chemins de l'application (mode développement et mode .exe empaqueté)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "OrdreDeTravail"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    """Dossier contenant l'exécutable (ou la racine du projet en mode développement)."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def bundled_resource_dir() -> Path:
    """Dossier des ressources embarquées (vendor/, assets/) - _MEIPASS en mode onefile."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return base_dir()


def data_dir() -> Path:
    """Dossier de données utilisateur, persistant entre les mises à jour de l'app."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        d = Path(local_app_data) / APP_NAME
    else:
        d = Path.home() / f".{APP_NAME.lower()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def imports_dir() -> Path:
    d = data_dir() / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "ordres.db"


def runtime_dir() -> Path:
    """Dossier accueillant le Python et les données Tesseract installés par setup/bootstrap.py
    (utilisé par la distribution 'légère' - voir setup/README)."""
    d = data_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def downloaded_tessdata_dir() -> Path | None:
    """Dossier de langues Tesseract téléchargé par setup/bootstrap.py (fra.traineddata, etc.)."""
    candidate = runtime_dir() / "tessdata"
    if candidate.exists() and any(candidate.glob("*.traineddata")):
        return candidate
    return None


def tesseract_exe_path() -> Path | None:
    candidate = bundled_resource_dir() / "vendor" / "tesseract" / "tesseract.exe"
    if candidate.exists():
        return candidate
    return None


def tessdata_dir() -> Path | None:
    candidate = bundled_resource_dir() / "vendor" / "tesseract" / "tessdata"
    if candidate.exists():
        return candidate
    return None


def icon_path() -> Path | None:
    candidate = bundled_resource_dir() / "assets" / "icon.ico"
    if candidate.exists():
        return candidate
    return None
