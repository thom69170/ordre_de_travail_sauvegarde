"""Deuxieme etape du premier lancement (executee par le Python local fraichement installe) :
verifie/installe le moteur OCR Tesseract et telecharge les langues necessaires (dont le
francais). Autonome : ne dépend pas du package app/ pour rester robuste tant que rien n'est
encore garanti installe.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

APP_NAME = "OrdreDeTravail"
LANGS = ["eng", "fra"]
TESSDATA_BASE_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"

COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def runtime_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) / APP_NAME if local_app_data else Path.home() / f".{APP_NAME.lower()}"
    d = base / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    for p in COMMON_TESSERACT_PATHS:
        if Path(p).exists():
            return p
    return None


def install_tesseract_via_winget() -> bool:
    winget = shutil.which("winget")
    if not winget:
        print("winget introuvable : impossible d'installer Tesseract automatiquement.")
        print("Installe-le manuellement depuis https://github.com/UB-Mannheim/tesseract/wiki")
        return False
    print("Installation du moteur OCR Tesseract via winget (une fenêtre peut apparaître)...")
    try:
        result = subprocess.run(
            [
                winget, "install", "--id", "UB-Mannheim.TesseractOCR", "-e",
                "--accept-package-agreements", "--accept-source-agreements",
            ],
            check=False,
        )
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        print(f"Échec de l'installation via winget : {exc}")
        return False


def download_tessdata() -> None:
    target = runtime_dir() / "tessdata"
    target.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        dest = target / f"{lang}.traineddata"
        if dest.exists():
            continue
        url = f"{TESSDATA_BASE_URL}/{lang}.traineddata"
        print(f"Téléchargement du modèle de langue '{lang}'...")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as exc:  # noqa: BLE001
            print(f"Échec du téléchargement de '{lang}': {exc}")


def main() -> int:
    tesseract_path = find_tesseract()
    if tesseract_path:
        print(f"Moteur OCR Tesseract déjà présent : {tesseract_path}")
    else:
        install_tesseract_via_winget()
        tesseract_path = find_tesseract()
        if tesseract_path:
            print(f"Moteur OCR Tesseract installé : {tesseract_path}")
        else:
            print("Moteur OCR non disponible : l'application fonctionnera en saisie manuelle.")

    download_tessdata()
    return 0


if __name__ == "__main__":
    sys.exit(main())
