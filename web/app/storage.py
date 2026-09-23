"""Copie et organisation des fichiers sources (photos/PDF) importés, par utilisateur."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import DATA_DIR


def _user_dir(user_id: int, subdir: str) -> Path:
    d = DATA_DIR / "users" / str(user_id) / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def imports_dir(user_id: int) -> Path:
    return _user_dir(user_id, "imports")


def payslips_dir(user_id: int) -> Path:
    return _user_dir(user_id, "payslips")


def store_source_file(user_id: int, original_path: Path, date_iso: str) -> tuple[str, str]:
    """Copie le fichier source dans le dossier de données de l'utilisateur.

    Retourne (nom_fichier_stocke, type) où type vaut 'pdf' ou 'image'.
    """
    suffix = original_path.suffix.lower()
    source_type = "pdf" if suffix == ".pdf" else "image"

    safe_date = date_iso if date_iso else "sans-date"
    dest_dir = imports_dir(user_id)

    base_name = f"{safe_date}{suffix}"
    dest_path = dest_dir / base_name
    counter = 1
    while dest_path.exists():
        dest_path = dest_dir / f"{safe_date}_{counter}{suffix}"
        counter += 1

    shutil.copy2(original_path, dest_path)
    return dest_path.name, source_type


def store_source_files(user_id: int, paths: list[Path], date_iso: str) -> tuple[str, str]:
    """Comme store_source_file, mais combine plusieurs fichiers (pages capturées séparément)
    en un seul PDF multi-page, pour que l'OT garde un seul fichier source cohérent."""
    if len(paths) == 1:
        return store_source_file(user_id, paths[0], date_iso)

    from app.ocr_engine import load_pages

    images = []
    for p in paths:
        images.extend(load_pages(p))
    if not images:
        raise ValueError("Aucune page à enregistrer.")

    safe_date = date_iso if date_iso else "sans-date"
    dest_dir = imports_dir(user_id)

    dest_path = dest_dir / f"{safe_date}.pdf"
    counter = 1
    while dest_path.exists():
        dest_path = dest_dir / f"{safe_date}_{counter}.pdf"
        counter += 1

    first, rest = images[0], images[1:]
    first.save(dest_path, "PDF", save_all=True, append_images=rest)
    return dest_path.name, "pdf"


def resolve_source_path(user_id: int, stored_filename: str) -> Path:
    return imports_dir(user_id) / stored_filename


def delete_source_file(user_id: int, stored_filename: str) -> None:
    path = resolve_source_path(user_id, stored_filename)
    if path.exists():
        path.unlink()


def store_payslip_file(user_id: int, original_path: Path, period_start: str) -> str:
    suffix = original_path.suffix.lower()
    safe_period = period_start if period_start else "sans-periode"
    dest_dir = payslips_dir(user_id)

    dest_path = dest_dir / f"{safe_period}{suffix}"
    counter = 1
    while dest_path.exists():
        dest_path = dest_dir / f"{safe_period}_{counter}{suffix}"
        counter += 1

    shutil.copy2(original_path, dest_path)
    return dest_path.name


def resolve_payslip_path(user_id: int, stored_filename: str) -> Path:
    return payslips_dir(user_id) / stored_filename


def delete_payslip_file(user_id: int, stored_filename: str) -> None:
    path = resolve_payslip_path(user_id, stored_filename)
    if path.exists():
        path.unlink()
