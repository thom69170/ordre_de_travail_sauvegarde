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

from app import ocr_engine
from app.models import ExtractionResult, SUMMARY_FIELDS, SUMMARY_FIELD_NAMES

MODEL_NAME = "gemini-3.5-flash-lite"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 60

PROMPT = """Tu analyses un "ordre de travail" (feuille de route) d'un chauffeur de bus/car en France.
Le document a 1 ou plusieurs pages. Sur la première page, un en-tête indique le nom du chauffeur,
son matricule (nombre) et la date du jour (ex: "Jeudi 16 JUILLET 2026"). Le corps liste les
services de la journée, un service par bloc de lignes ; parmi eux, certains blocs (souvent
identifiés par un code du type "164TATA1520 (164LVH...") contiennent un trajet du type
"LIEU A (CODE) / LIEU B (CODE)" sur 1 ou 2 lignes.

Ces blocs de trajet se répètent souvent 8 à 15 fois sur la page, parfois avec des lignes très
similaires les unes aux autres (ex: le même aller-retour répété toute la journée) : c'est normal,
et c'est justement pour ça qu'il faut être méthodique. Parcours le tableau des services du haut
vers le bas, bloc par bloc, et pour CHAQUE bloc qui contient un trajet "LIEU / LIEU", ajoute une
entrée dans "trajets" - même s'il est identique au précédent. Ne t'arrête pas après avoir vu le
même motif se répéter quelques fois : va bien jusqu'au dernier bloc avant "FIN DE SERVICE"/"FSR".
Un trajet oublié est une erreur : compte mentalement les blocs de trajet avant de répondre et
vérifie que ta liste "trajets" a bien le même nombre d'entrées.

Sur la dernière page se trouve un tableau récapitulatif avec des colonnes (valeurs en centièmes
d'heure, ex "7,47" = 7.47) : Date, TPS, TAD, Autres Temps, TTE, HLR 50% HI, HLR 100% HI, Amplitude
(Ampli), Amp<12 HI25%, Amp 12-13 HI75%, Amp>13 HI100%, RCN 21h-6h, Repas P, Primes P,
Dim.Travail P, Férié P, TPS OC P. Ces dernières colonnes (Repas/Primes/Dim.Travail/Férié/TPS OC)
sont très souvent vides : mets alors 0.

Ce tableau récapitulatif est la partie la plus importante et la plus difficile à lire (petits
chiffres, une seule ligne de données). Si une dernière image légendée "Agrandissement du tableau
récapitulatif" est fournie, sers-t'en en priorité pour lire précisément chaque chiffre (elle montre
en gros l'en-tête des colonnes juste au-dessus de la ligne de valeurs) ; sinon base-toi sur les
pages complètes. Lis chaque chiffre un par un avant de répondre, ne devine pas à partir d'une
impression générale.

Réponds uniquement avec les champs demandés par le schéma :
- date au format ISO AAAA-MM-JJ
- tous les nombres en notation décimale avec un point (jamais de virgule)
- "summary" DOIT contenir une valeur numérique pour CHACUNE des 16 colonnes, dans le même ordre
  que le tableau, même quand la case est vide (0) ou que tu n'es pas sûr (fais ta meilleure
  estimation plutôt que d'omettre le champ - un champ manquant est traité comme une erreur bien
  plus grave qu'une valeur légèrement imprécise)
- "trajets" : liste des trajets tels qu'ils apparaissent dans le tableau des services, un par
  ligne rencontrée (les doublons sont normaux et voulus), chacun normalisé en
  "LIEU A / LIEU B" (les deux noms de lieux dans l'ordre alphabétique, sans les codes entre
  parenthèses ni la mention GIR/QUAI)
- "warnings" : liste courte de champs que tu n'es pas sûr d'avoir bien lus, y compris ceux du
  tableau récapitulatif où tu as dû deviner (vide seulement si tout est clair)
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
            "required": list(SUMMARY_FIELD_NAMES),
        },
        "trajets": {"type": "ARRAY", "items": {"type": "STRING"}},
        "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["driver_name", "matricule", "date", "summary", "trajets"],
}


class GeminiError(Exception):
    pass


def _normalize_trajet(raw: str) -> str:
    """Force l'ordre alphabétique des deux lieux, quoi que Gemini ait renvoyé : sans ça, "A / B"
    et "B / A" seraient comptés comme deux trajets différents dans les statistiques."""
    parts = [p.strip(" .-") for p in raw.split("/")]
    if len(parts) != 2 or not all(parts):
        return raw.strip()
    return " / ".join(sorted(parts, key=str.upper))


def _image_to_png_b64(image: Image.Image) -> str:
    # PNG (sans perte) plutôt que JPEG : évite les artefacts de compression qui rendent les
    # petits chiffres du tableau récapitulatif encore plus difficiles à lire.
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _locate_summary_zoom(pages: list[Image.Image]) -> Image.Image | None:
    """Retrouve et agrandit le tableau récapitulatif (en-tête + ligne de données) pour aider
    Gemini à lire précisément les petits chiffres. S'appuie sur l'OCR local (Tesseract) pour
    localiser la zone : un pourcentage fixe serait trop peu fiable sur une photo cadrée
    différemment d'une fois sur l'autre. Retourne None si Tesseract est indisponible ou si la
    zone n'a pas pu être repérée (l'extraction se fait alors seulement sur les pages complètes)."""
    if not ocr_engine.is_available():
        return None
    from app import parser

    for page in reversed(pages):  # le tableau est presque toujours sur la dernière page
        try:
            region = parser.find_summary_table_region(page)
        except Exception:  # noqa: BLE001
            region = None
        if region is not None:
            if region.width < 2200:
                scale = 2200 / region.width
                region = region.resize(
                    (int(region.width * scale), int(region.height * scale)), Image.LANCZOS
                )
            return region
    return None


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
                "mime_type": "image/png",
                "data": _image_to_png_b64(page),
            }
        })
    zoom = _locate_summary_zoom(pages)
    zoom_found = zoom is not None
    if zoom is not None:
        parts.append({"text": "Agrandissement du tableau récapitulatif (en-tête + ligne de données) :"})
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": _image_to_png_b64(zoom),
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
    missing_fields = []
    for name, label in SUMMARY_FIELDS:
        value = summary_raw.get(name)
        if isinstance(value, (int, float)):
            result.summary[name] = round(float(value), 2)
        else:
            missing_fields.append(label)

    result.trajets = [
        _normalize_trajet(str(t)) for t in (payload.get("trajets") or []) if str(t).strip()
    ]
    result.warnings = [str(w) for w in (payload.get("warnings") or [])]
    if missing_fields:
        result.warnings.append(
            "Gemini n'a pas renvoyé de valeur pour : " + ", ".join(missing_fields)
            + " (mis à 0 par défaut, à vérifier)."
        )
    if not zoom_found:
        result.warnings.append(
            "Agrandissement automatique du tableau récapitulatif non trouvé sur ce document "
            "(l'OCR local n'a pas repéré l'en-tête TPS/TAD/TTE...) : Gemini a lu la page entière, "
            "vérifie particulièrement bien le tableau récapitulatif."
        )
    result.warnings.append("Lecture effectuée par l'IA Gemini : vérifie quand même les champs.")
    return result
