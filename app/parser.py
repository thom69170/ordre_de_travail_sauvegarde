"""Extraction des informations utiles depuis le texte/les images OCRisées.

Le document (ordre de travail TD RAI Arnas) a une mise en page fixe mais est scanné/
photographié, donc l'OCR n'est jamais parfait. Ce module fait de son mieux pour
pré-remplir les champs ; l'utilisateur valide et corrige ensuite dans l'interface.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from PIL import Image

from app import ocr_engine
from app.models import ExtractionResult, SUMMARY_FIELDS

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

FRENCH_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}

HEADER_KEYWORDS = {"TPS", "TAD", "TTE", "AMPLI", "RCN"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def parse_header(text_page1: str) -> tuple[str, str, str, list[str]]:
    """Cherche 'NOM PRENOM  MATRICULE  Jeudi 16 JUILLET 2026' dans le texte OCR de la page 1."""
    warnings: list[str] = []
    weekday_alt = "|".join(WEEKDAYS)
    pattern = re.compile(
        r"([A-ZÀ-Ÿ][A-ZÀ-Ÿ' \-]{2,40}?)\s+(\d{3,6})\s+"
        rf"((?:{weekday_alt})\.?\s+\d{{1,2}}(?:er)?\s+[A-Za-zÀ-ÿ]+\s+\d{{4}})",
        re.IGNORECASE,
    )
    m = pattern.search(text_page1)
    if not m:
        warnings.append("En-tête (nom / date) non détecté automatiquement.")
        return "", "", "", warnings

    driver_name = " ".join(m.group(1).split()).strip().upper()
    matricule = m.group(2).strip()
    date_str = m.group(3)

    date_iso = ""
    date_match = re.search(
        rf"(?:{weekday_alt})\.?\s+(\d{{1,2}})(?:er)?\s+([A-Za-zÀ-ÿ]+)\s+(\d{{4}})",
        date_str,
        re.IGNORECASE,
    )
    if date_match:
        day = int(date_match.group(1))
        month_name = _strip_accents(date_match.group(2)).lower()
        year = int(date_match.group(3))
        month = FRENCH_MONTHS.get(month_name)
        if month:
            try:
                date_iso = date(year, month, day).isoformat()
            except ValueError:
                warnings.append(f"Date détectée invalide : {date_str!r}")
        else:
            warnings.append(f"Mois non reconnu dans la date : {date_str!r}")
    else:
        warnings.append(f"Impossible d'interpréter la date détectée : {date_str!r}")

    return driver_name, matricule, date_iso, warnings


def _clean_place(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"[\(\{][A-Z0-9]{3,8}[\)\}]\s*$", "", s).strip()
    s = re.sub(r"^[\d\s.:\-]+", "", s).strip()
    s = s.strip(" .:-;")
    s = re.sub(r"\s+", " ", s)
    return s


TRAJET_PATTERN = re.compile(
    r"([A-Z0-9' \-.]{4,60}?[\(\{][A-Z0-9]{4,7}[\)\}])\s*/\s*"
    r"([A-Z0-9' \-.]{4,60}?[\(\{][A-Z0-9]{4,7}[\)\}])"
)


def extract_trajets(all_text: str) -> list[str]:
    joined = " ".join(line.strip() for line in all_text.splitlines())
    joined = re.sub(r"\s+", " ", joined)
    labels = []
    for a, b in TRAJET_PATTERN.findall(joined):
        place_a = _clean_place(a)
        place_b = _clean_place(b)
        if len(place_a) < 3 or len(place_b) < 3:
            continue
        pair = sorted([place_a, place_b], key=str.upper)
        labels.append(" / ".join(pair))
    return labels


def _find_summary_band(image: Image.Image) -> tuple[Image.Image, int, int] | None:
    words = ocr_engine.ocr_word_boxes(image, psm=6)
    candidates = [w for w in words if w["text"].upper().strip(":;,.") in HEADER_KEYWORDS]
    if len(candidates) < 3:
        return None

    # Regroupe les mots-clés par ligne (même 'top' à peu près) et garde le groupe le plus large.
    candidates.sort(key=lambda w: w["top"])
    groups: list[list[dict]] = []
    for w in candidates:
        placed = False
        for g in groups:
            if abs(g[-1]["top"] - w["top"]) <= max(g[-1]["height"], w["height"]):
                g.append(w)
                placed = True
                break
        if not placed:
            groups.append([w])
    best = max(groups, key=len)
    if len(best) < 3:
        return None

    header_top = min(w["top"] for w in best)
    header_height = max(w["height"] for w in best)
    width, img_height = image.size

    band_top = min(img_height, header_top + int(header_height * 3))
    band_bottom = min(img_height, band_top + int(header_height * 9))
    if band_bottom <= band_top:
        return None

    by_kw: dict[str, dict] = {}
    for w in sorted(best, key=lambda w: w["left"]):
        key = w["text"].upper().strip(":;,.")
        by_kw.setdefault(key, w)  # garde la 1re occurrence (la plus à gauche) de chaque mot-clé
    x_left = by_kw["TPS"]["left"] if "TPS" in by_kw else min(w["left"] for w in best)
    if "RCN" in by_kw:
        x_right = by_kw["RCN"]["left"] + by_kw["RCN"]["width"]
    else:
        x_right = max(w["left"] + w["width"] for w in best)

    band = image.crop((0, band_top, width, band_bottom))
    return band, x_left, x_right


_NUMBER_TOKEN = re.compile(r"\d+,\d+|\d{3,4}")


def _tokens_to_values(text: str) -> list[float]:
    cleaned = text
    cleaned = re.sub(r"[oO]", "0", cleaned)
    cleaned = re.sub(r"[lI](?=\d)", "1", cleaned)
    cleaned = re.sub(r"(?<=\d)[lI]", "1", cleaned)
    raw_tokens = _NUMBER_TOKEN.findall(cleaned)

    # La 1re "cellule" de la ligne est la date du jour (ex: "16/07"). L'OCR avale souvent
    # le séparateur ("1607"), ce qui donnerait un faux 12e chiffre décalant tout le reste :
    # on la détecte et l'ignore.
    if raw_tokens and "," not in raw_tokens[0] and len(raw_tokens[0]) == 4:
        day, month = raw_tokens[0][:2], raw_tokens[0][2:]
        if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
            raw_tokens = raw_tokens[1:]

    values = []
    for tok in raw_tokens:
        if "," in tok:
            whole, frac = tok.split(",", 1)
            frac = (frac + "00")[:2]
        else:
            whole, frac = tok[:-2], tok[-2:]
        whole = whole or "0"
        try:
            values.append(round(float(f"{whole}.{frac}"), 2))
        except ValueError:
            continue
    return values


def _token_to_decimal(tok: str) -> float | None:
    tok = re.sub(r"[oO]", "0", tok)
    tok = re.sub(r"[lI]", "1", tok)
    if "," in tok:
        whole, frac = tok.split(",", 1)
        frac = (frac + "00")[:2]
    elif len(tok) >= 3:
        whole, frac = tok[:-2], tok[-2:]
    else:
        return None
    whole = whole or "0"
    try:
        return round(float(f"{whole}.{frac}"), 2)
    except ValueError:
        return None


# Les 11 premières colonnes du tableau (les 5 suivantes - Repas/Primes/Dim.Travail/
# Férié/TPS OC - sont quasi toujours vides et laissées à 0 par défaut).
_POSITIONAL_FIELD_COUNT = 11


def parse_summary_from_image(image: Image.Image) -> tuple[dict[str, float], str, list[str]]:
    """Repère et lit le tableau récapitulatif (TPS/TAD/TTE/Ampli/...) sur une page."""
    warnings: list[str] = []
    found = _find_summary_band(image)
    if found is None:
        return {}, "", ["Tableau récapitulatif non localisé automatiquement sur ce document."]
    band, x_left, x_right = found

    scale = 2 if band.width < 2200 else 1
    band_scaled = band.resize((band.width * scale, band.height * scale), Image.LANCZOS) if scale != 1 else band
    text = ocr_engine.ocr_text(band_scaled, psm=6)

    # 1) Répartition par position horizontale : chaque nombre détecté est affecté à la
    #    colonne la plus proche, ce qui évite qu'une seule cellule illisible ne décale
    #    toutes les colonnes suivantes.
    values_by_position: dict[int, float] = {}
    if x_right > x_left:
        bin_width = (x_right - x_left) / _POSITIONAL_FIELD_COUNT
        words = ocr_engine.ocr_word_boxes(band_scaled, psm=6)
        for w in words:
            digits = re.sub(r"[^0-9,oOlI]", "", w["text"])
            value = _token_to_decimal(digits)
            if value is None:
                continue
            center_x = (w["left"] + w["width"] / 2) / scale
            idx = int((center_x - x_left) // bin_width)
            if 0 <= idx < _POSITIONAL_FIELD_COUNT and idx not in values_by_position:
                values_by_position[idx] = value

    summary: dict[str, float] = {}
    if len(values_by_position) >= 3:
        for idx, (field_name, _label) in enumerate(SUMMARY_FIELDS[:_POSITIONAL_FIELD_COUNT]):
            if idx in values_by_position:
                summary[field_name] = values_by_position[idx]
        missing = _POSITIONAL_FIELD_COUNT - len(values_by_position)
        if missing > 0:
            warnings.append(
                f"{missing} valeur(s) du tableau récapitulatif n'ont pas pu être lues automatiquement : vérifie chaque champ."
            )
        return summary, text, warnings

    # 2) Repli : lecture séquentielle simple si le repérage par colonne a échoué.
    values = _tokens_to_values(text)
    if not values:
        warnings.append("Aucune valeur numérique lue dans le tableau récapitulatif ; à saisir manuellement.")
        return {}, text, warnings

    for (field_name, _label), value in zip(SUMMARY_FIELDS, values):
        summary[field_name] = value
    warnings.append(
        "Lecture du tableau récapitulatif incertaine : vérifie bien chaque champ avant d'enregistrer."
    )
    return summary, text, warnings


def extract_from_pages(pages: list[Image.Image]) -> ExtractionResult:
    result = ExtractionResult()

    text_page1 = ocr_engine.ocr_text(pages[0], psm=6)
    result.raw_text_page1 = text_page1

    driver_name, matricule, date_iso, header_warnings = parse_header(text_page1)
    result.driver_name = driver_name
    result.matricule = matricule
    result.date = date_iso
    result.warnings.extend(header_warnings)

    all_text_parts = [text_page1]
    summary_found = False
    for page in pages:
        summary, raw_row_text, warn = parse_summary_from_image(page)
        if summary:
            result.summary = summary
            result.raw_text_summary_row = raw_row_text
            result.warnings.extend(warn)
            summary_found = True
            break
    if not summary_found:
        result.warnings.append(
            "Tableau récapitulatif (TPS/TTE/Amplitude...) non détecté automatiquement : à remplir manuellement."
        )

    for page in pages[1:]:
        all_text_parts.append(ocr_engine.ocr_text(page, psm=6))

    result.trajets = extract_trajets("\n".join(all_text_parts))

    return result
