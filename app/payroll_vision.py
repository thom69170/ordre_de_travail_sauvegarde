"""Lecture d'un bulletin de paie ou d'une feuille de prépaie PHOTOGRAPHIÉS (ou scannés en image) :
tout le monde n'a pas ces documents en PDF numérique.

Un PDF numérique est lu localement, sans IA, à partir de son texte (bulletin_parser.py,
payslip_parser.py). Une photo n'a pas de texte : l'IA Gemini lit l'image, puis on reconstruit les
MÊMES structures (BulletinData / PayslipData) que pour un PDF, de sorte que tout le reste de
l'application (comparaison bulletin / prépaie, contrôle de paie, Heures sup.) fonctionne à
l'identique.

Fiabilité des chiffres - deux garde-fous :
- le corps d'un bulletin est imprimé SANS virgule ("15167 134010 203253" pour 151,67 x 13,4010 =
  2 032,53) : l'IA recopie les chiffres tels quels et c'est ce code qui place la virgule d'après la
  colonne (2, 4, 2 puis 2 décimales), exactement comme pour le PDF ;
- les recoupements du PDF s'appliquent aussi (la somme des éléments de revenu brut doit donner le
  salaire brut, le net à payer doit correspondre au net payé) et lèvent un avertissement sinon.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from PIL import Image

from app import config, diagnostics, gemini_engine as ge
from app.bulletin_parser import (
    IMAGE_SUFFIXES,
    SECTION_AUTRES,
    SECTION_BRUT,
    SECTION_COTISATIONS,
    BulletinData,
    BulletinError,
    BulletinLine,
    finalize_bulletin,
    normalize,
)
from app.payslip_parser import (
    _HS25_LABEL,
    _HS50_LABEL,
    _REPOS_DIFFERE_LABEL,
    PayslipData,
    _find_value,
)

KIND_BULLETIN = "bulletin"
KIND_PREPAIE = "prepaie"

MAX_SIDE = 2600  # une photo de téléphone fait ~4000 px : inutile (et lourd) de l'envoyer entière
PHOTO_NOTE = "Document lu depuis une photo par l'IA Gemini : vérifie les chiffres sur l'original."

# Décimales de chaque colonne du corps d'un bulletin : Quantité/Base, Valeur unitaire/Taux,
# Montant/Part salarié, Part employeur (voir bulletin_parser).
_DECIMALS = (2, 4, 2, 2)


class PhotoError(Exception):
    """Photo illisible, clé Gemini absente ou erreur Gemini, avec un message lisible."""


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def available() -> bool:
    return bool(config.get_gemini_api_key())


# ----------------------------------------------------------------------------- consignes

_CLASSIFY_PROMPT = """Tu regardes la photo d'un document de paie français. Réponds avec son type :
- "bulletin" : un BULLETIN DE PAIE (titre « BULLETIN DE PAIE », tableaux « Eléments de revenu brut »,
  « Cotisations et contributions sociales », « Autres éléments de paie », net payé) ;
- "prepaie" : une FEUILLE DE PREPAIE / rapport d'activité du conducteur (en-tête « RNA », titre « Rapport
  d'activité pour la période du ... au ... », tableau jour par jour, blocs « Compteurs » et
  « Récapitulatif mensuel ») ;
- "autre" : tout le reste (ordre de travail, facture, photo sans rapport...).
"""

_CLASSIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {"type": {"type": "STRING", "enum": ["bulletin", "prepaie", "autre"]}},
    "required": ["type"],
}

_BULLETIN_PROMPT = """Tu lis la photo d'UNE PAGE d'un BULLETIN DE PAIE français (qui en compte deux : la page 1 porte les trois
tableaux, la page 2 la fin du tableau « Autres éléments de paie » et le pied de page).
Recopie ce qui est imprimé, sans rien inventer ni calculer. Information absente de CETTE page ou illisible :
chaîne vide / liste vide.

EN-TÊTE (présent sur les deux pages) : period_start / period_end = la période « Salaire du JJ/MM/AAAA au
JJ/MM/AAAA », au format AAAA-MM-JJ.

TABLEAUX : lis UNIQUEMENT les deux tableaux suivants (ignore le tableau « Cotisations et contributions
sociales » et le tableau « Date / Motif » à droite). Une page peut n'en contenir qu'une partie, voire rien :
- section "brut" : « Eléments de revenu brut », de SALAIRE DE BASE jusqu'à la ligne SALAIRE BRUT incluse. Ce tableau
  n'existe QUE sur la page 1 : sur la page 2 il n'y a pas de section "brut" (n'invente rien) ;
- section "autres" : « Autres éléments de paie », de sa première ligne jusqu'à sa dernière (NET A PAYER AVANT PAS
  et lignes de prélèvement à la source comprises).
Le bloc d'en-tête (COEFFICIENT, CLASSIFICATION, MENSUALISATION, TAUX HORAIRE, ANCIENNETÉ...) n'est PAS un
tableau de lignes : ne le transcris jamais comme une ligne. Une ligne ne compte que si elle est dans l'un des
deux tableaux ci-dessus et qu'elle a son libellé sur la même ligne horizontale.
Pour chaque ligne de ces tableaux qui porte au moins un nombre, de haut en bas :
- label : le libellé de la ligne, SANS le marqueur « RAP » de la colonne de gauche ;
- numbers : la liste, de GAUCHE À DROITE, des nombres imprimés sur CETTE ligne (à la même hauteur que le libellé).
  Suis bien la ligne horizontalement : un nombre appartient au libellé qui est exactement à sa hauteur, jamais à
  la ligne du dessus ou du dessous.
IMPORTANT : dans ces tableaux les nombres sont imprimés SANS virgule (ex. « 15167 », « 134010 », « 203253 »).
Recopie les chiffres EXACTEMENT comme imprimés, n'ajoute jamais de virgule ni de point, garde le signe « - » des
nombres négatifs. Une ligne a typiquement 3 nombres (quantité, valeur unitaire, montant), ou 1 seul (montant).
Un chiffre qui fait partie du libellé (ex. « PRIME URBAIN 5 TRAJETS + ») reste dans le label.

PIED DE PAGE (en bas de la page, surtout page 2) :
- payment_date (AAAA-MM-JJ) et payment_mode (ex. VIREMENT) : ligne « Paiement effectué le JJ/MM/AAAA par ... ».
- net_paye : le montant du cadre « Net payé en euros », tel qu'imprimé (avec sa virgule, ex. « 2233,44 »).
- cumuls : si le bloc « DU MOIS / CUMULE » est lisible, des paires label/value (value recopiée telle
  qu'imprimée, avec sa virgule) pour ces libellés exacts : « Brut fiscal (mois) », « Brut fiscal (cumul annuel) »,
  « Cotisations salariales (mois) », « Cotisations salariales (cumul annuel) », « Brut abattu (mois) »,
  « Brut abattu (cumul annuel) », « Cotisations patronales (mois) », « Cotisations patronales (cumul annuel) »,
  « Net fiscal (mois) », « Net fiscal (cumul annuel) », « Heures déclarées (mois) »,
  « Heures déclarées (cumul annuel) », « Plafond (mois) », « Plafond (cumul annuel) »,
  « Avantage en nature (mois) », « Avantage en nature (cumul annuel) ».
Chaîne ou liste vide pour ce qui n'est pas sur cette page.

rotation_degrees : 0 si le document est à l'endroit ; 180 s'il est tête en bas.
"""

_BULLETIN_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "period_start": {"type": "STRING"},
        "period_end": {"type": "STRING"},
        "payment_date": {"type": "STRING"},
        "payment_mode": {"type": "STRING"},
        "net_paye": {"type": "STRING"},
        "cumuls": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"label": {"type": "STRING"}, "value": {"type": "STRING"}},
                "required": ["label", "value"],
            },
        },
        "lines": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "section": {"type": "STRING", "enum": ["brut", "autres"]},
                    "label": {"type": "STRING"},
                    "numbers": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["section", "label", "numbers"],
            },
        },
        "rotation_degrees": {"type": "INTEGER"},
    },
    "required": ["period_start", "period_end", "payment_date", "payment_mode", "net_paye", "cumuls",
                 "lines", "rotation_degrees"],
}

_PREPAIE_PROMPT = """Tu lis la photo d'une FEUILLE DE PREPAIE de conducteur (rapport d'activité « RNA », une page).
Recopie ce qui est imprimé, sans rien inventer ni calculer.

- period_start / period_end : la période du titre « Rapport d'activité pour la période du JJ/MM/AAAA au
  JJ/MM/AAAA », au format AAAA-MM-JJ (PAS les sous-périodes hebdomadaires du tableau).
- recap : TOUTES les lignes du cadre « Récapitulatif mensuel » (en bas à droite), dans l'ordre, une paire
  label/value par ligne (label exact imprimé, ex. « Jours travaillés », « Heures indemnisées », « TTE »,
  « HS 150% », « Repas unique Prépaye », « Prime urbain +5 trajets Plan » ; value = le nombre imprimé, avec
  son point décimal).
- compteurs : TOUTES les lignes du bloc « Compteurs » (en bas à gauche), même format (ex. « Cumul annuel HS
  25% », « Cumul annuel HS 50% », « Cumul TTE annuel », « Solde repos différés »).
- Si un des deux blocs est absent de la page ou illisible, liste vide pour ce bloc.
- Ignore le tableau jour par jour du haut de la page.
- rotation_degrees : 0 si le document est à l'endroit ; 180 s'il est tête en bas.
"""

_PREPAIE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "period_start": {"type": "STRING"},
        "period_end": {"type": "STRING"},
        "recap": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"label": {"type": "STRING"}, "value": {"type": "NUMBER"}},
                "required": ["label", "value"],
            },
        },
        "compteurs": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"label": {"type": "STRING"}, "value": {"type": "NUMBER"}},
                "required": ["label", "value"],
            },
        },
        "rotation_degrees": {"type": "INTEGER"},
    },
    "required": ["period_start", "period_end", "recap", "compteurs", "rotation_degrees"],
}


# ----------------------------------------------------------------------------- appel Gemini

def _api_key() -> str:
    key = config.get_gemini_api_key()
    if not key:
        raise PhotoError(
            "la lecture d'une photo de bulletin ou de feuille de prépaie nécessite une clé Gemini "
            "(onglet Paramètres)."
        )
    return key


def skew_angle(page: Image.Image, limit: float = 6.0) -> float:
    """Inclinaison de la page en degrés (0 = droite), cherchée en maximisant le contraste des lignes
    de texte : sur une page bien droite, la luminosité moyenne de chaque ligne de pixels alterne
    nettement entre texte et interligne ; inclinée, ce contraste s'écrase. Indispensable pour un
    tableau large comme un bulletin : avec 2° d'inclinaison, les nombres de la colonne de droite se
    retrouvent presque une ligne plus bas que leur libellé et l'IA les rattache à la ligne suivante."""
    gray = page.convert("L")
    gray.thumbnail((800, 800))

    def score(angle: float) -> float:
        rotated = gray.rotate(angle, resample=Image.BILINEAR, fillcolor=128)
        rows = rotated.resize((1, rotated.height), Image.BOX).tobytes()
        return ge._roughness(rows)

    best_angle, best_score = 0.0, score(0.0)
    angle = -limit
    while angle <= limit + 1e-9:  # balayage grossier puis affinage
        value = score(angle)
        if value > best_score:
            best_angle, best_score = angle, value
        angle += 0.5
    for step in (-0.4, -0.3, -0.2, -0.1, 0.1, 0.2, 0.3, 0.4):
        value = score(best_angle + step)
        if value > best_score:
            best_angle, best_score = best_angle + step, value
    # Un gain négligeable = page déjà droite (ou sans lignes de texte nettes) : on ne touche à rien.
    return best_angle if best_score > score(0.0) * 1.02 else 0.0


def _load_page(path: Path) -> Image.Image:
    from app import ocr_engine

    try:
        pages = ocr_engine.load_pages(path)
    except Exception as exc:  # noqa: BLE001
        raise PhotoError(f"image illisible ({exc})") from exc
    page = pages[0]
    if ge._is_sideways(page):  # photo couchée : redressée d'un quart de tour (voir gemini_engine)
        page = page.rotate(-90, expand=True)
    if max(page.size) > MAX_SIDE:
        page = page.copy()
        page.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    angle = skew_angle(page)
    if abs(angle) >= 0.3:
        page = page.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    return page


def _ask(parts: list[dict], schema: dict, key: str) -> dict:
    try:
        raw = ge._call_gemini(key, parts, response_schema=schema)
        return json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
    except ge.GeminiError as exc:
        raise PhotoError(str(exc)) from exc
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise PhotoError(f"réponse de l'IA illisible ({exc})") from exc


def _read(path: Path, prompt: str, schema: dict) -> tuple[dict, bool]:
    """Lit la page avec le schéma donné ; une photo tête en bas est retournée puis relue. Retourne
    (réponse, orientation_incertaine)."""
    key = _api_key()
    page = _load_page(path)
    payload = _ask([{"text": prompt}] + ge._page_parts([page]), schema, key)
    if payload.get("rotation_degrees") != 180:
        return payload, False
    try:
        second = _ask([{"text": prompt}] + ge._page_parts([page.rotate(180)]), schema, key)
    except PhotoError:
        return payload, True
    return second, second.get("rotation_degrees") == 180


def classify_photo(path: Path) -> str | None:
    """"bulletin", "prepaie" ou None (autre chose). Lève PhotoError si l'IA est inaccessible."""
    key = _api_key()
    page = _load_page(path)
    small = page.copy()
    small.thumbnail((1400, 1400), Image.LANCZOS)
    parts = [{"text": _CLASSIFY_PROMPT},
             {"inline_data": {"mime_type": "image/png", "data": ge._image_to_png_b64(small)}}]
    kind = _ask(parts, _CLASSIFY_SCHEMA, key).get("type")
    diagnostics.record("photo_classify", file=path.name, size=path.stat().st_size, page_px=list(page.size),
                       result=kind)
    return kind if kind in (KIND_BULLETIN, KIND_PREPAIE) else None


# ----------------------------------------------------------------------------- bulletin

def raw_number(text: str, decimals: int) -> float | None:
    """Nombre recopié d'un bulletin : sans virgule dans le corps ("203253" -> 2032,53 pour 2
    décimales), avec virgule dans le pied de page. None si vide ou illisible."""
    s = (text or "").strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    negative = s[0] in "-−–"
    s = s.lstrip("-−–+")
    if not s:
        return None
    try:
        if "," in s or "." in s:
            value = float(s.replace(",", "."))
        elif s.isdigit():
            value = int(s) / 10 ** decimals
        else:
            return None
    except ValueError:
        return None
    return -value if negative else value


def _columns_for(numbers: list[float | None]) -> tuple[float | None, float | None, float | None]:
    """Range les nombres d'une ligne de revenu brut / autres éléments dans (quantité, valeur
    unitaire, montant) d'après leur NOMBRE, sans deviner la colonne sur l'image : 3 nombres = quantité,
    valeur unitaire, montant ; 2 = quantité et montant ; 1 = montant (formes constatées sur 32 bulletins
    réels, voir le contrôle q x r = montant plus bas)."""
    if len(numbers) >= 3:
        return numbers[0], numbers[1], numbers[2]
    if len(numbers) == 2:
        return numbers[0], None, numbers[1]
    return None, None, numbers[0]


def _coherent(quantity: float | None, rate: float | None, amount: float | None) -> bool:
    """quantité x valeur unitaire = montant (ou /100 pour un pourcentage), à l'arrondi près."""
    if quantity is None or rate is None or amount is None:
        return True
    return any(abs(quantity * rate / divisor - amount) <= 0.011 + 0.0002 * abs(amount) for divisor in (1, 100))


def _used_patterns() -> list[re.Pattern]:
    from app.payroll_check import _BULLETIN_PAIRS

    return [re.compile(pattern) for _label, pattern, _recap, _unit in _BULLETIN_PAIRS]


def bulletin_from_payload(payload: dict) -> BulletinData:
    data = BulletinData(
        period_start=(payload.get("period_start") or "").strip(),
        period_end=(payload.get("period_end") or "").strip(),
    )
    data.payment_date = (payload.get("payment_date") or "").strip()
    data.payment_mode = (payload.get("payment_mode") or "").strip()
    data.net_paye = raw_number(payload.get("net_paye", ""), 2) or 0.0
    for entry in payload.get("cumuls") or []:
        value = raw_number(entry.get("value", ""), 2)
        label = str(entry.get("label", "")).strip()
        if label and value is not None:
            data.cumuls[label] = value
    data.net_fiscal = data.cumuls.get("Net fiscal (mois)", 0.0)
    data.heures = data.cumuls.get("Heures déclarées (mois)", 0.0)
    sections = {"brut": SECTION_BRUT, "autres": SECTION_AUTRES}
    suspect: list[str] = []
    for entry in payload.get("lines") or []:
        label = " ".join(str(entry.get("label", "")).split()).lstrip("> ").strip()
        section = sections.get(entry.get("section"))
        raw = [str(n) for n in entry.get("numbers") or []]
        # Colonnes à 2 / 4 / 2 décimales selon le rang : quantité, valeur unitaire, montant.
        decimals = (2, 4, 2) if len(raw) >= 3 else ((2, 2) if len(raw) == 2 else (2,))
        numbers = [raw_number(text, d) for text, d in zip(raw, decimals)]
        numbers = [n for n in numbers if n is not None]
        if not label or section is None or not numbers:
            continue
        quantity, rate, amount = _columns_for(numbers)
        # Le contrôle q x r = montant n'est fiable que sur les lignes dont la comparaison utilise la
        # quantité (heures, primes, repas) ; d'autres lignes (retenues de congés...) ne l'obéissent pas.
        if any(regex.search(normalize(label)) for regex in _used_patterns()) and not _coherent(quantity, rate, amount):
            suspect.append(label)
        data.lines.append(BulletinLine(section=section, label=label, quantity=quantity, rate=rate, amount=amount))
    if suspect:
        data.warnings.append(
            "Quantité × valeur unitaire ≠ montant pour : " + ", ".join(suspect[:4])
            + (" ..." if len(suspect) > 4 else "")
            + " : à vérifier sur l'original (ligne peut-être mal lue ; l'écart est parfois normal quand "
              "le tarif change en cours de mois)."
        )
    return data


def _read_bulletin(path: Path) -> BulletinData:
    """Lit UNE page. Les recoupements (somme du brut, net payé) ne se font qu'une fois les pages du
    bulletin réunies : voir assemble_bulletin_photos."""
    payload, uncertain = _read(path, _BULLETIN_PROMPT, _BULLETIN_SCHEMA)
    data = bulletin_from_payload(payload)
    diagnostics.record(
        "photo_read_bulletin", file=path.name, orientation_uncertain=uncertain, payload=payload,
        parsed={"period": data.period_start, "lines": len(data.lines),
                "brut": sum(1 for l in data.lines if l.section == SECTION_BRUT),
                "autres": sum(1 for l in data.lines if l.section == SECTION_AUTRES), "net_paye": data.net_paye,
                "payment_date": data.payment_date, "cumuls": len(data.cumuls), "page_one": _is_page_one(data)},
        warnings=data.warnings,
    )
    if uncertain:
        data.warnings.insert(0, "Photo de travers : son orientation n'a pas pu être corrigée avec "
                                "certitude, vérifie bien les chiffres (ou reprends la photo à l'endroit).")
    data.warnings.append(PHOTO_NOTE)
    return data


# ----------------------------------------------------------------------------- feuille de prépaie

def prepaie_from_payload(payload: dict) -> PayslipData:
    result = PayslipData(
        period_start=(payload.get("period_start") or "").strip(),
        period_end=(payload.get("period_end") or "").strip(),
    )
    for name in ("recap", "compteurs"):
        block: dict[str, float] = {}
        for entry in payload.get(name) or []:
            label = " ".join(str(entry.get("label", "")).split())
            try:
                value = float(entry.get("value"))
            except (TypeError, ValueError):
                continue
            if label and label not in block:
                block[label] = value
        setattr(result, name, block)
    result.hs_25 = _find_value(result.recap, _HS25_LABEL)
    result.hs_50 = _find_value(result.recap, _HS50_LABEL)
    result.cumul_hs_25 = _find_value(result.compteurs, _HS25_LABEL)
    result.cumul_hs_50 = _find_value(result.compteurs, _HS50_LABEL)
    result.repos_differe = _find_value(result.compteurs, _REPOS_DIFFERE_LABEL)
    return result


def _read_prepaie(path: Path) -> PayslipData:
    payload, uncertain = _read(path, _PREPAIE_PROMPT, _PREPAIE_SCHEMA)
    result = prepaie_from_payload(payload)
    diagnostics.record("photo_read_prepaie", file=path.name, orientation_uncertain=uncertain, payload=payload,
                       parsed={"period": result.period_start, "recap": len(result.recap),
                               "compteurs": len(result.compteurs)})
    if not result.period_start:
        result.warnings.append("Période (dates) non détectée sur la photo.")
    if not result.recap or not result.compteurs:
        result.warnings.append(
            "« Récapitulatif mensuel » ou « Compteurs » non lus sur la photo : vérifie que le bas de "
            "la feuille est bien visible et net."
        )
    if uncertain:
        result.warnings.insert(0, "Photo de travers : son orientation n'a pas pu être corrigée avec "
                                  "certitude, vérifie bien les chiffres (ou reprends la photo à l'endroit).")
    result.warnings.append(PHOTO_NOTE)
    return result


# ----------------------------------------------------------------------------- mémoire des lectures

# Une photo est lue une seule fois (quelques secondes, appel à l'IA) même si plusieurs étapes en ont
# besoin (reconnaissance du type, puis lecture) : le résultat est gardé tant que le fichier ne change pas.
_CACHE: dict[tuple, tuple[str, object]] = {}
_LOCK = threading.Lock()


def _key(path: Path) -> tuple:
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


def prefetch(path: Path) -> str | None:
    """Reconnaît puis lit la photo et garde le résultat (ou l'erreur) en mémoire. À appeler dans un
    fil d'arrière-plan : c'est la partie lente. Retourne le type reconnu."""
    key = _key(path)
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached[0] if cached[0] in (KIND_BULLETIN, KIND_PREPAIE) else None
    # Une erreur (quota, réseau, photo illisible) n'est pas gardée : un nouvel essai refait l'appel.
    diagnostics.record("photo_start", file=path.name, copy=diagnostics.keep_photo(path))
    try:
        kind = classify_photo(path)
    except PhotoError as exc:
        diagnostics.record("photo_error", file=path.name, error=str(exc))
        raise
    try:
        if kind == KIND_BULLETIN:
            entry = (kind, _read_bulletin(path))
        elif kind == KIND_PREPAIE:
            entry = (kind, _read_prepaie(path))
        else:
            entry = ("autre", None)
    except PhotoError as exc:
        diagnostics.record("photo_error", file=path.name, kind=kind, error=str(exc))
        raise
    with _LOCK:
        _CACHE[key] = entry
    return entry[0] if entry[0] in (KIND_BULLETIN, KIND_PREPAIE) else None


def _cached(path: Path, kind: str):
    with _LOCK:
        entry = _CACHE.get(_key(path))
    return entry[1] if entry is not None and entry[0] == kind else None


def cached_kind(path: Path) -> str | None:
    """Type d'une photo déjà reconnue (voir prefetch), sans appeler l'IA."""
    try:
        with _LOCK:
            entry = _CACHE.get(_key(path))
    except OSError:
        return None
    return entry[0] if entry is not None and entry[0] in (KIND_BULLETIN, KIND_PREPAIE) else None


def read_bulletin_photo(path: Path) -> BulletinData:
    data = _cached(path, KIND_BULLETIN)
    if data is not None:
        return data
    try:
        return _read_bulletin(path)
    except PhotoError as exc:
        raise BulletinError(str(exc)) from exc


def read_prepaie_photo(path: Path) -> PayslipData:
    data = _cached(path, KIND_PREPAIE)
    if data is not None:
        return data
    try:
        return _read_prepaie(path)
    except PhotoError as exc:
        raise RuntimeError(str(exc)) from exc


# ----------------------------------------------------------------------------- bulletin sur deux pages

def _is_page_one(data: BulletinData) -> bool:
    """La page 1 est celle dont le tableau des revenus bruts va jusqu'à la ligne SALAIRE BRUT."""
    return any(line.section == SECTION_BRUT and normalize(line.label) == "salaire brut" for line in data.lines)


def _page_rank(data: BulletinData) -> int:
    """0 pour la page 1 (elle porte les revenus bruts), 1 pour la page 2 (pied de page)."""
    return 0 if _is_page_one(data) or (any(line.section == SECTION_BRUT for line in data.lines)) else 1


def _merge_pages(group: list[tuple[Path, BulletinData]]) -> BulletinData:
    group = sorted(group, key=lambda item: _page_rank(item[1]))
    merged = BulletinData(period_start=group[0][1].period_start, period_end=group[0][1].period_end)
    seen: set[tuple] = set()
    has_page_one = any(_is_page_one(page) for _path, page in group)
    for index, (_path, page) in enumerate(group):
        own: list[tuple] = []
        for line in page.lines:
            if has_page_one and not _is_page_one(page) and line.section == SECTION_BRUT:
                continue  # lignes de « revenu brut » inventées sur une page qui n'a pas ce tableau
            key = (line.section, normalize(line.label), line.quantity, line.rate, line.amount)
            if key in seen and index > 0:
                continue  # même ligne sur deux photos (page photographiée deux fois) : gardée une fois
            own.append(key)
            merged.lines.append(line)
        seen.update(own)
        merged.payment_date = merged.payment_date or page.payment_date
        merged.payment_mode = merged.payment_mode or page.payment_mode
        merged.net_paye = merged.net_paye or page.net_paye
        for label, value in page.cumuls.items():
            merged.cumuls.setdefault(label, value)
        merged.absences += [a for a in page.absences if a not in merged.absences]
        merged.period_end = merged.period_end or page.period_end
        merged.warnings += [w for w in page.warnings if w not in merged.warnings]
    merged.net_fiscal = merged.cumuls.get("Net fiscal (mois)", 0.0)
    merged.heures = merged.cumuls.get("Heures déclarées (mois)", 0.0)
    return merged


def combine_to_pdf(paths: list[Path]) -> Path:
    """Les photos d'un même bulletin réunies en un seul PDF (le bulletin garde ainsi un seul fichier
    source, comme un OT sur plusieurs pages). Fichier temporaire, à supprimer après l'import."""
    import tempfile

    from app import ocr_engine

    images: list[Image.Image] = []
    for path in paths:
        images.extend(ocr_engine.load_pages(path)[:1])
    folder = Path(tempfile.mkdtemp(prefix="ordres_bulletin_"))
    target = folder / "bulletin_assemble.pdf"
    first, rest = images[0].convert("RGB"), [img.convert("RGB") for img in images[1:]]
    first.save(target, "PDF", save_all=True, append_images=rest, resolution=150.0)
    return target


def _finish_bulletin(data: BulletinData) -> tuple[bool, bool]:
    """Recoupements du bulletin (réuni) et avertissements sur les pages manquantes. Retourne
    (a_la_page_1, a_la_page_2)."""
    finalize_bulletin(data)
    has_brut = any(line.section == SECTION_BRUT for line in data.lines)
    has_footer = bool(data.cumuls) or bool(data.payment_date)
    if not has_brut:
        data.warnings.append("La page 1 du bulletin (revenus bruts) n'a pas été photographiée.")
    if any(w.startswith(("La somme des éléments", "Le net à payer lu")) for w in data.warnings):
        data.warnings.append(
            "Photo probablement de travers ou prise de biais : reprends-la bien à plat, de face et en "
            "entier, avec un bon éclairage (sans reflet ni ombre)."
        )
    elif has_brut and not has_footer:
        data.warnings.append(
            "La page 2 du bulletin n'a pas été photographiée : net payé, cumuls et prélèvement à la "
            "source ne sont pas relevés (le net est calculé depuis le tableau quand c'est possible). "
            "Tu peux l'envoyer plus tard : elle sera ajoutée à ce bulletin."
        )
    return has_brut, has_footer


def bulletin_to_data(bulletin) -> BulletinData:
    """Un bulletin déjà enregistré, remis sous la forme d'une lecture (pour y ajouter une page)."""
    try:
        details = json.loads(bulletin.details_json) if bulletin.details_json else {}
    except ValueError:
        details = {}
    data = BulletinData(
        period_start=bulletin.period_start, period_end=bulletin.period_end,
        payment_date=bulletin.payment_date, payment_mode=details.get("payment_mode", ""),
        net_paye=bulletin.net_paye,
    )
    for entry in details.get("lines") or []:
        try:
            data.lines.append(BulletinLine(**entry))
        except TypeError:
            continue
    data.cumuls = dict(details.get("cumuls") or {})
    data.absences = list(details.get("absences") or [])
    data.net_fiscal = data.cumuls.get("Net fiscal (mois)", 0.0)
    data.heures = data.cumuls.get("Heures déclarées (mois)", 0.0)
    return data


_STALE_WARNINGS = ("La page ", "La somme des éléments", "Le net à payer lu", "Montant net payé non trouvé",
                   "Ligne « SALAIRE BRUT » non trouvée", "Photo probablement", "Aucune ligne")


def merge_with_existing(existing, path: Path, data: BulletinData):
    """Une page photographiée plus tard complète un bulletin déjà importé de la même période (page 2
    envoyée après la page 1, ou l'inverse) au lieu de le remplacer. Retourne (fichier, bulletin_complet)
    ou None si les deux ne sont pas complémentaires (alors : remplacement habituel, avec question)."""
    from app import storage

    if not (is_image(path) or path.name == "bulletin_assemble.pdf"):
        return None
    old = bulletin_to_data(existing)

    def has_brut(d: BulletinData) -> bool:
        return any(line.section == SECTION_BRUT for line in d.lines)

    def has_footer(d: BulletinData) -> bool:
        return bool(d.cumuls) or bool(d.payment_date)

    complementary = (has_brut(old) and not has_footer(old) and not has_brut(data) and has_footer(data)) or (
        has_footer(old) and not has_brut(old) and has_brut(data) and not has_footer(data))
    old_file = storage.resolve_bulletin_path(existing.source_filename) if existing.source_filename else None
    if not complementary or old_file is None or not old_file.exists():
        return None
    if old_file.suffix.lower() == ".pdf":
        return None  # PDF (numérique ou déjà réuni) : pas une photo seule, on ne le recompose pas
    ordered = [(old_file, old), (path, data)] if has_brut(old) else [(path, data), (old_file, old)]
    merged = _merge_pages(ordered)
    merged.warnings = [w for w in merged.warnings if not w.startswith(_STALE_WARNINGS)]
    _finish_bulletin(merged)
    combined = combine_to_pdf([p for p, _d in ordered])
    diagnostics.record("bulletin_completed", period=data.period_start, existing_file=existing.source_filename,
                       new_file=path.name, merged_lines=len(merged.lines))
    return combined, merged


def assemble_bulletin_photos(items: list[tuple[Path, BulletinData]]) -> list[tuple[Path, BulletinData]]:
    """Réunit les photos d'un même bulletin (même période : page 1 + page 2) en un seul bulletin,
    puis applique les recoupements du bulletin complet. Les PDF (déjà complets) passent tels quels.
    Un bulletin dont il manque une page est importé quand même, avec un avertissement."""
    result = [(p, d) for p, d in items if not is_image(p)]
    groups: dict[str, list[tuple[Path, BulletinData]]] = {}
    for path, data in items:
        if is_image(path):
            groups.setdefault(data.period_start or f"?{path}", []).append((path, data))
    for _period, group in groups.items():
        data = _merge_pages(group) if len(group) > 1 else group[0][1]
        path = group[0][0] if len(group) == 1 else combine_to_pdf(
            [p for p, _d in sorted(group, key=lambda item: _page_rank(item[1]))]
        )
        has_brut, has_footer = _finish_bulletin(data)
        diagnostics.record(
            "bulletin_assemble", period=data.period_start, photos=[p.name for p, _d in group],
            pages=[{"file": p.name, "page_one": _is_page_one(d),
                    "brut": sum(1 for l in d.lines if l.section == SECTION_BRUT),
                    "lines": len(d.lines), "period": d.period_start} for p, d in group],
            merged_lines=len(data.lines), brut_total=data.brut, net_paye=data.net_paye,
            has_page_one=has_brut, has_footer=has_footer, warnings=data.warnings,
        )
        result.append((path, data))
    return result
