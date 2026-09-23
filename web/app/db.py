"""Accès PostgreSQL - stockage multi-utilisateur des ordres de travail, feuilles de paie et
comptes. Port du db.py SQLite de l'app desktop : mêmes fonctions, avec un user_id en plus pour
isoler les données de chaque chauffeur."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from app.config import DATABASE_URL
from app.models import SUMMARY_FIELD_NAMES, Payslip, WorkOrder, split_trajet

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
    tps_oc REAL DEFAULT 0,
    trajets_up_to_date INTEGER DEFAULT 0,
    last_minute_change INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_work_orders_user_date ON work_orders(user_id, date);

CREATE TABLE IF NOT EXISTS trajets (
    id SERIAL PRIMARY KEY,
    work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    label TEXT NOT NULL,
    occurrences INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_trajets_work_order ON trajets(work_order_id);

CREATE TABLE IF NOT EXISTS payslips (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    hs_25 REAL DEFAULT 0,
    hs_50 REAL DEFAULT 0,
    cumul_hs_25 REAL DEFAULT 0,
    cumul_hs_50 REAL DEFAULT 0,
    repos_differe REAL DEFAULT 0,
    source_filename TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    details_json TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_payslips_user_period ON payslips(user_id, period_start);

CREATE TABLE IF NOT EXISTS import_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_import_jobs_user ON import_jobs(user_id);
"""


@contextmanager
def connect():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)


# --- Utilisateurs ---------------------------------------------------------

def create_user(email: str, password_hash: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (%s, %s, %s) RETURNING id",
            (email.strip().lower(), password_hash, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        return row["id"]


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = %s", (email.strip().lower(),)
        ).fetchone()


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


# --- Ordres de travail ------------------------------------------------------

def _row_to_work_order(row: dict) -> WorkOrder:
    data = {k: row[k] for k in row.keys() if k not in ("id", "user_id", "trajets_up_to_date")}
    data["last_minute_change"] = bool(data.get("last_minute_change"))
    return WorkOrder(id=row["id"], **data)


def insert_work_order(user_id: int, wo: WorkOrder) -> int:
    with connect() as conn:
        cols = ["date", "driver_name", "matricule", "source_filename", "source_type",
                "notes", "created_at"] + SUMMARY_FIELD_NAMES + ["last_minute_change"]
        values = [getattr(wo, c) for c in cols]
        values[cols.index("last_minute_change")] = int(wo.last_minute_change)
        if not wo.created_at:
            values[cols.index("created_at")] = datetime.now(timezone.utc).isoformat()
        placeholders = ", ".join(["%s"] * len(cols))
        row = conn.execute(
            f"INSERT INTO work_orders (user_id, {', '.join(cols)}, trajets_up_to_date) "
            f"VALUES (%s, {placeholders}, 1) RETURNING id",
            [user_id] + values,
        ).fetchone()
        work_order_id = row["id"]
        _replace_trajets(conn, work_order_id, wo.date, wo.trajets)
        return work_order_id


def update_work_order(user_id: int, wo: WorkOrder) -> None:
    if wo.id is None:
        raise ValueError("work order without id cannot be updated")
    with connect() as conn:
        cols = ["date", "driver_name", "matricule", "source_filename", "source_type",
                "notes"] + SUMMARY_FIELD_NAMES + ["last_minute_change"]
        values = [getattr(wo, c) for c in cols]
        values[cols.index("last_minute_change")] = int(wo.last_minute_change)
        assignments = ", ".join(f"{c} = %s" for c in cols)
        values = values + [wo.id, user_id]
        conn.execute(
            f"UPDATE work_orders SET {assignments}, trajets_up_to_date = 1 "
            f"WHERE id = %s AND user_id = %s",
            values,
        )
        _replace_trajets(conn, wo.id, wo.date, wo.trajets)


def delete_work_order(user_id: int, work_order_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM work_orders WHERE id = %s AND user_id = %s", (work_order_id, user_id)
        )


def _replace_trajets(conn, work_order_id: int, date: str, labels: list[str]) -> None:
    conn.execute("DELETE FROM trajets WHERE work_order_id = %s", (work_order_id,))
    counts = Counter(label.strip() for label in labels if label and label.strip())
    for label, occurrences in counts.items():
        conn.execute(
            "INSERT INTO trajets (work_order_id, date, label, occurrences) VALUES (%s, %s, %s, %s)",
            (work_order_id, date, label, occurrences),
        )


def get_work_order(user_id: int, work_order_id: int) -> WorkOrder | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM work_orders WHERE id = %s AND user_id = %s", (work_order_id, user_id)
        ).fetchone()
        if row is None:
            return None
        wo = _row_to_work_order(row)
        trajet_rows = conn.execute(
            "SELECT label, occurrences FROM trajets WHERE work_order_id = %s", (work_order_id,)
        ).fetchall()
        trajets = []
        for r in trajet_rows:
            trajets.extend([r["label"]] * r["occurrences"])
        wo.trajets = trajets
        return wo


def list_known_lignes(user_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.label FROM trajets t "
            "JOIN work_orders w ON w.id = t.work_order_id WHERE w.user_id = %s",
            (user_id,),
        ).fetchall()
    lignes = {split_trajet(r["label"])[0] for r in rows}
    lignes.discard("")
    return sorted(lignes)


def list_work_orders(
    user_id: int, start_date: str | None = None, end_date: str | None = None
) -> list[WorkOrder]:
    query = "SELECT id FROM work_orders WHERE user_id = %s"
    params: list = [user_id]
    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)
    query += " ORDER BY date DESC"
    with connect() as conn:
        ids = [r["id"] for r in conn.execute(query, params).fetchall()]
    return [wo for wo in (get_work_order(user_id, i) for i in ids) if wo is not None]


# --- Feuilles de paie --------------------------------------------------------

def _row_to_payslip(row: dict) -> Payslip:
    return Payslip(**{k: row[k] for k in row.keys() if k != "user_id"})


def insert_payslip(user_id: int, p: Payslip) -> int:
    with connect() as conn:
        cols = ["period_start", "period_end", "hs_25", "hs_50", "cumul_hs_25", "cumul_hs_50",
                "repos_differe", "source_filename", "created_at", "details_json"]
        values = [getattr(p, c) for c in cols]
        if not p.created_at:
            values[cols.index("created_at")] = datetime.now(timezone.utc).isoformat()
        placeholders = ", ".join(["%s"] * len(cols))
        row = conn.execute(
            f"INSERT INTO payslips (user_id, {', '.join(cols)}) "
            f"VALUES (%s, {placeholders}) RETURNING id",
            [user_id] + values,
        ).fetchone()
        return row["id"]


def delete_payslip(user_id: int, payslip_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM payslips WHERE id = %s AND user_id = %s", (payslip_id, user_id)
        )


def get_payslip(user_id: int, payslip_id: int) -> Payslip | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM payslips WHERE id = %s AND user_id = %s", (payslip_id, user_id)
        ).fetchone()
    return _row_to_payslip(row) if row is not None else None


def list_payslips(user_id: int) -> list[Payslip]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM payslips WHERE user_id = %s ORDER BY period_start DESC", (user_id,)
        ).fetchall()
    return [_row_to_payslip(r) for r in rows]


# --- Imports en cours (extraction en arrière-plan) --------------------------

def create_import_job(token: str, user_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO import_jobs (id, user_id, status, created_at) VALUES (%s, %s, 'pending', %s)",
            (token, user_id, datetime.now(timezone.utc).isoformat()),
        )


def set_import_job_result(token: str, result: dict) -> None:
    import json as _json

    with connect() as conn:
        conn.execute(
            "UPDATE import_jobs SET status = 'done', result_json = %s WHERE id = %s",
            (_json.dumps(result, ensure_ascii=False), token),
        )


def set_import_job_error(token: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE import_jobs SET status = 'error', error_message = %s WHERE id = %s",
            (message, token),
        )


def get_import_job(user_id: int, token: str) -> dict | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM import_jobs WHERE id = %s AND user_id = %s", (token, user_id)
        ).fetchone()


def list_pending_import_jobs(user_id: int) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM import_jobs WHERE user_id = %s ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def delete_import_job(user_id: int, token: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM import_jobs WHERE id = %s AND user_id = %s", (token, user_id)
        )
