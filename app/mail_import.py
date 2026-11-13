"""Réception des ordres de travail par e-mail (option personnelle, désactivée par défaut).

Une boîte mail dédiée reçoit les photos d'OT envoyées par l'utilisateur ; l'app la consulte (IMAP)
tant qu'elle est ouverte, télécharge les photos/PDF des nouveaux messages puis les traite comme un
import normal (voir app/ui/mail_watcher.py). Ce module ne contient aucune interface :

  - réglages (config.json, clé "mail"), journal et mémoire des messages déjà reçus ;
  - consultation de la boîte (fetch_new_mails) : filtre sur l'expéditeur, téléchargement des pièces
    jointes dans un dossier à part, message marqué lu seulement une fois les fichiers sur le disque ;
  - traitement d'un message (process_mail) : lecture par l'IA, enregistrement automatique si tout
    est net, sinon l'OT part en relecture dans l'onglet Importer.

Les messages ne sont jamais supprimés ni déplacés de la boîte.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import imaplib
import json
import mimetypes
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app import config
from app.paths import data_dir

# Au plus N pièces jointes par message (= pages d'un même OT) ; au-delà d'une taille, on ignore.
MAX_ATTACHMENTS = 12
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_MESSAGE_BYTES = 60 * 1024 * 1024
# Les images plus petites que ça sont des logos de signature, pas des photos de document.
MIN_IMAGE_BYTES = 20 * 1024
ATTACHMENT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
UNSUPPORTED_NOTE_EXTENSIONS = {".heic", ".heif"}
MAX_PROCESS_ATTEMPTS = 3
KEEP_DAYS = 30
STATE_IDS_LIMIT = 1000
LOG_LIMIT = 60
DEFAULT_INTERVAL_MINUTES = 5

KNOWN_HOSTS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com", "outlook.fr": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com", "hotmail.fr": "outlook.office365.com",
    "live.fr": "outlook.office365.com", "live.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com", "yahoo.fr": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com",
    "orange.fr": "imap.orange.fr", "wanadoo.fr": "imap.orange.fr",
    "free.fr": "imap.free.fr", "sfr.fr": "imap.sfr.fr", "laposte.net": "imap.laposte.net",
    "gmx.fr": "imap.gmx.net", "gmx.com": "imap.gmx.com",
}


class MailError(Exception):
    """Erreur de connexion ou de lecture de la boîte, avec un message lisible par l'utilisateur."""


# ----------------------------------------------------------------------------- réglages

def default_settings() -> dict:
    return {
        "enabled": False, "address": "", "password": "", "host": "", "port": 993, "ssl": True,
        "folder": "INBOX", "allowed_senders": [], "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "tray": True,  # fermer la fenêtre = veille à côté de l'horloge (seulement si la réception est active)
    }


def get_settings() -> dict:
    settings = default_settings()
    stored = config.load_config().get("mail")
    if isinstance(stored, dict):
        settings.update({k: v for k, v in stored.items() if k in settings})
    return settings


def save_settings(settings: dict) -> None:
    cfg = config.load_config()
    cfg["mail"] = {k: settings.get(k) for k in default_settings()}
    config.save_config(cfg)


def guess_host(address: str) -> str:
    domain = address.rsplit("@", 1)[-1].strip().lower() if "@" in address else ""
    if not domain:
        return ""
    return KNOWN_HOSTS.get(domain, f"imap.{domain}")


def parse_senders(text: str) -> list[str]:
    """Liste d'adresses saisies séparées par des virgules, points-virgules, espaces ou retours à
    la ligne -> adresses en minuscules, sans doublon."""
    found: list[str] = []
    for part in re.split(r"[\s,;]+", text or ""):
        part = part.strip().strip("<>").lower()
        if part and "@" in part and part not in found:
            found.append(part)
    return found


def is_configured(settings: dict) -> bool:
    return bool(settings["address"] and settings["password"] and settings["host"]
                and settings["allowed_senders"])


def interval_seconds(settings: dict) -> int:
    try:
        minutes = int(settings.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES)
    except (TypeError, ValueError):
        minutes = DEFAULT_INTERVAL_MINUTES
    return max(1, min(minutes, 120)) * 60


# ----------------------------------------------------------------------------- dossiers, état, journal

def inbox_dir() -> Path:
    d = data_dir() / "mail_inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return data_dir() / "mail_state.json"


def _log_path() -> Path:
    return data_dir() / "mail_log.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _known_ids() -> list[str]:
    return _read_json(_state_path(), {}).get("ids", [])


def _remember_id(message_id: str) -> None:
    ids = _known_ids()
    if message_id not in ids:
        ids.append(message_id)
    _state_path().write_text(json.dumps({"ids": ids[-STATE_IDS_LIMIT:]}), encoding="utf-8")


def log_event(text: str, level: str = "info") -> None:
    """Journal visible dans les Paramètres : ce que la réception e-mail a fait (ou refusé)."""
    events = _read_json(_log_path(), [])
    events.append({"time": datetime.now().isoformat(timespec="seconds"), "level": level, "text": text})
    try:
        _log_path().write_text(json.dumps(events[-LOG_LIMIT:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def recent_events(limit: int = 12) -> list[dict]:
    return list(reversed(_read_json(_log_path(), [])[-limit:]))


# ----------------------------------------------------------------------------- messages reçus

@dataclass
class ReceivedMail:
    """Un message accepté : ses pièces jointes sont déjà sur le disque (folder), dans l'ordre."""
    folder: Path
    message_id: str
    sender: str
    subject: str
    files: list[Path]
    notes: list[str] = field(default_factory=list)
    attempts: int = 0

    @property
    def manifest(self) -> Path:
        return self.folder / "mail.json"

    def save_manifest(self, status: str) -> None:
        self.manifest.write_text(json.dumps({
            "status": status, "message_id": self.message_id, "sender": self.sender,
            "subject": self.subject, "files": [p.name for p in self.files],
            "notes": self.notes, "attempts": self.attempts,
        }, ensure_ascii=False), encoding="utf-8")


@dataclass
class FetchReport:
    mails: list[ReceivedMail] = field(default_factory=list)
    ignored: int = 0  # messages lus mais écartés (expéditeur non autorisé, déjà reçu, sans photo...)


def pending_mails() -> list[ReceivedMail]:
    """Messages déjà téléchargés mais pas encore traités jusqu'au bout (fermeture de l'app, erreur
    passagère) : ils sont repris au prochain passage."""
    found: list[ReceivedMail] = []
    for folder in sorted(inbox_dir().iterdir()):
        data = _read_json(folder / "mail.json", None) if folder.is_dir() else None
        if not data or data.get("status") != "pending":
            continue
        files = [folder / name for name in data.get("files", []) if (folder / name).exists()]
        if not files:
            continue
        found.append(ReceivedMail(
            folder=folder, message_id=data.get("message_id", ""), sender=data.get("sender", ""),
            subject=data.get("subject", ""), files=files, notes=data.get("notes", []),
            attempts=int(data.get("attempts", 0)),
        ))
    return found


def cleanup_old_folders(now: float | None = None) -> None:
    """Supprime les dossiers de messages déjà traités depuis plus de KEEP_DAYS jours."""
    limit = (now or time.time()) - KEEP_DAYS * 86400
    for folder in inbox_dir().iterdir():
        if not folder.is_dir():
            continue
        data = _read_json(folder / "mail.json", {})
        if data.get("status") == "pending":
            continue
        try:
            if folder.stat().st_mtime < limit:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def discard(mail: ReceivedMail) -> None:
    shutil.rmtree(mail.folder, ignore_errors=True)


# ----------------------------------------------------------------------------- IMAP

def _connect(settings: dict):
    host, port = settings["host"].strip(), int(settings.get("port") or 993)
    try:
        if settings.get("ssl", True):
            conn = imaplib.IMAP4_SSL(host, port, timeout=30)
        else:
            conn = imaplib.IMAP4(host, port, timeout=30)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(f"Connexion impossible à {host}:{port} ({exc}).") from exc
    try:
        conn.login(settings["address"].strip(), settings["password"])
    except imaplib.IMAP4.error as exc:
        _quiet_logout(conn)
        raise MailError(
            "Connexion refusée : adresse ou mot de passe incorrect. Beaucoup de messageries "
            "exigent un « mot de passe d'application » (pas le mot de passe habituel) et que "
            "l'accès IMAP soit activé."
        ) from exc
    typ, _ = conn.select(settings.get("folder") or "INBOX")
    if typ != "OK":
        _quiet_logout(conn)
        raise MailError(f"Dossier « {settings.get('folder') or 'INBOX'} » introuvable dans la boîte.")
    return conn


def _quiet_logout(conn) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass


def test_connection(settings: dict) -> tuple[bool, str]:
    try:
        conn = _connect(settings)
    except MailError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"Erreur inattendue : {exc}"
    try:
        typ, data = conn.uid("SEARCH", None, "UNSEEN")
        unread = len(data[0].split()) if typ == "OK" and data and data[0] else 0
    finally:
        _quiet_logout(conn)
    return True, f"Connexion réussie ({unread} message(s) non lu(s) dans la boîte)."


def _sender_address(msg) -> str:
    addresses = email.utils.getaddresses([str(msg.get("From", ""))])
    return addresses[0][1].strip().lower() if addresses else ""


def _authentication_ok(msg) -> bool:
    """Le serveur de réception note si l'expéditeur est authentique (SPF/DKIM/DMARC) dans un en-tête
    qu'un expéditeur ne peut pas truquer. Absent : on ne peut pas juger, on accepte. Présent mais
    sans aucun « pass » : l'adresse d'expéditeur est probablement usurpée, on refuse."""
    values = " ".join(str(v).lower() for v in msg.get_all("Authentication-Results", []))
    if not values.strip():
        return True
    if "dmarc=fail" in values:
        return False
    return any(token in values for token in ("dmarc=pass", "dkim=pass", "spf=pass"))


def _safe_name(name: str, fallback: str) -> str:
    name = re.sub(r"[^\w.\- ]", "_", Path(name or "").name, flags=re.UNICODE).strip(" .")
    return name[:80] or fallback


def _extract_attachments(msg, folder: Path) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    notes: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename() or ""
        ext = Path(filename).suffix.lower()
        if not ext:
            ext = (mimetypes.guess_extension(ctype) or "").lower()
            ext = {".jpe": ".jpg"}.get(ext, ext)
        if ext in UNSUPPORTED_NOTE_EXTENSIONS or ctype in ("image/heic", "image/heif"):
            notes.append(f"{filename or 'photo'} : format HEIC non pris en charge (envoie en JPEG).")
            continue
        wanted = ctype.startswith("image/") or ctype == "application/pdf" or (
            ctype == "application/octet-stream" and ext in ATTACHMENT_EXTENSIONS)
        if not wanted or ext not in ATTACHMENT_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        if len(payload) > MAX_ATTACHMENT_BYTES:
            notes.append(f"{filename or 'pièce jointe'} : trop volumineuse, ignorée.")
            continue
        if ext != ".pdf" and len(payload) < MIN_IMAGE_BYTES:
            continue  # logo de signature, pas une photo de document
        if len(files) >= MAX_ATTACHMENTS:
            notes.append(f"Plus de {MAX_ATTACHMENTS} pièces jointes : les suivantes sont ignorées.")
            break
        path = folder / f"{len(files) + 1:02d}_{_safe_name(filename, 'photo' + ext)}"
        if path.suffix.lower() != ext:
            path = path.with_name(path.name + ext)
        path.write_bytes(payload)
        files.append(path)
    return files, notes


def fetch_new_mails(settings: dict) -> FetchReport:
    """Télécharge les nouveaux messages (non lus) venant d'un expéditeur autorisé. Chaque message
    accepté est marqué lu seulement quand ses pièces jointes et son manifeste sont sur le disque :
    plus rien ne peut se perdre ensuite, même si l'app se ferme au milieu du traitement."""
    allowed = {a.lower() for a in settings["allowed_senders"]}
    report = FetchReport()
    conn = _connect(settings)
    try:
        typ, data = conn.uid("SEARCH", None, "UNSEEN")
        if typ != "OK":
            raise MailError("La recherche des nouveaux messages a échoué.")
        uids = data[0].split() if data and data[0] else []
        known = set(_known_ids())
        for uid in uids:
            try:
                _handle_message(conn, uid, allowed, known, report)
            except MailError:
                raise
            except Exception as exc:  # noqa: BLE001
                log_event(f"Message {uid.decode(errors='replace')} illisible : {exc}", "error")
                report.ignored += 1
    except (imaplib.IMAP4.error, OSError) as exc:
        raise MailError(f"Échec de la lecture de la boîte : {exc}") from exc
    finally:
        _quiet_logout(conn)
    return report


def _handle_message(conn, uid: bytes, allowed: set, known: set, report: FetchReport) -> None:
    typ, data = conn.uid("FETCH", uid, "(RFC822.SIZE)")
    size_match = re.search(rb"RFC822\.SIZE (\d+)", b" ".join(x if isinstance(x, bytes) else x[0] for x in data if x))
    if size_match and int(size_match.group(1)) > MAX_MESSAGE_BYTES:
        log_event("Message trop volumineux, ignoré.", "warn")
        _mark_seen(conn, uid)
        report.ignored += 1
        return
    typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
    raw = next((part[1] for part in data if isinstance(part, tuple)), None)
    if typ != "OK" or raw is None:
        raise MailError("Lecture d'un message impossible.")
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    sender = _sender_address(msg)
    subject = str(msg.get("Subject", "") or "")[:120]
    message_id = str(msg.get("Message-ID", "") or "").strip() or "sha1:" + hashlib.sha1(raw).hexdigest()

    if sender not in allowed or not _authentication_ok(msg):
        reason = "expéditeur non autorisé" if sender not in allowed else "expéditeur non authentifié (usurpation possible)"
        log_event(f"Message de « {sender or 'inconnu'} » ignoré : {reason}.", "warn")
        _mark_seen(conn, uid)
        report.ignored += 1
        return
    if message_id in known:
        _mark_seen(conn, uid)
        report.ignored += 1
        return

    folder = inbox_dir() / f"{datetime.now():%Y%m%d-%H%M%S}-{hashlib.sha1(message_id.encode()).hexdigest()[:6]}"
    folder.mkdir(parents=True, exist_ok=True)
    files, notes = _extract_attachments(msg, folder)
    if not files:
        shutil.rmtree(folder, ignore_errors=True)
        detail = (" " + " ".join(notes)) if notes else ""
        log_event(f"Message « {subject or 'sans objet'} » sans photo ni PDF exploitable.{detail}", "warn")
        _mark_seen(conn, uid)
        _remember_id(message_id)
        known.add(message_id)
        report.ignored += 1
        return

    mail = ReceivedMail(folder=folder, message_id=message_id, sender=sender, subject=subject,
                        files=files, notes=notes)
    mail.save_manifest("pending")
    _remember_id(message_id)
    known.add(message_id)
    _mark_seen(conn, uid)
    report.mails.append(mail)


def _mark_seen(conn, uid: bytes) -> None:
    try:
        conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    except Exception:  # noqa: BLE001
        pass  # sans conséquence : le Message-ID mémorisé évite un second traitement


# ----------------------------------------------------------------------------- traitement

@dataclass
class MailOutcome:
    status: str  # "saved" | "review" | "error"
    mail: ReceivedMail
    date: str = ""
    extraction: object | None = None
    reasons: list[str] = field(default_factory=list)


def work_order_from_extraction(extraction):
    from app.models import WorkOrder

    wo = WorkOrder(
        date=extraction.date, driver_name=extraction.driver_name, matricule=extraction.matricule,
        notes=extraction.notes, trajets=list(extraction.trajets),
        last_minute_change=bool(extraction.last_minute_change),
        repas_midi=bool(extraction.repas_midi), repas_soir=bool(extraction.repas_soir),
    )
    for name, value in {**extraction.summary, **extraction.extras}.items():
        if hasattr(wo, name):
            setattr(wo, name, float(value or 0.0))
    return wo


# Avertissements de la lecture qui ne signalent AUCUN doute (simple information affichée dans le
# formulaire). Tout autre avertissement - y compris un message inconnu ajouté plus tard - compte
# comme un doute et envoie l'OT en relecture : en cas de surprise, on relit plutôt que d'enregistrer.
_INFORMATIVE_PREFIXES = (
    "Lecture effectuée par l'IA Gemini",
    "Service édité le",  # changement de dernière minute : règle de calcul, case cochée
)


def _is_doubt(warning: str) -> bool:
    text = warning.strip()
    if any(text.startswith(prefix) for prefix in _INFORMATIVE_PREFIXES):
        return False
    if text.startswith("Indemnités de repas suggérées") and "À VÉRIFIER" not in text:
        return False  # repas calculés sans ambiguïté (oui ou non)
    return True


def review_reasons(extraction) -> list[str]:
    """Pourquoi cet OT ne doit PAS être enregistré sans relecture (liste vide = enregistrement
    automatique). Un chiffre faux enregistré en silence est pire qu'un OT à valider."""
    from app import db

    reasons: list[str] = []
    if not config.get_gemini_api_key():
        reasons.append("pas de clé Gemini : la lecture locale (OCR) n'est pas assez fiable pour un enregistrement automatique")
    if extraction is None:
        return reasons + ["lecture impossible"]
    doubts = [w.strip() for w in extraction.warnings if _is_doubt(w)]
    if doubts:
        first = doubts[0] if len(doubts[0]) <= 110 else doubts[0][:107].rstrip() + "..."
        reasons.append("la lecture a signalé : " + first)
    if not extraction.date:
        reasons.append("date de l'OT non lue")
    else:
        try:
            datetime.fromisoformat(extraction.date)
        except ValueError:
            reasons.append("date de l'OT illisible")
        else:
            if db.get_work_order_by_date(extraction.date) is not None:
                reasons.append(f"un OT existe déjà pour le {extraction.date}")
    hours = sum(float(extraction.summary.get(k) or 0.0) for k in ("tte", "tps", "ampli"))
    km = float(extraction.extras.get("km_totaux") or 0.0)
    if hours <= 0 and km <= 0:
        reasons.append("aucune heure ni aucun kilomètre lu")
    return reasons


def process_mail(mail: ReceivedMail, extract=None) -> MailOutcome:
    """Lit les pages du message. Enregistre l'OT tout seul quand la lecture est nette ; sinon
    renvoie "review" (à relire dans l'onglet Importer). Exécuté hors du fil d'affichage."""
    from app import db, ocr_engine, storage

    if extract is None:
        from app.extraction import extract_from_pages as extract

    try:
        pages = []
        for path in mail.files:
            pages.extend(ocr_engine.load_pages(path))
        if not pages:
            raise ValueError("aucune page lisible")
        extraction = extract(pages)
    except Exception as exc:  # noqa: BLE001
        return MailOutcome("error", mail, reasons=[str(exc)])
    finally:
        pages = None  # libère les images

    reasons = review_reasons(extraction)
    if reasons:
        return MailOutcome("review", mail, date=extraction.date, extraction=extraction, reasons=reasons)

    wo = work_order_from_extraction(extraction)
    wo.source_filename, wo.source_type = storage.store_source_files(mail.files, wo.date)
    db.insert_work_order(wo)
    return MailOutcome("saved", mail, date=wo.date, extraction=extraction)
