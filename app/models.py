"""Structures de données de l'application."""
from __future__ import annotations

from dataclasses import dataclass, field

# Colonnes du tableau récapitulatif (page 2 des ordres de travail), dans l'ordre
# où elles apparaissent sur le document. Les valeurs sont en centièmes d'heure.
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


@dataclass
class WorkOrder:
    id: int | None = None
    date: str = ""  # ISO YYYY-MM-DD
    driver_name: str = ""
    matricule: str = ""
    source_filename: str = ""
    source_type: str = ""  # 'pdf' ou 'image'
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

    trajets: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Résultat brut (et donc potentiellement imparfait) de l'OCR, avant validation utilisateur."""
    driver_name: str = ""
    matricule: str = ""
    date: str = ""  # ISO si détectée, sinon ""
    summary: dict[str, float] = field(default_factory=dict)
    trajets: list[str] = field(default_factory=list)
    raw_text_page1: str = ""
    raw_text_summary_row: str = ""
    warnings: list[str] = field(default_factory=list)
