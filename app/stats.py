"""Agrégations pour l'onglet Statistiques : résumé d'une période, série du graphique, tableau de
détail, trajets et lignes les plus fréquents. Tout est calculé à partir de la liste des ordres de
travail (une seule lecture de la base par rafraîchissement), sans rien écrire."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models import WorkOrder, split_trajet

KINDS = ("week", "month", "year", "all")

FRENCH_MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
                  "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
SHORT_MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
                "nov.", "déc."]
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
SHORT_WEEKDAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

MAX_MONTHS_ALL = 24  # vue "Tout" : au plus les 24 derniers mois dans le graphique


def hours_to_hm(value: float) -> str:
    """Convertit des heures décimales (centièmes d'heure) en 'Hh MM'."""
    total_minutes = round(value * 60)
    sign = "-" if total_minutes < 0 else ""
    total_minutes = abs(total_minutes)
    h, m = divmod(total_minutes, 60)
    return f"{sign}{h}h{m:02d}"


def format_km(value: float) -> str:
    return f"{value:,.0f} km".replace(",", " ")


def long_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {FRENCH_MONTHS[d.month - 1].lower()} {d.year}"


def short_date(d: date) -> str:
    return f"{SHORT_WEEKDAYS[d.weekday()]} {d.day:02d}/{d.month:02d}"


def _order_date(wo: WorkOrder) -> date | None:
    try:
        return date.fromisoformat(wo.date)
    except ValueError:
        return None


# ----------------------------------------------------------------------------- périodes

def period_bounds(kind: str, anchor: date) -> tuple[date | None, date | None]:
    """Premier et dernier jour de la période contenant anchor (None, None pour "all")."""
    if kind == "week":
        monday = anchor - timedelta(days=anchor.weekday())
        return monday, monday + timedelta(days=6)
    if kind == "month":
        start = anchor.replace(day=1)
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1)
        return start, end
    if kind == "year":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    return None, None


def shift_anchor(kind: str, anchor: date, step: int) -> date:
    """Période précédente (step=-1) ou suivante (step=+1)."""
    if kind == "week":
        return anchor + timedelta(days=7 * step)
    if kind == "month":
        index = anchor.year * 12 + anchor.month - 1 + step
        return date(index // 12, index % 12 + 1, 1)
    if kind == "year":
        return date(anchor.year + step, 1, 1)
    return anchor


def period_label(kind: str, anchor: date) -> str:
    start, end = period_bounds(kind, anchor)
    if kind == "week":
        week = anchor.isocalendar()[1]
        if start.month == end.month:
            span = f"{start.day} au {end.day} {FRENCH_MONTHS[end.month - 1].lower()} {end.year}"
        else:
            span = (f"{start.day} {SHORT_MONTHS[start.month - 1]} au "
                    f"{end.day} {SHORT_MONTHS[end.month - 1]} {end.year}")
        return f"Semaine {week} · {span}"
    if kind == "month":
        return f"{FRENCH_MONTHS[anchor.month - 1]} {anchor.year}"
    if kind == "year":
        return str(anchor.year)
    return "Depuis le début"


def in_period(orders: list[WorkOrder], kind: str, anchor: date) -> list[WorkOrder]:
    start, end = period_bounds(kind, anchor)
    if start is None:
        return [wo for wo in orders if _order_date(wo) is not None]
    return [wo for wo in orders if (d := _order_date(wo)) is not None and start <= d <= end]


# ----------------------------------------------------------------------------- résumé

@dataclass
class PeriodSummary:
    days: int = 0
    tte: float = 0.0
    tps: float = 0.0
    ampli: float = 0.0
    tad: float = 0.0
    last_minute_count: int = 0
    meal_count: int = 0
    trajet_count: int = 0
    km_productifs: float = 0.0
    km_hlp: float = 0.0
    km_totaux: float = 0.0
    km_days: int = 0  # jours avec des kilomètres (Feuilles de Route seulement)
    indem_coup: float = 0.0
    indem_ampl: float = 0.0
    longest: WorkOrder | None = None  # journée au plus grand TTE
    widest: WorkOrder | None = None   # journée à la plus grande amplitude

    @property
    def avg_tte(self) -> float:
        return self.tte / self.days if self.days else 0.0

    @property
    def avg_ampli(self) -> float:
        return self.ampli / self.days if self.days else 0.0


def summarize(orders: list[WorkOrder]) -> PeriodSummary:
    s = PeriodSummary()
    for wo in orders:
        s.days += 1
        s.tte += wo.tte
        s.tps += wo.tps
        s.ampli += wo.ampli
        s.tad += wo.tad
        s.last_minute_count += int(bool(wo.last_minute_change))
        s.meal_count += int(bool(wo.repas_midi)) + int(bool(wo.repas_soir))
        s.trajet_count += len(wo.trajets)
        s.km_productifs += wo.km_productifs
        s.km_hlp += wo.km_hlp
        s.km_totaux += wo.km_totaux
        s.km_days += int(wo.km_totaux > 0)
        s.indem_coup += wo.indem_coup
        s.indem_ampl += wo.indem_ampl
        if s.longest is None or wo.tte > s.longest.tte:
            s.longest = wo
        if s.widest is None or wo.ampli > s.widest.ampli:
            s.widest = wo
    return s


# ----------------------------------------------------------------------------- tableau de détail

@dataclass
class PeriodGroup:
    kind: str       # "week" | "month" | "year" : ce sur quoi un clic doit amener
    anchor: date    # un jour de la période
    label: str
    summary: PeriodSummary


def grouped(orders: list[WorkOrder], kind: str) -> list[PeriodGroup]:
    """Une ligne par semaine / mois / année ayant au moins un OT, de la plus récente à la plus
    ancienne."""
    buckets: dict[date, list[WorkOrder]] = {}
    for wo in orders:
        d = _order_date(wo)
        if d is None:
            continue
        start, _end = period_bounds(kind, d)
        buckets.setdefault(start, []).append(wo)
    return [
        PeriodGroup(kind, start, period_label(kind, start), summarize(items))
        for start, items in sorted(buckets.items(), reverse=True)
    ]


# ----------------------------------------------------------------------------- graphique

@dataclass
class ChartPoint:
    label: str                 # sous la barre
    value: float               # TTE en heures
    title: str                 # 1re ligne de l'info-bulle
    lines: list[str] = field(default_factory=list)  # lignes suivantes de l'info-bulle
    target: tuple[str, date] | None = None          # (kind, anchor) : où un clic amène
    muted: bool = False        # libellé atténué (samedi / dimanche)


def _day_point(d: date, wo: WorkOrder | None, label: str) -> ChartPoint:
    point = ChartPoint(label=label, value=wo.tte if wo else 0.0, title=long_date(d).capitalize(),
                       muted=d.weekday() >= 5)
    if wo is None:
        point.lines = ["Pas d'ordre de travail"]
        return point
    point.lines = [f"Temps de travail : {hours_to_hm(wo.tte)}", f"Amplitude : {hours_to_hm(wo.ampli)}"]
    detail = [f"{len(wo.trajets)} trajet{'s' if len(wo.trajets) != 1 else ''}"]
    if wo.km_totaux:
        detail.append(format_km(wo.km_totaux))
    point.lines.append(" · ".join(detail))
    flags = []
    if wo.repas_midi:
        flags.append("repas midi")
    if wo.repas_soir:
        flags.append("repas soir")
    if wo.last_minute_change:
        flags.append("changement de dernière minute")
    if flags:
        point.lines.append(" · ".join(flags).capitalize())
    return point


def _month_point(start: date, items: list[WorkOrder], label: str) -> ChartPoint:
    s = summarize(items)
    lines = ["Pas d'ordre de travail"]
    if s.days:
        lines = [f"Temps de travail : {hours_to_hm(s.tte)}",
                 f"{s.days} jour{'s' if s.days > 1 else ''} · {hours_to_hm(s.avg_tte)} en moyenne"]
    return ChartPoint(label=label, value=s.tte, title=f"{FRENCH_MONTHS[start.month - 1]} {start.year}",
                      lines=lines, target=("month", start))


def chart_series(orders: list[WorkOrder], kind: str, anchor: date) -> list[ChartPoint]:
    """Semaine et mois : une barre par jour. Année et "Tout" : une barre par mois."""
    by_day: dict[date, WorkOrder] = {}
    by_month: dict[date, list[WorkOrder]] = {}
    for wo in orders:
        d = _order_date(wo)
        if d is None:
            continue
        by_day[d] = wo
        by_month.setdefault(d.replace(day=1), []).append(wo)

    if kind in ("week", "month"):
        start, end = period_bounds(kind, anchor)
        points = []
        d = start
        while d <= end:
            label = f"{SHORT_WEEKDAYS[d.weekday()]}\n{d.day:02d}" if kind == "week" else str(d.day)
            points.append(_day_point(d, by_day.get(d), label))
            d += timedelta(days=1)
        return points

    if kind == "year":
        months = [date(anchor.year, m, 1) for m in range(1, 13)]
        return [_month_point(m, by_month.get(m, []), SHORT_MONTHS[m.month - 1]) for m in months]

    if not by_month:
        return []
    first, last = min(by_month), max(by_month)
    months = []
    m = first
    while m <= last:
        months.append(m)
        m = shift_anchor("month", m, 1)
    months = months[-MAX_MONTHS_ALL:]
    return [_month_point(m, by_month.get(m, []), f"{SHORT_MONTHS[m.month - 1]}\n{m.year % 100:02d}")
            for m in months]


# ----------------------------------------------------------------------------- trajets

@dataclass
class TrajetCount:
    label: str
    count: int


def top_trajets(orders: list[WorkOrder], limit: int = 12) -> list[TrajetCount]:
    counter: Counter[str] = Counter()
    for wo in orders:
        counter.update(wo.trajets)
    return [TrajetCount(label, count) for label, count in counter.most_common(limit)]


def top_lignes(orders: list[WorkOrder], limit: int = 12) -> list[TrajetCount]:
    """Nombre de trajets par numéro de ligne (les trajets sans numéro sont regroupés)."""
    counter: Counter[str] = Counter()
    for wo in orders:
        for trajet in wo.trajets:
            ligne = split_trajet(trajet)[0]
            counter[f"Ligne {ligne}" if ligne else "Sans numéro de ligne"] += 1
    return [TrajetCount(label, count) for label, count in counter.most_common(limit)]
