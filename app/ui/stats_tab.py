"""Onglet 'Statistiques' : temps de travail par semaine/mois/année, trajets les plus fréquents."""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from app import stats
from app.stats import hours_to_hm
from app.ui.common import ACCENT, BORDER, CARD_BG, SUCCESS, TEXT_MUTED, ScrollableFrame

PERIODS = ["Semaine", "Mois", "Année"]


def _current_week_range() -> tuple[str, str]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def _current_month_range() -> tuple[str, str]:
    today = date.today()
    start = date(today.year, today.month, 1)
    end = date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _current_year_range() -> tuple[str, str]:
    today = date.today()
    return date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()


class SummaryCard(ttk.Frame):
    def __init__(self, parent, title: str):
        super().__init__(parent, padding=16, style="Card.TFrame")
        ttk.Label(self, text=title, font=("Segoe UI", 9), foreground=TEXT_MUTED).pack(anchor="w")
        self.value_label = ttk.Label(self, text="0h00", font=("Segoe UI Semibold", 20))
        self.value_label.pack(anchor="w", pady=(2, 0))
        self.sub_label = ttk.Label(self, text="", font=("Segoe UI", 8), foreground=TEXT_MUTED)
        self.sub_label.pack(anchor="w")

    def set(self, value_text: str, sub_text: str = ""):
        self.value_label.config(text=value_text)
        self.sub_label.config(text=sub_text)


class BarRow(ttk.Frame):
    MAX_WIDTH = 300

    def __init__(self, parent, label: str, value_text: str, fraction: float, color: str = ACCENT):
        super().__init__(parent)
        ttk.Label(self, text=label, width=20, anchor="w").pack(side="left")
        track = tk.Frame(self, bg=BORDER, width=self.MAX_WIDTH, height=16)
        track.pack(side="left", padx=6)
        track.pack_propagate(False)
        bar_w = max(2, int(self.MAX_WIDTH * max(0.0, min(1.0, fraction))))
        tk.Frame(track, bg=color, width=bar_w, height=16).place(x=0, y=0)
        ttk.Label(self, text=value_text, width=12, anchor="w").pack(side="left")


class StatsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        cards_row = ttk.Frame(self, padding=12)
        cards_row.pack(fill="x")
        self.card_week = SummaryCard(cards_row, "Cette semaine")
        self.card_month = SummaryCard(cards_row, "Ce mois-ci")
        self.card_year = SummaryCard(cards_row, "Cette année")
        self.card_total = SummaryCard(cards_row, "Depuis le début")
        for card in (self.card_week, self.card_month, self.card_year, self.card_total):
            card.pack(side="left", fill="both", expand=True, padx=6)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)

        left = ttk.LabelFrame(mid, text="Temps de travail (TTE) par période", padding=12)
        left.pack(side="left", fill="both", expand=True, padx=12, pady=(0, 12))

        period_row = ttk.Frame(left)
        period_row.pack(fill="x", pady=(0, 8))
        ttk.Label(period_row, text="Regrouper par :").pack(side="left")
        self.period_var = tk.StringVar(value="Mois")
        for p in PERIODS:
            ttk.Radiobutton(period_row, text=p, value=p, variable=self.period_var,
                             command=self.refresh).pack(side="left", padx=4)

        self.chart_scroll = ScrollableFrame(left)
        self.chart_scroll.pack(fill="both", expand=True)
        self.chart_holder = self.chart_scroll.inner

        right = ttk.LabelFrame(mid, text="Trajets les plus fréquents", padding=12)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=(0, 12))

        scope_row = ttk.Frame(right)
        scope_row.pack(fill="x", pady=(0, 8))
        ttk.Label(scope_row, text="Période :").pack(side="left")
        self.trajet_scope_var = tk.StringVar(value="Toutes les périodes")
        ttk.Combobox(
            scope_row, textvariable=self.trajet_scope_var, state="readonly", width=20,
            values=["Toutes les périodes", "Cette année", "Ce mois-ci", "Cette semaine"],
        ).pack(side="left", padx=4)
        self.trajet_scope_var.trace_add("write", lambda *a: self.refresh())

        self.trajet_scroll = ScrollableFrame(right)
        self.trajet_scroll.pack(fill="both", expand=True)
        self.trajet_holder = self.trajet_scroll.inner

    def refresh(self):
        week_start, week_end = _current_week_range()
        month_start, month_end = _current_month_range()
        year_start, year_end = _current_year_range()

        week_sum = stats.summary_for_period(week_start, week_end)
        month_sum = stats.summary_for_period(month_start, month_end)
        year_sum = stats.summary_for_period(year_start, year_end)
        total_sum = stats.summary_for_period()

        def _sub_text(period_sum) -> str:
            text = f"{period_sum.days} jour(s)"
            if period_sum.last_minute_count:
                text += f" · {period_sum.last_minute_count} prime(s) dernière minute"
            return text

        self.card_week.set(hours_to_hm(week_sum.tte), _sub_text(week_sum))
        self.card_month.set(hours_to_hm(month_sum.tte), _sub_text(month_sum))
        self.card_year.set(hours_to_hm(year_sum.tte), _sub_text(year_sum))
        self.card_total.set(hours_to_hm(total_sum.tte), _sub_text(total_sum))

        for child in self.chart_holder.winfo_children():
            child.destroy()
        period = self.period_var.get()
        if period == "Semaine":
            periods = stats.weekly_totals()
        elif period == "Année":
            periods = stats.yearly_totals()
        else:
            periods = stats.monthly_totals()
        periods = periods[-16:]
        if not periods:
            ttk.Label(self.chart_holder, text="Aucune donnée pour le moment.").pack(anchor="w", pady=8)
        else:
            max_tte = max((p.tte for p in periods), default=0) or 1
            for p in reversed(periods):
                BarRow(self.chart_holder, p.label, hours_to_hm(p.tte), p.tte / max_tte).pack(
                    fill="x", pady=2, padx=2
                )
        self.chart_scroll.scroll_to_top()

        for child in self.trajet_holder.winfo_children():
            child.destroy()
        scope = self.trajet_scope_var.get()
        if scope == "Cette année":
            t_start, t_end = year_start, year_end
        elif scope == "Ce mois-ci":
            t_start, t_end = month_start, month_end
        elif scope == "Cette semaine":
            t_start, t_end = week_start, week_end
        else:
            t_start = t_end = None
        top = stats.top_trajets(t_start, t_end, limit=15)
        if not top:
            ttk.Label(self.trajet_holder, text="Aucun trajet enregistré pour cette période.").pack(
                anchor="w", pady=8
            )
        else:
            max_count = max(t.count for t in top) or 1
            for t in top:
                BarRow(self.trajet_holder, t.label, f"{t.count}×", t.count / max_count, color=SUCCESS).pack(
                    fill="x", pady=2, padx=2
                )
        self.trajet_scroll.scroll_to_top()
