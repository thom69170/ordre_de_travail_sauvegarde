"""Extraction des ordres de travail via l'API Gemini (Google), en alternative à l'OCR local.

Utilisé uniquement si l'utilisateur a renseigné une clé API dans l'onglet Paramètres. Repose
uniquement sur la bibliothèque standard (urllib) pour éviter d'ajouter une dépendance lourde au
premier lancement.
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request

from PIL import Image

from app import ocr_engine
from app.models import ExtractionResult, SUMMARY_FIELDS, SUMMARY_FIELD_NAMES, format_trajet

MODEL_NAME = "gemini-3.5-flash-lite"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 60

PROMPT = """Tu analyses un "ordre de travail" (feuille de route) d'un conducteur de bus/car en France.
Le document a 1 ou plusieurs pages. Sur la première page, un en-tête indique le nom du conducteur,
son matricule (nombre) et la date du jour (ex: "Jeudi 16 JUILLET 2026"). Le corps liste les
services de la journée, un bloc par ligne de service.

Deux types de blocs à bien distinguer :
- Les blocs "HLP" ("Haut Le Pied", conducteur seul sans passager - trajet à vide entre le dépôt
  et le début/fin d'un service, ou entre deux services) : la colonne SERVICE indique "HLP", et le
  texte du trajet utilise une FLÈCHE "->", ex: "HLP : SARCEY - DEPOT (RSYDEP) -> TARARE HAUTS DE
  TARARE (RTRHT1)". ⚠ Ce ne sont JAMAIS des trajets à extraire, quel que soit le nombre de fois où
  ils apparaissent.
- Les vrais trajets de service (les seuls à extraire) sont les blocs identifiés par un code de
  service (ex: "164TATA1520 (164LVH..."), et leur texte utilise une BARRE OBLIQUE "/", ex:
  "TARARE HAUTS DE TARARE (RTRHT1) / TARARE AQUAVAL (RTRAQ) - QUAI - GIR. 16411", sur 1 ou 2
  lignes. Le numéro de ligne de ce trajet est les chiffres au tout début du code de service,
  avant les lettres : "164TATA1520" -> ligne "164", "419SMTA0737" -> ligne "419",
  "86TSLY0600" -> ligne "86".

Ces blocs de trajet (avec code de service, séparateur "/") se répètent souvent 8 à 15 fois sur la
page, parfois avec des lignes très similaires les unes aux autres (ex: le même aller-retour répété
toute la journée) : c'est normal, et c'est justement pour ça qu'il faut être méthodique. Parcours
le tableau des services du haut vers le bas, bloc par bloc, et pour CHAQUE bloc qui a un code de
service et un trajet "LIEU / LIEU", ajoute une entrée dans "trajets" - même s'il est identique au
précédent ; pour CHAQUE bloc "HLP" (flèche "->", sans code de service), ignore-le et passe au
suivant. Ne t'arrête pas après avoir vu le même motif se répéter quelques fois : va bien jusqu'au
dernier bloc avant "FIN DE SERVICE"/"FSR". Un trajet oublié ou un HLP compté par erreur sont deux
erreurs aussi graves l'une que l'autre : compte mentalement les blocs de trajet (hors HLP) avant
de répondre et vérifie que ta liste "trajets" a bien le même nombre d'entrées.

Pour chaque page, en plus de la vue complète tu reçois aussi un agrandissement de sa moitié haute
et un de sa moitié basse (elles se chevauchent légèrement au milieu) : utilise-les pour repérer
et lire chaque bloc de service un par un sans en rater, la vue complète servant surtout à ne pas
compter un bloc en double dans la zone de chevauchement.

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
- "trajets" : liste des VRAIS trajets de service (avec code de service, séparateur "/") tels
  qu'ils apparaissent dans le tableau, un par ligne rencontrée (les doublons sont normaux et
  voulus). N'INCLUS JAMAIS les blocs "HLP" (trajet à vide sans passager, séparateur "->", sans
  code de service). Chaque entrée est un objet avec :
  - "ligne" : le numéro de ligne (voir ci-dessus), en chiffres uniquement, sans les lettres qui
    suivent ; chaîne vide si tu ne le trouves vraiment pas
  - "trajet" : "LIEU A / LIEU B" (les deux noms de lieux dans l'ordre alphabétique, sans les
    codes entre parenthèses ni la mention GIR/QUAI)
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
        "trajets": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ligne": {"type": "STRING"},
                    "trajet": {"type": "STRING"},
                },
                "required": ["ligne", "trajet"],
            },
        },
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


def _split_page_halves(page: Image.Image) -> list[Image.Image]:
    """Découpe une page en deux moitiés (haut/bas, avec un léger recouvrement) agrandies, pour
    que les lignes du tableau des services (souvent nombreuses et petites, surtout sur une photo
    de téléphone) soient plus faciles à distinguer une par une qu'en vue pleine page."""
    width, height = page.size
    overlap = int(height * 0.08)
    halves = [
        page.crop((0, 0, width, min(height, height // 2 + overlap))),
        page.crop((0, max(0, height // 2 - overlap), width, height)),
    ]
    result = []
    for half in halves:
        if half.width < 1600:
            scale = 1600 / half.width
            half = half.resize((int(half.width * scale), int(half.height * scale)), Image.LANCZOS)
        result.append(half)
    return result


def _tesseract_trajets(pages: list[Image.Image]) -> list[str] | None:
    """Récupère la liste des trajets via l'OCR local + une recherche par motif (regex), qui
    énumère mécaniquement chaque occurrence sans "se lasser" d'une répétition — contrairement à
    Gemini qui a tendance à résumer/tronquer les listes très répétitives plutôt que de toutes les
    lister. Retourne None si Tesseract est indisponible."""
    if not ocr_engine.is_available():
        return None
    from app import parser

    texts = []
    for page in pages:
        try:
            texts.append(ocr_engine.ocr_text(page, psm=6))
        except Exception:  # noqa: BLE001
            pass
    if not texts:
        return None
    return parser.extract_trajets("\n".join(texts))


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
    for i, page in enumerate(pages, start=1):
        parts.append({"text": f"Page {i} (vue complète) :"})
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": _image_to_png_b64(page),
            }
        })
        top_half, bottom_half = _split_page_halves(page)
        parts.append({"text": f"Page {i}, moitié haute agrandie :"})
        parts.append({
            "inline_data": {"mime_type": "image/png", "data": _image_to_png_b64(top_half)}
        })
        parts.append({"text": f"Page {i}, moitié basse agrandie :"})
        parts.append({
            "inline_data": {"mime_type": "image/png", "data": _image_to_png_b64(bottom_half)}
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

    gemini_trajets = []
    for entry in payload.get("trajets") or []:
        if isinstance(entry, dict):
            trajet_text = str(entry.get("trajet") or "").strip()
            ligne = re.sub(r"\D", "", str(entry.get("ligne") or ""))
        else:  # défense en profondeur si Gemini ignore le schéma et renvoie une simple chaîne
            trajet_text = str(entry).strip()
            ligne = ""
        if not trajet_text:
            continue
        gemini_trajets.append(format_trajet(ligne, _normalize_trajet(trajet_text)))
    tesseract_trajets = _tesseract_trajets(pages)
    result.warnings = [str(w) for w in (payload.get("warnings") or [])]
    if tesseract_trajets and len(tesseract_trajets) > len(gemini_trajets):
        result.trajets = tesseract_trajets
        result.warnings.append(
            f"Trajets obtenus via l'OCR local ({len(tesseract_trajets)} trouvés contre "
            f"{len(gemini_trajets)} par Gemini, qui a tendance à en manquer sur les listes très "
            "répétitives) : vérifie quand même la liste."
        )
    else:
        result.trajets = gemini_trajets
        if tesseract_trajets and len(gemini_trajets) > len(tesseract_trajets):
            # L'OCR local ne peut structurellement pas compter un trajet "HLP" (il exige un
            # séparateur "/", jamais utilisé pour un HLP), donc un surplus côté Gemini est
            # suspect - sans certitude sur la cause (HLP compté par erreur, ou autre lecture
            # incertaine), un simple écart de compte mérite une vérification.
            result.warnings.append(
                f"Gemini a trouvé plus de trajets ({len(gemini_trajets)}) que l'OCR local "
                f"({len(tesseract_trajets)}) : vérifie la liste (un trajet \"HLP\" à vide a pu "
                "être compté par erreur, ou une autre lecture incertaine)."
            )
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
