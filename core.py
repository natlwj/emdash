"""
EMDASH :: core.py
===================================================================
THE SPINE. One SQLite file, one place to read/write it.

Public read API:
    get_conn(), get_series(), get_market(), get_commodity(),
    get_global(), get_latest(), get_panel(),
    countries_df(), tags_df(), table_counts()

NEW in this version -- "do I already have this?" checks so ingest
can skip data that's already stored (fast, gap-filling re-runs):
    has_macro(iso3, indicator)
    has_market(iso3, series)
    has_commodity(name)
    has_global(series)

Write helper (used by ingest.py):
    write_rows(table, rows, replace=False)
        replace=False -> INSERT OR IGNORE (keep what's there, add gaps)
        replace=True  -> INSERT OR REPLACE (overwrite / refresh)
===================================================================
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

import pandas as pd

import config


# -------------------------------------------------------------------
# CONNECTION
# -------------------------------------------------------------------
def get_conn(db_path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# -------------------------------------------------------------------
# SCHEMA
# -------------------------------------------------------------------
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS countries (
    iso3 TEXT PRIMARY KEY, name TEXT NOT NULL, desk TEXT NOT NULL,
    dm_em TEXT, fx_ticker TEXT
);
CREATE TABLE IF NOT EXISTS country_tags (
    iso3 TEXT NOT NULL, tag TEXT NOT NULL,
    PRIMARY KEY (iso3, tag),
    FOREIGN KEY (iso3) REFERENCES countries(iso3)
);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY, name TEXT, type TEXT, tier TEXT, frequency TEXT
);
CREATE TABLE IF NOT EXISTS macro_data (
    date TEXT NOT NULL, iso3 TEXT NOT NULL, indicator TEXT NOT NULL,
    value REAL, source_id TEXT, freq TEXT,
    PRIMARY KEY (date, iso3, indicator),
    FOREIGN KEY (iso3) REFERENCES countries(iso3)
);
CREATE TABLE IF NOT EXISTS market_data (
    date TEXT NOT NULL, iso3 TEXT NOT NULL, series TEXT NOT NULL,
    value REAL, source_id TEXT,
    PRIMARY KEY (date, iso3, series),
    FOREIGN KEY (iso3) REFERENCES countries(iso3)
);
CREATE TABLE IF NOT EXISTS commodity_data (
    date TEXT NOT NULL, commodity TEXT NOT NULL, value REAL, source_id TEXT,
    PRIMARY KEY (date, commodity)
);
CREATE TABLE IF NOT EXISTS global_market (
    date TEXT NOT NULL, series TEXT NOT NULL, value REAL, source_id TEXT,
    PRIMARY KEY (date, series)
);
CREATE TABLE IF NOT EXISTS predmarket_data (
    date TEXT NOT NULL, market_id TEXT NOT NULL, question TEXT,
    prob REAL, venue TEXT,
    PRIMARY KEY (date, market_id)
);
CREATE TABLE IF NOT EXISTS news (
    ts TEXT NOT NULL, source_id TEXT, tier TEXT, iso3_tags TEXT,
    headline TEXT, url TEXT, tone REAL,
    PRIMARY KEY (ts, url)
);
CREATE TABLE IF NOT EXISTS trends_data (
    date TEXT NOT NULL, iso3 TEXT NOT NULL, topic TEXT NOT NULL, value REAL,
    PRIMARY KEY (date, iso3, topic)
);
CREATE TABLE IF NOT EXISTS signals (
    date TEXT NOT NULL, iso3 TEXT NOT NULL, signal TEXT NOT NULL, value REAL,
    PRIMARY KEY (date, iso3, signal)
);
CREATE TABLE IF NOT EXISTS regime_state (
    date TEXT NOT NULL, engine TEXT NOT NULL, regime TEXT, probability REAL,
    PRIMARY KEY (date, engine)
);
CREATE TABLE IF NOT EXISTS seed_data (
    date TEXT NOT NULL, iso3 TEXT NOT NULL, series TEXT NOT NULL,
    value REAL, note TEXT,
    PRIMARY KEY (date, iso3, series)
);
CREATE TABLE IF NOT EXISTS ingest_log (
    source_id TEXT PRIMARY KEY, last_run TEXT, rows INTEGER
);
CREATE INDEX IF NOT EXISTS idx_macro_iso_ind ON macro_data(iso3, indicator);
CREATE INDEX IF NOT EXISTS idx_macro_date    ON macro_data(date);
CREATE INDEX IF NOT EXISTS idx_market_iso    ON market_data(iso3, series);
CREATE INDEX IF NOT EXISTS idx_news_ts       ON news(ts);
"""


def init_db(db_path=None) -> None:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.executescript(_SCHEMA_SQL)
    cur.executemany(
        "INSERT OR REPLACE INTO countries (iso3,name,desk,dm_em,fx_ticker) "
        "VALUES (?,?,?,?,?)", config.COUNTRIES)
    cur.executemany(
        "INSERT OR REPLACE INTO country_tags (iso3,tag) VALUES (?,?)",
        config.TAGS)
    cur.executemany(
        "INSERT OR REPLACE INTO sources (source_id,name,type,tier,frequency) "
        "VALUES (?,?,?,?,?)", config.SOURCES)
    conn.commit()
    conn.close()
    print(f"[core] initialised DB at {config.DB_PATH}")


# -------------------------------------------------------------------
# WRITE HELPER
# -------------------------------------------------------------------
_TABLE_COLS = {
    "macro_data":      "(date,iso3,indicator,value,source_id,freq)",
    "market_data":     "(date,iso3,series,value,source_id)",
    "commodity_data":  "(date,commodity,value,source_id)",
    "global_market":   "(date,series,value,source_id)",
    "predmarket_data": "(date,market_id,question,prob,venue)",
    "news":            "(ts,source_id,tier,iso3_tags,headline,url,tone)",
    "trends_data":     "(date,iso3,topic,value)",
    "signals":         "(date,iso3,signal,value)",
    "regime_state":    "(date,engine,regime,probability)",
    "seed_data":       "(date,iso3,series,value,note)",
}


def write_rows(table: str, rows: Sequence[tuple],
               replace: bool = False, db_path=None) -> int:
    """Bulk insert. replace=False keeps existing rows (INSERT OR IGNORE);
    replace=True overwrites them (INSERT OR REPLACE)."""
    if table not in _TABLE_COLS:
        raise ValueError(f"unknown table: {table}")
    rows = list(rows)
    if not rows:
        return 0
    cols = _TABLE_COLS[table]
    placeholders = ",".join(["?"] * (cols.count(",") + 1))
    verb = "REPLACE" if replace else "IGNORE"
    conn = get_conn(db_path)
    conn.executemany(
        f"INSERT OR {verb} INTO {table} {cols} VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()
    return len(rows)


# -------------------------------------------------------------------
# "DO I ALREADY HAVE THIS?"  -- lets ingest skip filled data
# -------------------------------------------------------------------
def _exists(query: str, params: tuple, db_path=None) -> bool:
    conn = get_conn(db_path)
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row is not None


def has_macro(iso3: str, indicator: str, db_path=None) -> bool:
    return _exists(
        "SELECT 1 FROM macro_data WHERE iso3=? AND indicator=? LIMIT 1",
        (iso3, indicator), db_path)


def has_market(iso3: str, series: str = "FX", db_path=None) -> bool:
    return _exists(
        "SELECT 1 FROM market_data WHERE iso3=? AND series=? LIMIT 1",
        (iso3, series), db_path)


def has_commodity(name: str, db_path=None) -> bool:
    return _exists(
        "SELECT 1 FROM commodity_data WHERE commodity=? LIMIT 1",
        (name,), db_path)


def has_global(series: str, db_path=None) -> bool:
    return _exists(
        "SELECT 1 FROM global_market WHERE series=? LIMIT 1",
        (series,), db_path)


def log_ingest(source_id: str, rows: int, db_path=None) -> None:
    """Record when a source last ran + how many rows (freshness stamp)."""
    import datetime as dt
    conn = get_conn(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO ingest_log (source_id,last_run,rows) "
        "VALUES (?,?,?)",
        (source_id, dt.datetime.now().isoformat(timespec="seconds"), rows))
    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# READ API
# -------------------------------------------------------------------
def get_series(iso3, indicator, db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date, value FROM macro_data "
                     "WHERE iso3=? AND indicator=? ORDER BY date",
                     conn, params=(iso3, indicator))
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_market(iso3, series="FX", db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date, value FROM market_data "
                     "WHERE iso3=? AND series=? ORDER BY date",
                     conn, params=(iso3, series))
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_commodity(name, db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date, value FROM commodity_data "
                     "WHERE commodity=? ORDER BY date",
                     conn, params=(name,))
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_global(series, db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date, value FROM global_market "
                     "WHERE series=? ORDER BY date",
                     conn, params=(series,))
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_latest(indicator, db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql(
        """
        SELECT m.iso3, m.value, m.date
        FROM macro_data m
        JOIN (SELECT iso3, MAX(date) AS mx FROM macro_data
              WHERE indicator=? GROUP BY iso3) t
          ON m.iso3=t.iso3 AND m.date=t.mx
        WHERE m.indicator=?
        """, conn, params=(indicator, indicator))
    conn.close()
    return df


def get_panel(indicator, db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date, iso3, value FROM macro_data WHERE indicator=?",
                     conn, params=(indicator,))
    conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="iso3", values="value")


def countries_df(desk=None, tag=None, db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    if tag:
        df = pd.read_sql("SELECT c.* FROM countries c "
                         "JOIN country_tags t ON c.iso3=t.iso3 WHERE t.tag=?",
                         conn, params=(tag,))
    elif desk:
        df = pd.read_sql("SELECT * FROM countries WHERE desk=?",
                         conn, params=(desk,))
    else:
        df = pd.read_sql("SELECT * FROM countries", conn)
    conn.close()
    return df


def tags_df(db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT * FROM country_tags", conn)
    conn.close()
    return df


def table_counts(db_path=None) -> dict:
    conn = get_conn(db_path)
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    out = {}
    for n in names:
        try:
            out[n] = conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
        except sqlite3.Error:
            out[n] = None
    conn.close()
    return out


if __name__ == "__main__":
    init_db()
    print("[core] table counts:", table_counts())
