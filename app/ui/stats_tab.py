"""Onglet 'Statistiques' : une période au choix (semaine / mois / année / tout) que l'on fait
défiler, ses chiffres clés, le temps de travail jour par jour, les trajets les plus fréquents et
un tableau de détail période par période."""
from __future__ import annotations

import math
import tkinter as tk
from datetime import date
from tkinter import ttk

from app import db, stats
from app.stats import format_km, hours_to_hm, short_date
from app.ui.common import ACCENT, BORDER, CARD_BG, TEXT_MUTED, ScrollableFrame

KIND_LABELS = [("week", "Semaine"), ("month", "Mois"), ("year", "Année"), ("all", "Tout")]
TABLE_TITLES = {"week": "Détail par semaine", "month": "Détail par mois",
                "year": "Détail par année", "all": "Détail par année"}
BAR_HOVER = "#003e7e"   # barre survolée : même teinte, plus foncée
TEXT = "#1c1c1c"
GRID = "#ececec"


def _order_day(wo) -> str:
    try:
        return short_date(date.fromisoformat(wo.date))
    except ValueError:
        return wo.date


class SummaryCard(ttk.Frame):
    """Chiffre clé : titre, grande valeur, deux lignes de précision."""

    def __init__(self, parent, title: str):
        super().__init__(parent, padding=(14, 10), style="Card.TFrame")
        ttk.Label(self, text=title, font=("Segoe UI", 9), foreground=TEXT_MUTED).pack(anchor="w")
        self.value_label = ttk.Label(self, text="—", font=("Segoe UI Semibold", 18))
        self.value_label.pack(anchor="w", pady=(2, 0))
        self.sub_label = ttk.Label(self, text="", font=("Segoe UI", 8), foreground=TEXT_MUTED)
        self.sub_label.pack(anchor="w")
        self.extra_label = ttk.Label(self, text="", font=("Segoe UI", 8), foreground=TEXT_MUTED)
        self.extra_label.pack(anchor="w")

    def set(self, value_text: str, sub_text: str = "", extra_text: str = ""):
        self.value_label.config(text=value_text)
        self.sub_label.config(text=sub_text)
        self.extra_label.config(text=extra_text)


class BarChart(tk.Canvas):
    """Barres verticales (une seule série : le temps de travail), avec graduations discrètes,
    ligne de moyenne et info-bulle au survol. Se redessine quand sa taille change."""

    LEFT, RIGHT, TOP, BOTTOM = 44, 14, 20, 38

    def __init__(self, parent, on_click=None):
        super().__init__(parent, background=CARD_BG, highlightthickness=0, height=200)
        self.points: list[stats.ChartPoint] = []
        self.average: float | None = None
        self.on_click = on_click
        self._slots: list[tuple[float, float]] = []  # (x0, x1) de chaque barre, pour le survol
        self._hover: int | None = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<Button-1>", self._on_click)

    def set_data(self, points: list[stats.ChartPoint], average: float | None = None):
        self.points = points
        self.average = average
        self._hover = None
        self._draw()

    # ------------------------------------------------------------------ dessin

    @staticmethod
    def _tick_step(maximum: float) -> float:
        for step in (0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500):
            if maximum / step <= 5:
                return step
        return 1000

    def _draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 80 or height < 80:
            return
        if not self.points or not any(p.value for p in self.points):
            self.create_text(width / 2, height / 2, fill=TEXT_MUTED, font=("Segoe UI", 10),
                             text="Aucun ordre de travail sur cette période.")
            self._slots = []
            return

        x0, x1 = self.LEFT, width - self.RIGHT
        y0, y1 = self.TOP, height - self.BOTTOM  # y1 = ligne de base
        maximum = max(p.value for p in self.points)
        step = self._tick_step(maximum)
        top_value = max(step, math.ceil(maximum / step) * step)

        def y_of(value: float) -> float:
            return y1 - (value / top_value) * (y1 - y0)

        # Graduations horizontales : discrètes, derrière les barres
        ticks = int(round(top_value / step))
        for i in range(ticks + 1):
            value = i * step
            y = y_of(value)
            self.create_line(x0, y, x1, y, fill=BORDER if i == 0 else GRID)
            text = f"{value:g}h".replace(".", ",")
            self.create_text(x0 - 8, y, text=text, anchor="e", fill=TEXT_MUTED, font=("Segoe UI", 8))

        count = len(self.points)
        slot = (x1 - x0) / count
        bar_w = max(3.0, min(slot - 2, slot * 0.68, 54))
        label_every = max(1, math.ceil(24 / slot))  # pas de libellés qui se chevauchent
        show_values = slot >= 46
        self._slots = []
        for i, p in enumerate(self.points):
            cx = x0 + slot * (i + 0.5)
            self._slots.append((x0 + slot * i, x0 + slot * (i + 1)))
            if p.value > 0:
                self.create_rectangle(
                    cx - bar_w / 2, y_of(p.value), cx + bar_w / 2, y1,
                    fill=BAR_HOVER if i == self._hover else ACCENT, width=0, tags=(f"bar{i}",),
                )
                if show_values:
                    self.create_text(cx, y_of(p.value) - 3, text=hours_to_hm(p.value), anchor="s",
                                     fill=TEXT, font=("Segoe UI", 8))
            if i % label_every == 0:
                self.create_text(cx, y1 + 5, text=p.label, anchor="n", justify="center",
                                 fill="#9a9a9a" if p.muted else TEXT_MUTED, font=("Segoe UI", 8))

        if self.average:
            y = y_of(self.average)
            self.create_line(x0, y, x1, y, fill=TEXT_MUTED, dash=(4, 3))
            # Libellé sur un petit fond blanc : il reste lisible même posé sur une barre.
            label = self.create_text(x1 - 4, y - 3, text=f"moyenne {hours_to_hm(self.average)}",
                                     anchor="se", fill=TEXT, font=("Segoe UI", 8))
            lx0, ly0, lx1, ly1 = self.bbox(label)
            self.create_rectangle(lx0 - 3, ly0 - 1, lx1 + 3, ly1 + 1, fill=CARD_BG, width=0)
            self.tag_raise(label)
        self._draw_tooltip()

    def _draw_tooltip(self):
        self.delete("tip")
        if self._hover is None or self._hover >= len(self.points):
            return
        p = self.points[self._hover]
        lines = [p.title] + p.lines
        if p.target:
            lines.append("Clic : ouvrir ce mois")
        sx0, sx1 = self._slots[self._hover]
        text_id = self.create_text(0, 0, text="\n".join(lines), anchor="nw", fill="#ffffff",
                                   font=("Segoe UI", 9), tags=("tip",))
        bx0, by0, bx1, by1 = self.bbox(text_id)
        w, h = bx1 - bx0 + 16, by1 - by0 + 12
        # À côté de la barre survolée (à droite si la place le permet), jamais dessus.
        x = sx1 + 6 if sx1 + 6 + w <= self.winfo_width() - 4 else max(4, sx0 - 6 - w)
        y = 4
        self.create_rectangle(x, y, x + w, y + h, fill="#2b2b2b", width=0, tags=("tip",))
        self.coords(text_id, x + 8, y + 6)
        self.tag_raise(text_id)

    # ------------------------------------------------------------------ survol et clic

    def _index_at(self, x: float) -> int | None:
        for i, (sx0, sx1) in enumerate(self._slots):
            if sx0 <= x < sx1:
                return i
        return None

    def _set_hover(self, index: int | None):
        if index == self._hover:
            return
        previous, self._hover = self._hover, index
        for i in (previous, index):
            if i is not None:
                self.itemconfig(f"bar{i}", fill=BAR_HOVER if i == index else ACCENT)
        target = index is not None and self.points[index].target is not None
        self.config(cursor="hand2" if target else "")
        self._draw_tooltip()

    def _on_motion(self, event):
        self._set_hover(self._index_at(event.x))

    def _on_click(self, event):
        index = self._index_at(event.x)
        if index is not None and self.points[index].target and self.on_click:
            self.on_click(*self.points[index].target)


class RankRow(ttk.Frame):
    """Une ligne du classement : libellé entier (sur 2 lignes s'il le faut), nombre à droite, et
    dessous une barre fine proportionnelle."""

    def __init__(self, parent, label: str, count: int, fraction: float):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.label = ttk.Label(self, text=label, anchor="w", justify="left", font=("Segoe UI", 9))
        self.label.grid(row=0, column=0, sticky="ew")
        ttk.Label(self, text=f"{count}×", anchor="e", font=("Segoe UI Semibold", 9)).grid(
            row=0, column=1, sticky="e", padx=(8, 0))
        track = tk.Frame(self, bg=GRID, height=6)
        track.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        tk.Frame(track, bg=ACCENT).place(relx=0, rely=0, relheight=1, relwidth=max(0.01, min(1.0, fraction)))
        self.bind("<Configure>", lambda e: self.label.config(wraplength=max(120, e.width - 60)))


class StatsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.kind = "month"
        self.anchor = date.today()
        self._anchor_chosen = False  # tant que l'utilisateur n'a pas navigué : dernier mois avec des données
        self._filling_table = False
        self._groups: dict[str, stats.PeriodGroup] = {}
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        bar = ttk.Frame(self, padding=(12, 10, 12, 4))
        bar.pack(fill="x")
        self.kind_var = tk.StringVar(value=self.kind)
        for kind, text in KIND_LABELS:
            ttk.Radiobutton(bar, text=text, value=kind, variable=self.kind_var,
                            command=self._on_kind_change).pack(side="left", padx=(0, 6))
        self.prev_btn = ttk.Button(bar, text="◀", width=3, command=lambda: self._step(-1))
        self.prev_btn.pack(side="left", padx=(16, 4))
        self.period_label = ttk.Label(bar, text="", font=("Segoe UI Semibold", 12), width=34, anchor="center")
        self.period_label.pack(side="left")
        self.next_btn = ttk.Button(bar, text="▶", width=3, command=lambda: self._step(1))
        self.next_btn.pack(side="left", padx=4)
        self.today_btn = ttk.Button(bar, text="Aujourd'hui", command=self._go_today)
        self.today_btn.pack(side="left", padx=(10, 0))

        cards = ttk.Frame(self, padding=(6, 4, 6, 6))
        cards.pack(fill="x")
        self.card_tte = SummaryCard(cards, "Temps de travail (TTE)")
        self.card_avg = SummaryCard(cards, "Moyenne par jour travaillé")
        self.card_ampli = SummaryCard(cards, "Amplitude moyenne")
        self.card_km = SummaryCard(cards, "Kilomètres")
        self.card_primes = SummaryCard(cards, "Repas et primes")
        for column, card in enumerate(
                (self.card_tte, self.card_avg, self.card_ampli, self.card_km, self.card_primes)):
            cards.columnconfigure(column, weight=1, uniform="cards")  # cinq cartes de même largeur
            card.grid(row=0, column=column, sticky="nsew", padx=6)

        # Tableau de détail en bas (hauteur fixe) ; le graphique et les trajets prennent le reste.
        self.table_frame = ttk.LabelFrame(self, text="Détail par mois", padding=8)
        self.table_frame.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        columns = ("periode", "jours", "tte", "moyenne", "ampli", "km", "repas", "dm")
        headings = {"periode": "Période", "jours": "Jours", "tte": "Temps de travail",
                    "moyenne": "Moyenne / jour", "ampli": "Amplitude moy.", "km": "Kilomètres",
                    "repas": "Repas", "dm": "Dernière minute"}
        widths = {"periode": 260, "jours": 60, "tte": 120, "moyenne": 110, "ampli": 110, "km": 100,
                  "repas": 70, "dm": 110}
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings",
                                 selectmode="browse", height=4)
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w" if col == "periode" else "center",
                             stretch=col == "periode")
        scroll = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_table_select)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        self.chart_frame = ttk.LabelFrame(mid, text="Temps de travail", padding=8)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=(0, 10))
        self.chart = BarChart(self.chart_frame, on_click=self._go)
        self.chart.pack(fill="both", expand=True)

        right = ttk.LabelFrame(mid, text="Les plus fréquents sur la période", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=(0, 10))
        mode_row = ttk.Frame(right)
        mode_row.pack(fill="x", pady=(0, 6))
        self.rank_var = tk.StringVar(value="trajets")
        ttk.Radiobutton(mode_row, text="Trajets", value="trajets", variable=self.rank_var,
                        command=self._fill_ranking).pack(side="left", padx=(0, 6))
        ttk.Radiobutton(mode_row, text="Lignes", value="lignes", variable=self.rank_var,
                        command=self._fill_ranking).pack(side="left")
        self.rank_total = ttk.Label(mode_row, text="", foreground=TEXT_MUTED, font=("Segoe UI", 8))
        self.rank_total.pack(side="right")
        self.rank_scroll = ScrollableFrame(right)
        self.rank_scroll.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ navigation

    def _go(self, kind: str, anchor: date):
        self.kind, self.anchor, self._anchor_chosen = kind, anchor, True
        self.kind_var.set(kind)
        self.refresh()

    def _on_kind_change(self):
        self.kind = self.kind_var.get()
        self.refresh()

    def _step(self, step: int):
        self._go(self.kind, stats.shift_anchor(self.kind, self.anchor, step))

    def _go_today(self):
        self._go(self.kind, date.today())

    def _on_table_select(self, _event=None):
        if self._filling_table:
            return
        selection = self.tree.selection()
        group = self._groups.get(selection[0]) if selection else None
        if group is not None and (group.kind, group.anchor) != (self.kind, self._period_start()):
            self._go(group.kind, group.anchor)

    def _period_start(self):
        return stats.period_bounds(self.kind, self.anchor)[0]

    # ------------------------------------------------------------------ données

    def refresh(self):
        orders = db.list_work_orders()
        if not self._anchor_chosen and orders:
            # À l'ouverture : la période la plus récente qui contient des données (pas un mois vide).
            dates = [wo.date for wo in orders if wo.date]
            try:
                latest = date.fromisoformat(max(dates))
                if not stats.in_period(orders, self.kind, date.today()):
                    self.anchor = latest
            except ValueError:
                pass
        self._orders = orders
        self._current = stats.in_period(orders, self.kind, self.anchor)

        navigable = self.kind != "all"
        self.period_label.config(text=stats.period_label(self.kind, self.anchor))
        for btn in (self.prev_btn, self.next_btn, self.today_btn):
            btn.config(state="normal" if navigable else "disabled")

        self._fill_cards()
        self._fill_chart()
        self._fill_ranking()
        self._fill_table()

    def _fill_cards(self):
        s = stats.summarize(self._current)
        days = f"{s.days} jour{'s' if s.days != 1 else ''} travaillé{'s' if s.days != 1 else ''}"

        previous_text = ""
        if self.kind != "all":
            prev_anchor = stats.shift_anchor(self.kind, self.anchor, -1)
            prev = stats.summarize(stats.in_period(self._orders, self.kind, prev_anchor))
            if prev.days:
                previous_text = f"Période précédente : {hours_to_hm(prev.tte)} ({prev.days} j)"
        self.card_tte.set(hours_to_hm(s.tte) if s.days else "—", days if s.days else "Aucun ordre de travail",
                          previous_text)

        if s.days:
            self.card_avg.set(
                hours_to_hm(s.avg_tte),
                f"Journée la plus longue : {hours_to_hm(s.longest.tte)}", f"({_order_day(s.longest)})")
            self.card_ampli.set(
                hours_to_hm(s.avg_ampli),
                f"Maximum : {hours_to_hm(s.widest.ampli)}", f"({_order_day(s.widest)})")
        else:
            self.card_avg.set("—")
            self.card_ampli.set("—")

        if s.km_totaux:
            self.card_km.set(
                format_km(s.km_totaux),
                f"dont {format_km(s.km_hlp)} HLP" if s.km_hlp else "",
                f"{format_km(s.km_totaux / s.km_days)} par jour ({s.km_days} Feuille{'s' if s.km_days > 1 else ''} de Route)")
        else:
            self.card_km.set("—", "Sur les Feuilles de Route uniquement" if s.days else "")

        indem = []
        if s.indem_coup:
            indem.append(f"indem. coupure {hours_to_hm(s.indem_coup)}")
        if s.indem_ampl:
            indem.append(f"indem. amplitude {hours_to_hm(s.indem_ampl)}")
        self.card_primes.set(
            f"{s.meal_count} repas" if s.days else "—",
            (f"{s.last_minute_count} changement{'s' if s.last_minute_count != 1 else ''} de dernière minute"
             if s.days else ""),
            " · ".join(indem))

    def _fill_chart(self):
        points = stats.chart_series(self._orders if self.kind in ("year", "all") else self._current,
                                    self.kind, self.anchor)
        worked = [p.value for p in points if p.value > 0]
        per = "par jour" if self.kind in ("week", "month") else "par mois"
        self.chart_frame.config(text=f"Temps de travail {per} — {stats.period_label(self.kind, self.anchor)}")
        # La moyenne n'a de sens qu'avec plusieurs barres.
        self.chart.set_data(points, sum(worked) / len(worked) if len(worked) > 1 else None)

    def _fill_ranking(self):
        holder = self.rank_scroll.inner
        for child in holder.winfo_children():
            child.destroy()
        by_ligne = self.rank_var.get() == "lignes"
        top = stats.top_lignes(self._current) if by_ligne else stats.top_trajets(self._current)
        total = sum(len(wo.trajets) for wo in self._current)
        self.rank_total.config(text=f"{total} trajet{'s' if total != 1 else ''} au total" if total else "")
        if not top:
            ttk.Label(holder, text="Aucun trajet enregistré sur cette période.",
                      foreground=TEXT_MUTED).pack(anchor="w", pady=8)
        else:
            maximum = max(t.count for t in top) or 1
            for t in top:
                RankRow(holder, t.label, t.count, t.count / maximum).pack(fill="x", pady=(0, 7), padx=(2, 8))
        self.rank_scroll.scroll_to_top()

    def _fill_table(self):
        table_kind = "year" if self.kind == "all" else self.kind
        self.table_frame.config(text=f"{TABLE_TITLES[self.kind]} (clic sur une ligne pour l'afficher)")
        self._filling_table = True
        try:
            self.tree.delete(*self.tree.get_children())
            self._groups = {}
            current_start = self._period_start()
            for group in stats.grouped(self._orders, table_kind):
                s = group.summary
                iid = self.tree.insert("", "end", values=(
                    group.label, s.days, hours_to_hm(s.tte), hours_to_hm(s.avg_tte),
                    hours_to_hm(s.avg_ampli), format_km(s.km_totaux) if s.km_totaux else "",
                    s.meal_count or "", s.last_minute_count or "",
                ))
                self._groups[iid] = group
                if self.kind != "all" and group.anchor == current_start:
                    self.tree.selection_set(iid)
                    self.tree.see(iid)
        finally:
            # <<TreeviewSelect>> est émis après coup : on ne relâche le garde qu'une fois traité.
            self.after_idle(self._release_table_guard)

    def _release_table_guard(self):
        self._filling_table = False
