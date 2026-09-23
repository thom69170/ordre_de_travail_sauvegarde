"""Copie et organisation des fichiers sources (photos/PDF) importés par l'utilisateur."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.paths import imports_dir, payslips_dir


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


def store_source_files(paths: list[Path], date_iso: str) -> tuple[str, str]:
    """Comme store_source_file, mais pour un ordre de travail dont les pages ont été capturées
    en plusieurs fichiers séparés (ex: 2 photos du téléphone pour un OT sur 2 pages) : les
    combine en un seul PDF multi-page, pour que l'OT garde un seul fichier source cohérent
    (comme n'importe quel autre) plutôt que de rajouter une colonne/liste en base."""
    if len(paths) == 1:
        return store_source_file(paths[0], date_iso)

    from app.ocr_engine import load_pages

    images = []
    for p in paths:
        images.extend(load_pages(p))
    if not images:
        raise ValueError("Aucune page à enregistrer.")

    safe_date = date_iso if date_iso else "sans-date"
    dest_dir = imports_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / f"{safe_date}.pdf"
    counter = 1
    while dest_path.exists():
        dest_path = dest_dir / f"{safe_date}_{counter}.pdf"
        counter += 1

    first, rest = images[0], images[1:]
    first.save(dest_path, "PDF", save_all=True, append_images=rest)
    return dest_path.name, "pdf"


def resolve_source_path(stored_filename: str) -> Path:
    return imports_dir() / stored_filename


def delete_source_file(stored_filename: str) -> None:
    path = resolve_source_path(stored_filename)
    if path.exists():
        path.unlink()


def store_payslip_file(original_path: Path, period_start: str) -> str:
    """Copie une feuille de prépaie dans le dossier de données de l'app. Retourne le nom du
    fichier stocké (préfixé par le début de la période, pour rester lisible)."""
    suffix = original_path.suffix.lower()
    safe_period = period_start if period_start else "sans-periode"
    dest_dir = payslips_dir()

    dest_path = dest_dir / f"{safe_period}{suffix}"
    counter = 1
    while dest_path.exists():
        dest_path = dest_dir / f"{safe_period}_{counter}{suffix}"
        counter += 1

    shutil.copy2(original_path, dest_path)
    return dest_path.name


def resolve_payslip_path(stored_filename: str) -> Path:
    return payslips_dir() / stored_filename


def delete_payslip_file(stored_filename: str) -> None:
    path = resolve_payslip_path(stored_filename)
    if path.exists():
        path.unlink()
