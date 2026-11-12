"""Contrôle de paie : rapproche les totaux d'une feuille de prépaie de ceux des ordres de travail
enregistrés sur la même période.

Fidèle au principe de l'app : aucun montant en euros n'est calculé, on compare seulement des
compteurs déjà imprimés sur les documents (jours, heures, nombre de primes) et on signale les
écarts - à l'utilisateur de voir ensuite avec son employeur.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from app import db
from app.models import Bulletin, Payslip

# Écart toléré sur les heures (arrondis des centièmes d'heure, jour après jour).
HOURS_TOLERANCE = 0.10


@dataclass
class CheckLine:
    label: str
    payslip_value: float | None  # None : ligne absente de la feuille de prépaie
    ot_value: float
    unit: str  # "j", "h" ou "" (simple nombre)
    status: str = ""  # "ok", "moins" (prépaie < OT), "plus" (prépaie > OT), "absent"
    comment: str = ""

    @property
    def diff(self) -> float | None:
        if self.payslip_value is None:
            return None
        return round(self.payslip_value - self.ot_value, 2)


@dataclass
class PayrollCheck:
    period_start: str
    period_end: str
    ot_count: int = 0
    lines: list[CheckLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def find_recap_value(recap: dict, *patterns: str) -> float | None:
    """Valeur de la première ligne du récapitulatif dont le libellé (sans accents ni majuscules)
    correspond à l'un des motifs. None si aucune."""
    for pattern in patterns:
        regex = re.compile(pattern)
        for label, value in recap.items():
            if regex.search(_normalize(label)) and isinstance(value, (int, float)):
                return float(value)
    return None


def _finish(line: CheckLine, tolerance: float, less_msg: str, more_msg: str) -> CheckLine:
    if line.payslip_value is None:
        line.status = "absent"
        line.comment = "Ligne absente de la feuille de prépaie."
    elif abs(line.diff) <= tolerance:
        line.status = "ok"
    elif line.diff < 0:
        line.status = "moins"
        line.comment = less_msg
    else:
        line.status = "plus"
        line.comment = more_msg
    return line


def check_payslip(payslip: Payslip) -> PayrollCheck:
    check = PayrollCheck(period_start=payslip.period_start, period_end=payslip.period_end)
    try:
        details = json.loads(payslip.details_json) if payslip.details_json else {}
    except (json.JSONDecodeError, TypeError):
        details = {}
    recap = details.get("recap") or {}
    if not recap:
        check.notes.append(
            "Ce relevé ne contient pas le détail de la feuille de prépaie (import ancien ou "
            "saisie manuelle) : réimporte le PDF pour pouvoir le contrôler."
        )
        return check

    orders = db.list_work_orders(payslip.period_start, payslip.period_end or payslip.period_start)
    check.ot_count = len(orders)

    days = _finish(
        CheckLine("Jours travaillés", find_recap_value(recap, r"^jours travailles"),
                  float(len(orders)), "j"),
        0,
        "Plus de jours dans tes OT que sur la feuille de prépaie : vérifie qu'aucun OT n'est "
        "d'un autre mois ou en double.",
        "Il manque des OT dans l'application pour ce mois.",
    )
    check.lines.append(days)

    check.lines.append(_finish(
        CheckLine("TTE (temps de travail)", find_recap_value(recap, r"^tte$"),
                  round(sum(o.tte for o in orders), 2), "h"),
        HOURS_TOLERANCE,
        "Moins d'heures sur la feuille de prépaie que sur tes OT : à vérifier.",
        "Plus d'heures sur la feuille de prépaie que sur tes OT.",
    ))

    check.lines.append(_finish(
        CheckLine("Prime modification de service",
                  find_recap_value(recap, r"prime modification"),
                  float(sum(1 for o in orders if o.last_minute_change)), ""),
        0,
        "Moins de primes payées que de changements de dernière minute relevés sur tes OT : "
        "à réclamer si tes OT sont exacts.",
        "Plus de primes payées que de changements relevés sur tes OT.",
    ))
    # Une prime absente de la feuille n'est un problème que si on en attendait une.
    last = check.lines[-1]
    if last.status == "absent":
        if last.ot_value == 0:
            last.status, last.comment = "ok", "Aucune prime sur la feuille, aucune relevée sur tes OT."
        else:
            last.status = "moins"
            last.comment = (
                "Aucune prime sur la feuille de prépaie alors que tes OT relèvent des changements "
                "de dernière minute : à réclamer si tes OT sont exacts."
            )

    # Repas : la feuille de prépaie les compte sur deux lignes ("Repas unique" et "Indemnité
    # spéciale") ; l'app ne distingue pas les deux et compare le total.
    meal_values = [
        v for v in (
            find_recap_value(recap, r"^repas unique"),
            find_recap_value(recap, r"^indemnite speciale"),
        ) if v is not None
    ]
    meals_line = _finish(
        CheckLine("Indemnités de repas (repas unique + indemnité spéciale)",
                  sum(meal_values) if meal_values else None,
                  float(sum(int(o.repas_midi) + int(o.repas_soir) for o in orders)), ""),
        0,
        "Moins de repas payés que de repas dus d'après tes OT : à réclamer si tes OT sont exacts.",
        "Plus de repas payés que de repas relevés sur tes OT (cases « Repas » non cochées ?).",
    )
    if meals_line.status == "absent":
        if meals_line.ot_value == 0:
            meals_line.status = "ok"
            meals_line.comment = "Aucun repas sur la feuille, aucun relevé sur tes OT."
        else:
            meals_line.status = "moins"
            meals_line.comment = (
                "Aucun repas sur la feuille de prépaie alors que tes OT en relèvent : à réclamer "
                "si tes OT sont exacts."
            )
    check.lines.append(meals_line)

    if days.payslip_value is not None and len(orders) < days.payslip_value:
        missing = int(days.payslip_value - len(orders))
        check.notes.append(
            f"Il manque {missing} jour(s) d'OT dans l'application pour cette période : tant que "
            "tous les jours ne sont pas importés, les écarts sur les heures et les primes ne "
            "veulent rien dire."
        )
    elif not orders:
        check.notes.append("Aucun ordre de travail enregistré sur cette période.")
    return check


# (libellé affiché, motif des lignes du bulletin, motif de la ligne de la feuille de prépaie, unité)
# Motifs appliqués aux libellés sans accents ni majuscules.
_BULLETIN_PAIRS = (
    ("Heures indemnisées", r"\bh indemnitaire", r"^heures indemnisees", "h"),
    ("Heures supplémentaires 150 % (HS 50 %)", r"heures suppl\.? 150", r"^hs 150", "h"),
    ("Prime modification de service", r"prime modification", r"prime modification", ""),
    ("Prime urbain (+5 trajets)", r"prime urbain", r"prime urbain", ""),
    ("Repas unique", r"indemnite repas unique", r"^repas unique", ""),
    ("Indemnité spéciale", r"indem\S* (ns )?speciale", r"^indemnite speciale", ""),
)


def format_hours(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " h"


def _cumul_hs50_increase(prepaie: Payslip) -> float | None:
    """Heures HS 50 % du mois d'une feuille de prépaie, déduites de la hausse de son cumul annuel
    par rapport à la feuille du mois précédent (None si on ne peut pas le savoir)."""
    from app.bulletin_parser import previous_month_start

    if prepaie.period_start[5:7] == "01":  # le cumul repart de zéro en janvier
        before = 0.0
    else:
        earlier = db.get_payslip_by_period(previous_month_start(prepaie.period_start))
        if earlier is None:
            return None
        before = earlier.cumul_hs_50
    delta = round(prepaie.cumul_hs_50 - before, 2)
    return delta if delta > 0 else None


def check_bulletin(bulletin: Bulletin) -> PayrollCheck:
    """Rapproche les éléments variables payés sur un bulletin de paie (lignes "RAP ...") de ceux
    annoncés par la feuille de prépaie du mois PRÉCÉDENT : le bulletin d'août paie les heures
    indemnisées, primes et repas de juillet (vérifié sur des documents réels : mêmes quantités).
    Dans les CheckLine, payslip_value = quantité payée (bulletin), ot_value = quantité annoncée
    (feuille de prépaie)."""
    from app.bulletin_parser import normalize, previous_month_start

    check = PayrollCheck(period_start=bulletin.period_start, period_end=bulletin.period_end)
    try:
        details = json.loads(bulletin.details_json) if bulletin.details_json else {}
    except (json.JSONDecodeError, TypeError):
        details = {}
    lines = details.get("lines") or []

    previous_start = previous_month_start(bulletin.period_start)
    check.period_start = previous_start  # période de la feuille de prépaie comparée
    prepaie = db.get_payslip_by_period(previous_start)
    if prepaie is None:
        check.notes.append(
            "La feuille de prépaie du mois précédent n'est pas importée (onglet Heures sup.) : "
            "importe-la pour pouvoir comparer."
        )
        return check
    check.period_end = prepaie.period_end
    try:
        recap = (json.loads(prepaie.details_json) if prepaie.details_json else {}).get("recap") or {}
    except (json.JSONDecodeError, TypeError):
        recap = {}
    if not recap:
        check.notes.append(
            "La feuille de prépaie du mois précédent ne contient pas son détail (import ancien) : "
            "réimporte son PDF pour pouvoir comparer."
        )
        return check

    for label, bulletin_pattern, recap_pattern, unit in _BULLETIN_PAIRS:
        regex = re.compile(bulletin_pattern)
        quantities = [
            line["quantity"] for line in lines
            if line.get("quantity") is not None and regex.search(normalize(line.get("label", "")))
        ]
        paid = max(quantities) if quantities else None
        announced = find_recap_value(recap, recap_pattern)
        deduced_note = ""
        if paid and not announced and recap_pattern == r"^hs 150":
            # La ligne mensuelle "HS 150%" manque sur certaines feuilles de prépaie alors que le
            # cumul annuel a bien augmenté (constaté sur des documents réels : +3,66 en avril 2026,
            # payé 3,67 sur le bulletin de mai) : on en déduit les heures du mois.
            delta = _cumul_hs50_increase(prepaie)
            if delta:
                announced = delta
                deduced_note = (
                    f"La ligne « HS 150% » du mois n'est pas imprimée sur la feuille de prépaie ; "
                    f"les {format_hours(delta)} sont déduits de la hausse de son cumul annuel "
                    "HS 50 %."
                )
        if paid is None and not announced:
            continue  # rien d'un côté ni de l'autre
        line = CheckLine(label, paid, float(announced or 0.0), unit)
        line.comment = deduced_note
        if paid is None:
            line.status = "moins"
            line.comment = (
                "Annoncé sur la feuille de prépaie mais introuvable sur le bulletin (peut-être "
                "sous un autre libellé) : à vérifier."
            )
        else:
            note = line.comment
            _finish(
                line, 0.02 if unit == "h" else 0.01,
                "Moins payé sur le bulletin qu'annoncé sur la feuille de prépaie : à vérifier.",
                "Plus payé sur le bulletin qu'annoncé sur la feuille de prépaie.",
            )
            if note:
                line.comment = (note + " " + line.comment).strip()
        check.lines.append(line)
    if not check.lines:
        check.notes.append(
            "Aucun élément comparable trouvé (ni heures indemnisées, ni primes, ni repas)."
        )
    return check
