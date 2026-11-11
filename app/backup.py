"""Sauvegarde / restauration de toutes les données de l'utilisateur dans un seul fichier .zip,
et export d'une liste d'ordres de travail en CSV (ouvrable dans Excel).

Uniquement la bibliothèque standard : rien à installer en plus sur les installations existantes.
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from app.models import EXTRA_FIELDS, SUMMARY_FIELDS, WorkOrder
from app.paths import bulletins_dir, data_dir, db_path, imports_dir, payslips_dir

DB_NAME = "ordres.db"
# Dossiers sauvegardés en plus de la base. Volontairement PAS config.json (clé API Gemini,
# personnelle - à ne pas retrouver dans un fichier qu'on peut être amené à partager), ni les
# dossiers techniques (runtime, photos temporaires reçues du téléphone).
BACKUP_FOLDERS = {"imports": imports_dir, "payslips": payslips_dir, "bulletins": bulletins_dir}

FRENCH_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class BackupError(Exception):
    pass


def default_backup_name() -> str:
    return f"ordres_de_travail_sauvegarde_{date.today().isoformat()}.zip"


def create_backup(dest: Path) -> int:
    """Écrit la base + les fichiers importés dans dest (.zip). Retourne le nombre de fichiers
    (hors base) sauvegardés."""
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        # Copie cohérente de la base via l'API de sauvegarde de SQLite (plutôt qu'une simple
        # copie du fichier, qui pourrait tomber au milieu d'une écriture).
        snapshot = Path(tmp) / DB_NAME
        src = sqlite3.connect(db_path())
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, DB_NAME)
            for folder, get_dir in BACKUP_FOLDERS.items():
                for path in sorted(get_dir().iterdir()):
                    if path.is_file():
                        zf.write(path, f"{folder}/{path.name}")
                        count += 1
    return count


def _backup_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str, str]]:
    """Membres du zip qu'on accepte de restaurer : (info, dossier, nom_de_fichier). Tout autre
    chemin (sous-dossier inattendu, "..", chemin absolu) est ignoré : on n'écrit jamais ailleurs
    que dans les dossiers de données de l'app."""
    members = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = info.filename.replace("\\", "/").split("/")
        if len(parts) == 2 and parts[0] in BACKUP_FOLDERS and parts[1] not in ("", ".", ".."):
            members.append((info, parts[0], parts[1]))
    return members


def restore_backup(src: Path) -> tuple[Path, int]:
    """Remplace les données actuelles par celles de la sauvegarde src. Les données actuelles sont
    d'abord sauvegardées automatiquement (chemin retourné) pour pouvoir revenir en arrière.
    Retourne (sauvegarde_automatique, nombre_de_fichiers_restaurés)."""
    if not zipfile.is_zipfile(src):
        raise BackupError("Ce fichier n'est pas une sauvegarde valide (.zip attendu).")

    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(src) as zf:
        if DB_NAME not in zf.namelist():
            raise BackupError("Ce fichier .zip ne contient pas de base « ordres.db ».")

        # Tout est d'abord extrait et vérifié à part : si la sauvegarde est abîmée, les données
        # actuelles ne sont pas touchées.
        staging = Path(tmp)
        new_db = staging / DB_NAME
        with zf.open(DB_NAME) as fsrc, open(new_db, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
        try:
            conn = sqlite3.connect(new_db)
            try:
                conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise BackupError(f"La base de cette sauvegarde est illisible : {exc}") from exc

        members = _backup_members(zf)
        for info, folder, name in members:
            target = staging / folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fsrc, open(target, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)

        auto_dir = data_dir() / "sauvegardes_auto"
        auto_dir.mkdir(parents=True, exist_ok=True)
        safety = auto_dir / f"avant_restauration_{datetime.now():%Y-%m-%d_%Hh%Mm%S}.zip"
        create_backup(safety)

        shutil.copyfile(new_db, db_path())
        for folder, get_dir in BACKUP_FOLDERS.items():
            dest_dir = get_dir()
            for path in dest_dir.iterdir():
                if path.is_file():
                    path.unlink()
            staged = staging / folder
            if staged.is_dir():
                for path in staged.iterdir():
                    shutil.copyfile(path, dest_dir / path.name)

    from app import db

    db.init_db()  # une sauvegarde plus ancienne peut avoir un schéma à migrer
    return safety, len(members)


def _fr(value: float) -> str:
    """Nombre avec virgule décimale, pour qu'Excel (français) le reconnaisse comme un nombre."""
    return f"{value:.2f}".replace(".", ",")


def export_work_orders_csv(orders: list[WorkOrder], dest: Path) -> None:
    """Un OT par ligne (dans l'ordre des dates) + une ligne TOTAL. Séparateur « ; » et encodage
    UTF-8 avec BOM : s'ouvre directement dans Excel avec les accents et les colonnes correctes."""
    numeric_fields = SUMMARY_FIELDS + EXTRA_FIELDS
    header = (
        ["Date", "Jour", "Conducteur", "Matricule"]
        + [label for _name, label in numeric_fields]
        + ["Dernière minute", "Repas midi", "Repas soir", "Nb trajets", "Trajets", "Notes"]
    )
    totals = {name: 0.0 for name, _label in numeric_fields}
    last_minute_total = 0
    lunch_total = dinner_total = 0
    trajets_total = 0

    with open(dest, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        for wo in sorted(orders, key=lambda o: o.date):
            try:
                d = date.fromisoformat(wo.date)
                date_text, day_text = d.strftime("%d/%m/%Y"), FRENCH_DAYS[d.weekday()]
            except ValueError:
                date_text, day_text = wo.date, ""
            counts = Counter(wo.trajets)
            trajets_text = " | ".join(
                f"{n}× {label}" if n > 1 else label for label, n in sorted(counts.items())
            )
            row = [date_text, day_text, wo.driver_name, wo.matricule]
            for name, _label in numeric_fields:
                value = getattr(wo, name)
                totals[name] += value
                row.append(_fr(value))
            row += [
                "Oui" if wo.last_minute_change else "", "Oui" if wo.repas_midi else "",
                "Oui" if wo.repas_soir else "", len(wo.trajets), trajets_text,
                " ".join(wo.notes.split()),
            ]
            writer.writerow(row)
            last_minute_total += 1 if wo.last_minute_change else 0
            lunch_total += int(wo.repas_midi)
            dinner_total += int(wo.repas_soir)
            trajets_total += len(wo.trajets)

        writer.writerow(
            ["TOTAL", f"{len(orders)} jour(s)", "", ""]
            + [_fr(totals[name]) for name, _label in numeric_fields]
            + [last_minute_total, lunch_total, dinner_total, trajets_total, "", ""]
        )
