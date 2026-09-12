"""Extraction des ordres de travail via l'API Gemini (Google), en alternative à l'OCR local.

Utilisé uniquement si l'utilisateur a renseigné une clé API dans l'onglet Paramètres. Repose
uniquement sur la bibliothèque standard (urllib) pour éviter d'ajouter une dépendance lourde au
premier lancement.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request

from PIL import Image

from app.models import ExtractionResult, SUMMARY_FIELD_NAMES

MODEL_NAME = "gemini-3.5-flash-lite"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 60

PROMPT = """Tu analyses un "ordre de travail" (feuille de route) d'un chauffeur de bus/car en France.
Le document a 1 ou plusieurs pages. Sur la première page, un en-tête indique le nom du chauffeur,
son matricule (nombre) et la date du jour (ex: "Jeudi 16 JUILLET 2026"). Le corps liste les
services de la journée avec des trajets du type "LIEU A (CODE) / LIEU B (CODE)".

Sur la dernière page se trouve un tableau récapitulatif avec des colonnes (valeurs en centièmes
d'heure, ex "7,47" = 7.47) : Date, TPS, TAD, Autres Temps, TTE, HLR 50% HI, HLR 100% HI, Amplitude
(Ampli), Amp<12 HI25%, Amp 12-13 HI75%, Amp>13 HI100%, RCN 21h-6h, Repas P, Primes P,
Dim.Travail P, Férié P, TPS OC P. Ces dernières colonnes (Repas/Primes/Dim.Travail/Férié/TPS OC)
sont très souvent vides : mets alors 0.

Réponds uniquement avec les champs demandés par le schéma :
- date au format ISO AAAA-MM-JJ
- tous les nombres en notation décimale avec un point (jamais de virgule)
- "trajets" : liste des trajets tels qu'ils apparaissent dans le tableau des services, un par
  ligne rencontrée (les doublons sont normaux et voulus), chacun normalisé en
  "LIEU A / LIEU B" (les deux noms de lieux dans l'ordre alphabétique, sans les codes entre
  parenthèses ni la mention GIR/QUAI)
- "warnings" : liste courte de champs que tu n'es pas sûr d'avoir bien lus (vide si tout est clair)
"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "driver_name": {"type": "STRING"},
        "matricule": {"type": "STRING"},
        "date": {"type": "STRING"},
        "summary": {
            "type": "OBJECT",
            "properties": {name: {"type": "NUMBER"} for name in SUMMARY_FIELD_NAMES},
        },
        "trajets": {"type": "ARRAY", "items": {"type": "STRING"}},
        "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["driver_name", "matricule", "date", "summary", "trajets"],
}


class GeminiError(Exception):
    pass


def _image_to_jpeg_b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _call_gemini(api_key: str, parts: list[dict], response_schema: dict | None = None) -> dict:
    url = f"{API_BASE}/{MODEL_NAME}:generateContent?key={api_key}"
    body: dict = {"contents": [{"parts": parts}]}
    if response_schema is not None:
        body["generationConfig"] = {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in (400, 401, 403):
            raise GeminiError("Clé API refusée ou invalide.") from exc
        if exc.code == 429:
            raise GeminiError("Quota Gemini dépassé pour le moment, réessaie plus tard.") from exc
        raise GeminiError(f"Erreur Gemini ({exc.code}) : {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"Connexion à Gemini impossible : {exc.reason}") from exc


def test_api_key(api_key: str) -> tuple[bool, str]:
    """Fait un petit appel texte pour vérifier que la clé fonctionne."""
    api_key = (api_key or "").strip()
    if not api_key:
        return False, "Aucune clé saisie."
    try:
        result = _call_gemini(api_key, [{"text": "Réponds uniquement par le mot : OK"}])
    except GeminiError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"Erreur inattendue : {exc}"

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return False, "Réponse Gemini inattendue."
    return True, f"Clé valide (réponse : {text.strip()[:50]})"


def extract_from_pages(pages: list[Image.Image], api_key: str) -> ExtractionResult:
    """Envoie les pages du document à Gemini et reconstruit un ExtractionResult."""
    parts: list[dict] = [{"text": PROMPT}]
    for page in pages:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": _image_to_jpeg_b64(page),
            }
        })

    raw = _call_gemini(api_key, parts, response_schema=RESPONSE_SCHEMA)
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        payload = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiError(f"Réponse Gemini illisible : {exc}") from exc

    result = ExtractionResult()
    result.driver_name = str(payload.get("driver_name") or "").strip().upper()
    result.matricule = str(payload.get("matricule") or "").strip()
    result.date = str(payload.get("date") or "").strip()

    summary_raw = payload.get("summary") or {}
    for name in SUMMARY_FIELD_NAMES:
        value = summary_raw.get(name)
        if isinstance(value, (int, float)):
            result.summary[name] = round(float(value), 2)

    result.trajets = [str(t).strip() for t in (payload.get("trajets") or []) if str(t).strip()]
    result.warnings = [str(w) for w in (payload.get("warnings") or [])]
    result.warnings.append("Lecture effectuée par l'IA Gemini : vérifie quand même les champs.")
    return result
