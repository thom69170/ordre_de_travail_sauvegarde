"""Extraction des heures supplémentaires depuis une "feuille de prépaie" (rapport d'activité
RNA/ABC Informatique) - un PDF généré numériquement (pas une photo), donc lu par extraction de
texte directe plutôt que par OCR : bien plus fiable pour un document chiffré comme celui-ci.

Ne calcule jamais les heures sup nous-mêmes (le mode de calcul exact - équivalence, modulation -
n'est pas documenté de façon fiable) : on se contente de relire ce que le document indique déjà.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PayslipData:
    period_start: str = ""  # ISO YYYY-MM-DD
    period_end: str = ""  # ISO YYYY-MM-DD
    hs_25: float = 0.0
    hs_50: float = 0.0
    cumul_hs_25: float = 0.0
    cumul_hs_50: float = 0.0
    warnings: list[str] = field(default_factory=list)


_PERIOD_PATTERN = re.compile(r"##(\d{4}-\d{2}-\d{2})##(\d{4}-\d{2}-\d{2})##")
_NUMBER_LINE = re.compile(r"^\d+[.,]\d{2}$")
_HS25_LABEL = re.compile(r"HS\s*1?25\s*%", re.IGNORECASE)
_HS50_LABEL = re.compile(r"HS\s*1?50\s*%", re.IGNORECASE)


def _extract_all_text(path: Path) -> str:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    parts = []
    for i in range(len(pdf)):
        parts.append(pdf[i].get_textpage().get_text_range())
    return "\n".join(parts)


def _parse_value_label_block(block_text: str) -> dict[str, float]:
    """Un bloc "Récapitulatif mensuel"/"Compteurs" de ce document est mis en page en deux
    colonnes (valeurs à droite, libellés à gauche) : le texte extrait du PDF liste donc d'abord
    TOUTES les valeurs numériques du bloc, puis TOUS les libellés correspondants, dans le même
    ordre - on les réassocie par position."""
    lines = [ln.strip() for ln in block_text.splitlines() if ln.strip()]
    # Le bloc peut être précédé de texte d'en-tête (nom, date d'édition...) qui n'est pas une
    # valeur : on ignore tout jusqu'à la première ligne numérique plutôt que de supposer que la
    # colonne de valeurs commence dès le tout début du bloc.
    start = next((i for i, ln in enumerate(lines) if _NUMBER_LINE.match(ln)), None)
    if start is None:
        return {}
    values: list[float] = []
    i = start
    while i < len(lines) and _NUMBER_LINE.match(lines[i]):
        values.append(float(lines[i].replace(",", ".")))
        i += 1
    labels = lines[i:]
    return dict(zip(labels, values))


def _find_value(mapping: dict[str, float], pattern: re.Pattern) -> float:
    for label, value in mapping.items():
        if pattern.search(label):
            return value
    return 0.0


def extract_payslip(path: Path) -> PayslipData:
    result = PayslipData()
    text = _extract_all_text(path)

    period_match = _PERIOD_PATTERN.search(text)
    if period_match:
        result.period_start, result.period_end = period_match.group(1), period_match.group(2)
    else:
        result.warnings.append("Période (dates) non détectée automatiquement.")

    recap_idx = text.find("Récapitulatif mensuel")
    compteurs_idx = text.find("Compteurs", recap_idx if recap_idx >= 0 else 0)

    if recap_idx < 0 or compteurs_idx < 0:
        result.warnings.append(
            "Sections 'Récapitulatif mensuel' / 'Compteurs' non trouvées : "
            "vérifie que c'est bien une feuille de prépaie RNA."
        )
        return result

    # Le bloc "Récapitulatif mensuel" (valeurs + libellés du mois) est AVANT le marqueur de
    # titre ; le bloc "Compteurs" (valeurs + libellés cumulés) est APRÈS son propre marqueur.
    recap_block = text[:recap_idx]
    compteurs_block = text[compteurs_idx + len("Compteurs"):]

    recap = _parse_value_label_block(recap_block)
    compteurs = _parse_value_label_block(compteurs_block)

    result.hs_25 = _find_value(recap, _HS25_LABEL)
    result.hs_50 = _find_value(recap, _HS50_LABEL)
    result.cumul_hs_25 = _find_value(compteurs, _HS25_LABEL)
    result.cumul_hs_50 = _find_value(compteurs, _HS50_LABEL)

    return result
