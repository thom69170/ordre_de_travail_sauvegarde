"""Copie et organisation des fichiers sources (photos/PDF) importés par l'utilisateur."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.paths import imports_dir


def store_source_file(original_path: Path, date_iso: str) -> tuple[str, str]:
    """Copie le fichier source dans le dossier de données de l'app.

    Retourne (nom_fichier_stocke, type) où type vaut 'pdf' ou 'image'.
    Le nom stocké est préfixé par la date pour rester lisible en cas d'exploration manuelle.
    """
    suffix = original_path.suffix.lower()
    source_type = "pdf" if suffix == ".pdf" else "image"

    safe_date = date_iso if date_iso else "sans-date"
    dest_dir = imports_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{safe_date}{suffix}"
    dest_path = dest_dir / base_name
    counter = 1
    while dest_path.exists():
        dest_path = dest_dir / f"{safe_date}_{counter}{suffix}"
        counter += 1

    shutil.copy2(original_path, dest_path)
    return dest_path.name, source_type


def resolve_source_path(stored_filename: str) -> Path:
    return imports_dir() / stored_filename


def delete_source_file(stored_filename: str) -> None:
    path = resolve_source_path(stored_filename)
    if path.exists():
        path.unlink()
