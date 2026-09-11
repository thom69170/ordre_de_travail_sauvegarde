"""Accès SQLite - stockage local des ordres de travail."""
from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone

from app.models import SUMMARY_FIELD_NAMES, WorkOrder
from app.paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    driver_name TEXT DEFAULT '',
    matricule TEXT DEFAULT '',
    source_filename TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    tps REAL DEFAULT 0,
    tad REAL DEFAULT 0,
    autres_temps REAL DEFAULT 0,
    tte REAL DEFAULT 0,
    hlr50 REAL DEFAULT 0,
    hlr100 REAL DEFAULT 0,
    ampli REAL DEFAULT 0,
    amp_lt12 REAL DEFAULT 0,
    amp_12_13 REAL DEFAULT 0,
    amp_gt13 REAL DEFAULT 0,
    rcn REAL DEFAULT 0,
    repas REAL DEFAULT 0,
    primes REAL DEFAULT 0,
    dim_travail REAL DEFAULT 0,
    ferie REAL DEFAULT 0,
    tps_oc REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_work_orders_date ON work_orders(date);

CREATE TABLE IF NOT EXISTS trajets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    label TEXT NOT NULL,
    occurrences INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_trajets_date ON trajets(date);
CREATE INDEX IF NOT EXISTS idx_trajets_label ON trajets(label);
CREATE INDEX IF NOT EXISTS idx_trajets_work_order ON trajets(work_order_id);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _row_to_work_order(row: sqlite3.Row) -> WorkOrder:
    data = {k: row[k] for k in row.keys() if k != "id"}
    wo = WorkOrder(id=row["id"], **data)
    return wo


def insert_work_order(wo: WorkOrder) -> int:
    with connect() as conn:
        cols = ["date", "driver_name", "matricule", "source_filename", "source_type",
                "notes", "created_at"] + SUMMARY_FIELD_NAMES
        values = [getattr(wo, c) for c in cols]
        if not wo.created_at:
            values[cols.index("created_at")] = datetime.now(timezone.utc).isoformat()
        placeholders = ", ".join(["?"] * len(cols))
        cur = conn.execute(
            f"INSERT INTO work_orders ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        work_order_id = cur.lastrowid
        _replace_trajets(conn, work_order_id, wo.date, wo.trajets)
        return work_order_id


def update_work_order(wo: WorkOrder) -> None:
    if wo.id is None:
        raise ValueError("work order without id cannot be updated")
    with connect() as conn:
        cols = ["date", "driver_name", "matricule", "source_filename", "source_type",
                "notes"] + SUMMARY_FIELD_NAMES
        assignments = ", ".join(f"{c} = ?" for c in cols)
        values = [getattr(wo, c) for c in cols] + [wo.id]
        conn.execute(f"UPDATE work_orders SET {assignments} WHERE id = ?", values)
        _replace_trajets(conn, wo.id, wo.date, wo.trajets)


def delete_work_order(work_order_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM work_orders WHERE id = ?", (work_order_id,))


def _replace_trajets(conn: sqlite3.Connection, work_order_id: int, date: str, labels: list[str]) -> None:
    conn.execute("DELETE FROM trajets WHERE work_order_id = ?", (work_order_id,))
    counts = Counter(label.strip() for label in labels if label and label.strip())
    for label, occurrences in counts.items():
        conn.execute(
            "INSERT INTO trajets (work_order_id, date, label, occurrences) VALUES (?, ?, ?, ?)",
            (work_order_id, date, label, occurrences),
        )


def get_work_order(work_order_id: int) -> WorkOrder | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()
        if row is None:
            return None
        wo = _row_to_work_order(row)
        trajet_rows = conn.execute(
            "SELECT label, occurrences FROM trajets WHERE work_order_id = ?", (work_order_id,)
        ).fetchall()
        trajets = []
        for r in trajet_rows:
            trajets.extend([r["label"]] * r["occurrences"])
        wo.trajets = trajets
        return wo


def get_work_order_by_date(date: str) -> WorkOrder | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM work_orders WHERE date = ?", (date,)).fetchone()
        if row is None:
            return None
    return get_work_order(row["id"])


def list_work_orders(start_date: str | None = None, end_date: str | None = None) -> list[WorkOrder]:
    query = "SELECT id FROM work_orders"
    conditions = []
    params: list[str] = []
    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY date DESC"
    with connect() as conn:
        ids = [r["id"] for r in conn.execute(query, params).fetchall()]
    return [wo for wo in (get_work_order(i) for i in ids) if wo is not None]
