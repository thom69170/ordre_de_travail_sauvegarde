"""Agrégations : temps de travail par semaine/mois/année, trajets les plus fréquents."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from app import db
from app.models import WorkOrder


def hours_to_hm(value: float) -> str:
    """Convertit des heures décimales (centièmes d'heure) en 'Hh MM'."""
    total_minutes = round(value * 60)
    sign = "-" if total_minutes < 0 else ""
    total_minutes = abs(total_minutes)
    h, m = divmod(total_minutes, 60)
    return f"{sign}{h}h{m:02d}"


@dataclass
class PeriodTotal:
    key: str
    label: str
    days: int = 0
    tte: float = 0.0
    tps: float = 0.0
    ampli: float = 0.0


def _iso_week_key(d: date) -> tuple[str, str]:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}", f"Semaine {week:02d} / {year}"


FRENCH_MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
                  "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


def _month_key(d: date) -> tuple[str, str]:
    return f"{d.year}-{d.month:02d}", f"{FRENCH_MONTHS[d.month - 1]} {d.year}"


def _year_key(d: date) -> tuple[str, str]:
    return str(d.year), str(d.year)


def _aggregate(work_orders: list[WorkOrder], key_fn) -> list[PeriodTotal]:
    totals: dict[str, PeriodTotal] = {}
    for wo in work_orders:
        try:
            d = date.fromisoformat(wo.date)
        except ValueError:
            continue
        key, label = key_fn(d)
        pt = totals.setdefault(key, PeriodTotal(key=key, label=label))
        pt.days += 1
        pt.tte += wo.tte
        pt.tps += wo.tps
        pt.ampli += wo.ampli
    return sorted(totals.values(), key=lambda pt: pt.key)


def weekly_totals(start_date: str | None = None, end_date: str | None = None) -> list[PeriodTotal]:
    return _aggregate(db.list_work_orders(start_date, end_date), _iso_week_key)


def monthly_totals(start_date: str | None = None, end_date: str | None = None) -> list[PeriodTotal]:
    return _aggregate(db.list_work_orders(start_date, end_date), _month_key)


def yearly_totals(start_date: str | None = None, end_date: str | None = None) -> list[PeriodTotal]:
    return _aggregate(db.list_work_orders(start_date, end_date), _year_key)


@dataclass
class PeriodSummary:
    days: int = 0
    tte: float = 0.0
    tps: float = 0.0
    ampli: float = 0.0
    tad: float = 0.0


def summary_for_period(start_date: str | None = None, end_date: str | None = None) -> PeriodSummary:
    summary = PeriodSummary()
    for wo in db.list_work_orders(start_date, end_date):
        summary.days += 1
        summary.tte += wo.tte
        summary.tps += wo.tps
        summary.ampli += wo.ampli
        summary.tad += wo.tad
    return summary


@dataclass
class TrajetCount:
    label: str
    count: int


def top_trajets(start_date: str | None = None, end_date: str | None = None, limit: int = 20) -> list[TrajetCount]:
    counter: Counter[str] = Counter()
    for wo in db.list_work_orders(start_date, end_date):
        counter.update(wo.trajets)
    return [TrajetCount(label=label, count=count) for label, count in counter.most_common(limit)]
