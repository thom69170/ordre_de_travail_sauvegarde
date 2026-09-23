"""Structures de données de l'application (portées telles quelles depuis l'app desktop)."""
from __future__ import annotations

from dataclasses import dataclass, field

SUMMARY_FIELDS = [
    ("tps", "TPS"),
    ("tad", "TAD"),
    ("autres_temps", "Autres Temps"),
    ("tte", "TTE"),
    ("hlr50", "HLR 50% HI"),
    ("hlr100", "HLR 100% HI"),
    ("ampli", "Amplitude"),
    ("amp_lt12", "Amp<12 HI25%"),
    ("amp_12_13", "Amp 12-13 HI75%"),
    ("amp_gt13", "Amp>13 HI100%"),
    ("rcn", "RCN 21h-6h"),
    ("repas", "Repas P"),
    ("primes", "Primes P"),
    ("dim_travail", "Dim. Travail P"),
    ("ferie", "Férié P"),
    ("tps_oc", "TPS OC P"),
]

SUMMARY_FIELD_NAMES = [f[0] for f in SUMMARY_FIELDS]

TRAJET_LIGNE_SEPARATOR = " — "


def format_trajet(ligne: str, label: str) -> str:
    ligne = (ligne or "").strip()
    label = (label or "").strip()
    if ligne:
        return f"{ligne}{TRAJET_LIGNE_SEPARATOR}{label}"
    return label


def split_trajet(trajet: str) -> tuple[str, str]:
    if TRAJET_LIGNE_SEPARATOR in trajet:
        ligne, label = trajet.split(TRAJET_LIGNE_SEPARATOR, 1)
        return ligne.strip(), label.strip()
    return "", trajet.strip()


@dataclass
class WorkOrder:
    id: int | None = None
    date: str = ""
    driver_name: str = ""
    matricule: str = ""
    source_filename: str = ""
    source_type: str = ""
    notes: str = ""
    created_at: str = ""

    tps: float = 0.0
    tad: float = 0.0
    autres_temps: float = 0.0
    tte: float = 0.0
    hlr50: float = 0.0
    hlr100: float = 0.0
    ampli: float = 0.0
    amp_lt12: float = 0.0
    amp_12_13: float = 0.0
    amp_gt13: float = 0.0
    rcn: float = 0.0
    repas: float = 0.0
    primes: float = 0.0
    dim_travail: float = 0.0
    ferie: float = 0.0
    tps_oc: float = 0.0

    last_minute_change: bool = False

    trajets: list[str] = field(default_factory=list)


@dataclass
class Payslip:
    id: int | None = None
    period_start: str = ""
    period_end: str = ""
    hs_25: float = 0.0
    hs_50: float = 0.0
    cumul_hs_25: float = 0.0
    cumul_hs_50: float = 0.0
    repos_differe: float = 0.0
    source_filename: str = ""
    created_at: str = ""
    details_json: str = ""


@dataclass
class ExtractionResult:
    driver_name: str = ""
    matricule: str = ""
    date: str = ""
    summary: dict[str, float] = field(default_factory=dict)
    trajets: list[str] = field(default_factory=list)
    last_minute_change: bool = False
    raw_text_page1: str = ""
    raw_text_summary_row: str = ""
    warnings: list[str] = field(default_factory=list)
