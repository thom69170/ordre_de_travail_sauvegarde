"""Indemnités de repas : suggestion calculée à partir des heures du service.

Règles confirmées par l'utilisateur (convention transport de voyageurs, telle qu'appliquée chez
lui) - l'app ne fait que SUGGÉRER, les cases restent modifiables et aucun montant n'est calculé :
- un repas est dû si le service (de la prise de service à la fin de service) couvre TOUTE la plage
  du repas : 11h00-14h30 pour le midi, 18h30-22h00 pour le soir ;
- sauf si le conducteur dispose, PENDANT cette plage, d'une coupure d'au moins 1 heure au dépôt.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LUNCH_WINDOW = (11 * 60, 14 * 60 + 30)
DINNER_WINDOW = (18 * 60 + 30, 22 * 60)
MIN_BREAK_MINUTES = 60


@dataclass
class Pause:
    start: int  # minutes depuis minuit
    end: int
    place: str  # lieu imprimé sur la ligne de coupure (Feuille de Route), sinon ""
    line_before: str = ""  # texte de la ligne juste avant / juste après la coupure (ancien
    line_after: str = ""   # format, où la coupure elle-même n'indique aucun lieu)

    def at_depot(self) -> bool:
        """Le conducteur est au dépôt pendant la coupure si elle y est située, s'il y arrive
        juste avant ("... -> SARCEY - DEPOT") ou s'il en repart juste après ("SARCEY - DEPOT ->
        ..."). Déduit ici à partir des lignes recopiées telles quelles : demandé directement,
        Gemini donnait un lieu faux une fois sur deux sur l'ancien format."""
        candidates = [self.place]
        if self.line_before:
            candidates.append(re.split(r"->|/", self.line_before)[-1])
        if self.line_after:
            candidates.append(re.split(r"->|/", self.line_after)[0])
        return any(is_depot(text) for text in candidates)


@dataclass
class MealSuggestion:
    lunch: bool = False
    dinner: bool = False
    checked: bool = False  # False : heures de service illisibles, rien n'a pu être vérifié
    explanation: str = ""


def parse_minutes(text: str) -> int | None:
    """"06h45", "6:45" -> minutes depuis minuit ; None si illisible."""
    match = re.match(r"^\s*(\d{1,2})\s*[hH:]\s*(\d{2})\s*$", text or "")
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def _hm(minutes: int) -> str:
    return f"{(minutes // 60) % 24}h{minutes % 60:02d}"


def is_depot(place: str) -> bool:
    text = unicodedata.normalize("NFD", place or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "DEPOT" in text.upper()


# Écart toléré entre la durée totale des coupures lues et celle attendue (amplitude - TTE) pour
# considérer que les coupures ont été lues correctement.
BREAK_MISMATCH_TOLERANCE = 15


def _one_meal(
    name: str, window: tuple[int, int], ps: int, fs: int, pauses: list[Pause]
) -> tuple[bool, str, bool]:
    """Retourne (repas dû, explication, repose_sur_une_coupure_hors_depot)."""
    start, end = window
    label = f"{_hm(start)}-{_hm(end)}"
    if ps > start or fs < end:
        text = f"{name} : non (le service {_hm(ps)}-{_hm(fs)} ne couvre pas toute la plage {label})"
        return False, text, False
    offsite = None
    for pause in pauses:
        overlap = min(pause.end, end) - max(pause.start, start)
        if overlap < MIN_BREAK_MINUTES:
            continue
        if pause.at_depot():
            return False, (
                f"{name} : non (coupure {_hm(pause.start)}-{_hm(pause.end)} au dépôt pendant la "
                f"plage {label})"
            ), False
        offsite = pause
    if offsite is not None:
        return True, (
            f"{name} : OUI (service {_hm(ps)}-{_hm(fs)} ; la coupure {_hm(offsite.start)}-"
            f"{_hm(offsite.end)} n'est pas au dépôt d'après le document)"
        ), True
    text = f"{name} : OUI (service {_hm(ps)}-{_hm(fs)}, pas de coupure d'1 h au dépôt entre {label})"
    return True, text, False


def suggest_meals(
    ps_text: str, fs_text: str, pauses: list[Pause], expected_break_minutes: float | None = None
) -> MealSuggestion:
    """expected_break_minutes : durée totale des coupures de la journée connue par ailleurs
    (amplitude - TTE), pour contrôler ce qui a été lu. Un repas n'est pas suggéré, seulement
    signalé "à vérifier", quand la lecture des coupures n'est pas sûre :
    - il manque 1 heure ou plus de coupure : elle pourrait être au dépôt pendant le repas ;
    - le repas ne tient qu'à une longue coupure lue "hors dépôt" alors que les durées lues ne
      concordent pas avec la durée attendue (coupure probablement mal lue)."""
    ps, fs = parse_minutes(ps_text), parse_minutes(fs_text)
    if ps is None or fs is None:
        return MealSuggestion(
            explanation="Indemnités de repas : non vérifiées (heure de prise ou de fin de service "
                        "non lue), coche les cases à la main si besoin."
        )
    if fs <= ps:  # service qui finit après minuit
        fs += 24 * 60

    unlocated = mismatch = 0
    if expected_break_minutes is not None:
        located = sum(p.end - p.start for p in pauses if p.end - p.start >= 30)
        unlocated = round(expected_break_minutes - located)
        mismatch = abs(unlocated)

    results = []
    for name, window in (("midi", LUNCH_WINDOW), ("soir", DINNER_WINDOW)):
        due, text, offsite = _one_meal(name, window, ps, fs, pauses)
        if due and unlocated >= MIN_BREAK_MINUTES:
            due, text = False, (
                f"{name} : À VÉRIFIER (une coupure d'environ {_hm(unlocated)} n'a pas pu être "
                "située dans la journée)"
            )
        elif due and offsite and mismatch >= BREAK_MISMATCH_TOLERANCE:
            due, text = False, (
                f"{name} : À VÉRIFIER (une longue coupure pendant la plage semble mal lue : "
                "regarde si elle est au dépôt)"
            )
        results.append((due, text))
    (lunch, lunch_text), (dinner, dinner_text) = results
    return MealSuggestion(
        lunch=lunch, dinner=dinner, checked=True,
        explanation=f"Indemnités de repas suggérées - {lunch_text} ; {dinner_text}. Vérifie et "
                    "corrige les cases si besoin.",
    )
