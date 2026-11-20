"""Diagnostic : journal technique des imports et rapport « Signaler un problème ».

Le journal (diag.jsonl, dans le dossier de données) garde, pour chaque import de bulletin / feuille de
prépaie / photo, ce qui s'est vraiment passé : fichiers reçus, type reconnu, réponse brute de l'IA,
regroupement des pages, décisions (remplacé, ignoré, fusionné), erreurs. Il ne contient JAMAIS de mot de
passe, de clé d'API ni d'identité (nom, adresse, matricule : ces champs ne sont pas lus).

Le rapport est un fichier .zip créé sur demande de l'utilisateur (rien n'est envoyé tout seul) :
report.json (version, système, réglages sans secret, résumé des données, derniers événements) et, seulement
si l'utilisateur le coche, les photos lues récemment (réduites).
"""
from __future__ import annotations

import json
import platform
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from app.paths import data_dir
from app.version import VERSION

MAX_EVENTS = 400            # lignes gardées dans le journal
MAX_PHOTOS = 8              # photos récentes gardées (réduites) pour le rapport
PHOTO_MAX_SIDE = 1600
REPORT_EVENTS = 250         # événements inclus dans un rapport
SCHEMA = 1

_LOCK = threading.Lock()


def _log_path() -> Path:
    return data_dir() / "diag.jsonl"


def _photos_dir() -> Path:
    d = data_dir() / "diag_photos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record(event: str, **data) -> None:
    """Ajoute un événement au journal. Ne lève jamais : un diagnostic ne doit pas casser l'app."""
    try:
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "v": VERSION, "event": event, **data}
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _LOCK:
            path = _log_path()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if path.stat().st_size > 2_000_000:  # rotation grossière
                lines = path.read_text(encoding="utf-8").splitlines()[-MAX_EVENTS:]
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def record_exception(context: str, exc: BaseException | None = None) -> None:
    text = "".join(traceback.format_exception(exc)) if exc is not None else traceback.format_exc()
    record("exception", context=context, traceback=text[-3000:])


def install_exception_hooks() -> None:
    """Les erreurs non gérées (fil d'arrière-plan, autre) vont aussi au journal."""
    previous_thread_hook = threading.excepthook

    def thread_hook(args):
        record("exception", context=f"thread {args.thread.name if args.thread else '?'}",
               traceback="".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))[-3000:])
        previous_thread_hook(args)

    threading.excepthook = thread_hook


def recent_events(limit: int = REPORT_EVENTS) -> list[dict]:
    try:
        lines = _log_path().read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


# ----------------------------------------------------------------------------- photos

def keep_photo(path: Path) -> str | None:
    """Garde une copie réduite d'une photo lue (pour le rapport, si l'utilisateur l'autorise) ;
    retourne son nom de fichier. Seules les MAX_PHOTOS plus récentes sont conservées."""
    try:
        from PIL import Image, ImageOps

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in path.stem)[:40]
        target = _photos_dir() / f"{stamp}_{safe}.jpg"
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
            img.save(target, "JPEG", quality=72)
        files = sorted(_photos_dir().glob("*.jpg"))
        for old in files[:-MAX_PHOTOS]:
            old.unlink(missing_ok=True)
        return target.name
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------- rapport

def _package_versions() -> dict[str, str]:
    from importlib import metadata

    versions = {}
    for name in ("Pillow", "pypdfium2", "pytesseract", "sv-ttk", "pywinstyles", "qrcode", "pystray"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "absent"
    return versions


def _data_summary() -> dict:
    """Ce que contient la base, sans aucun détail personnel : périodes, nombres, noms de fichiers."""
    from app import db

    summary: dict = {}
    try:
        orders = db.list_work_orders()
        summary["ordres_de_travail"] = {
            "nombre": len(orders), "premier": min((o.date for o in orders), default=""),
            "dernier": max((o.date for o in orders), default=""),
        }
        bulletins = []
        for b in db.list_bulletins():
            try:
                details = json.loads(b.details_json) if b.details_json else {}
            except ValueError:
                details = {}
            lines = details.get("lines") or []
            bulletins.append({
                "periode": b.period_start, "fichier": b.source_filename, "lignes": len(lines),
                "lignes_brut": sum(1 for l in lines if l.get("section") == "brut"),
                "cumuls": len(details.get("cumuls") or {}), "net_paye": bool(b.net_paye),
                "date_paiement": bool(b.payment_date),
            })
        summary["bulletins"] = bulletins
        payslips = []
        for p in db.list_payslips():
            try:
                details = json.loads(p.details_json) if p.details_json else {}
            except ValueError:
                details = {}
            payslips.append({
                "periode": p.period_start, "fichier": p.source_filename,
                "recap": len(details.get("recap") or {}), "compteurs": len(details.get("compteurs") or {}),
            })
        summary["feuilles_de_prepaie"] = payslips
    except Exception as exc:  # noqa: BLE001
        summary["erreur"] = str(exc)
    return summary


def _settings_flags() -> dict:
    from app import autostart, config, mail_import

    cfg = config.load_config()
    flags = {
        "cle_gemini_presente": bool(config.get_gemini_api_key()),
        "accord_photos_paie": bool(cfg.get("payroll_photos_ok")),
    }
    try:
        mail = mail_import.get_settings()
        flags["reception_mail"] = {
            "activee": bool(mail["enabled"]), "configuree": mail_import.is_configured(mail),
            "veille_zone_notification": bool(mail.get("tray", True)),
            "intervalle_minutes": mail.get("interval_minutes"),
        }
        flags["lancement_auto_windows"] = autostart.is_enabled()
    except Exception as exc:  # noqa: BLE001
        flags["erreur_reglages_mail"] = str(exc)
    return flags


def build_report_data(user_note: str = "") -> dict:
    import tkinter

    from app.paths import base_dir, is_frozen

    return {
        "schema": SCHEMA,
        "cree_le": datetime.now().isoformat(timespec="seconds"),
        "version_app": VERSION,
        "note_utilisateur": user_note.strip(),
        "systeme": {
            "os": platform.platform(), "python": sys.version.split()[0], "tk": tkinter.TkVersion,
            "executable_gele": is_frozen(), "dossier_app": str(base_dir()),
        },
        "modules": _package_versions(),
        "reglages": _settings_flags(),
        "donnees": _data_summary(),
        "evenements": recent_events(),
    }


def create_report(target: Path, user_note: str = "", include_photos: bool = False) -> Path:
    """Écrit le rapport (.zip) à l'emplacement choisi par l'utilisateur."""
    data = build_report_data(user_note)
    photos = sorted(_photos_dir().glob("*.jpg")) if include_photos else []
    data["photos_jointes"] = [p.name for p in photos]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps(data, ensure_ascii=False, indent=1, default=str))
        for photo in photos:
            archive.write(photo, f"photos/{photo.name}")
    return target
