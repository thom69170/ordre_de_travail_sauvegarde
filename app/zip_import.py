"""Import de documents de paie reçus dans un fichier .zip (bulletins de paie et/ou feuilles de
prépaie mélangés), et reconnaissance du type de chaque PDF.

Extraction prudente (un .zip peut venir d'un e-mail ou d'un téléphone) : seuls les PDF sont
extraits, sous un nom simple choisi par nous (jamais le chemin du zip : pas de "../"), avec des
limites de nombre et de taille. Uniquement la bibliothèque standard.
"""
from __future__ import annotations

import gc
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_ENTRIES = 300  # entrées examinées dans un zip
MAX_FILE_BYTES = 30 * 1024 * 1024  # un PDF de paie fait quelques dizaines de Ko
MAX_TOTAL_BYTES = 300 * 1024 * 1024

KIND_BULLETIN = "bulletin"
KIND_PREPAIE = "prepaie"


@dataclass
class ExpandedDocuments:
    """Fichiers prêts à être lus, plus les anomalies rencontrées. À fermer avec cleanup() quand
    les fichiers ont été importés (ils sont alors copiés ailleurs par l'import)."""
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _temp_dirs: list[Path] = field(default_factory=list)

    def cleanup(self) -> None:
        gc.collect()  # libère d'éventuels PDF encore ouverts, qui verrouillent les fichiers (Windows)
        for directory in self._temp_dirs:
            shutil.rmtree(directory, ignore_errors=True)
        self._temp_dirs.clear()


def _is_junk(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return any(p.startswith(".") or p == "__MACOSX" for p in parts if p)


def _safe_stem(name: str) -> str:
    stem = Path(name.replace("\\", "/")).name
    stem = re.sub(r"[^\w.\- ]", "_", stem, flags=re.UNICODE).strip(" .") or "document.pdf"
    return stem if stem.lower().endswith(".pdf") else stem + ".pdf"


def _extract_zip(zip_path: Path, out: ExpandedDocuments) -> None:
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        out.errors.append(f"{zip_path.name} : fichier .zip illisible ({exc}).")
        return

    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_ENTRIES:
            out.errors.append(
                f"{zip_path.name} : trop de fichiers ({len(infos)}), seuls les {MAX_ENTRIES} "
                "premiers sont examinés."
            )
            infos = infos[:MAX_ENTRIES]

        temp_dir = Path(tempfile.mkdtemp(prefix="ordres_zip_"))
        out._temp_dirs.append(temp_dir)
        total = 0
        found = 0
        for index, info in enumerate(infos):
            name = info.filename
            if _is_junk(name):
                continue
            if not name.lower().endswith(".pdf"):
                if name.lower().endswith(".zip"):
                    out.errors.append(f"{zip_path.name} : le zip « {Path(name).name} » imbriqué est ignoré.")
                elif not name.lower().endswith((".txt", ".xml", ".json", ".csv")):
                    out.errors.append(f"{zip_path.name} : « {Path(name).name} » ignoré (ce n'est pas un PDF).")
                continue
            if info.flag_bits & 0x1:
                out.errors.append(f"{zip_path.name} : le zip est protégé par un mot de passe.")
                return
            if info.file_size > MAX_FILE_BYTES or total + info.file_size > MAX_TOTAL_BYTES:
                out.errors.append(f"{zip_path.name} : « {Path(name).name} » est trop volumineux, ignoré.")
                continue

            # Un sous-dossier par entrée : deux PDF de même nom dans des dossiers différents du zip
            # ne s'écrasent pas, et le nom du fichier (affiché dans les messages) reste le sien.
            target = temp_dir / f"{index:03d}" / _safe_stem(name)
            target.parent.mkdir(exist_ok=True)
            try:
                written = 0
                with archive.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_FILE_BYTES:  # en-tête de taille mensonger
                            raise ValueError("taille réelle supérieure à la limite")
                        dst.write(chunk)
            except (zipfile.BadZipFile, RuntimeError, ValueError, OSError) as exc:
                target.unlink(missing_ok=True)
                out.errors.append(f"{zip_path.name} : « {Path(name).name} » illisible ({exc}).")
                continue
            total += written
            out.files.append(target)
            found += 1
        if not found:
            out.errors.append(f"{zip_path.name} : aucun PDF trouvé dans ce zip.")


def expand_documents(paths: list[Path]) -> ExpandedDocuments:
    """Les chemins donnés, avec chaque .zip remplacé par les PDF qu'il contient."""
    out = ExpandedDocuments()
    for path in paths:
        if path.suffix.lower() == ".zip":
            _extract_zip(path, out)
        else:
            out.files.append(path)
    return out


def classify(path: Path) -> str | None:
    """"bulletin" (bulletin de paie), "prepaie" (feuille de prépaie) ou None."""
    from app.bulletin_parser import is_bulletin

    if is_bulletin(path):
        return KIND_BULLETIN
    if path.suffix.lower() != ".pdf":
        return None
    try:
        from app.payslip_parser import extract_payslip

        return KIND_PREPAIE if extract_payslip(path).period_start else None
    except Exception:  # noqa: BLE001
        return None
