"""Résolution des chemins pour la version web (conteneur Linux/Docker).

Contrairement à l'app desktop, il n'y a pas de Tesseract "embarqué" à côté de l'exécutable :
on installe le paquet système `tesseract-ocr` (+ `tesseract-ocr-fra`) dans l'image Docker, donc
ocr_engine.configure() le trouve via `shutil.which("tesseract")` (branche système).
"""
from __future__ import annotations

from pathlib import Path


def bundled_resource_dir() -> Path:
    return Path(__file__).resolve().parent


def downloaded_tessdata_dir() -> Path | None:
    return None


def tesseract_exe_path() -> Path | None:
    return None


def tessdata_dir() -> Path | None:
    return None
