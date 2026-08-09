"""
EMDASH :: core.py   (v2)
===================================================================
THE SPINE. One SQLite file, one place to read/write it.

Public read API:
    get_conn(), get_series(), get_market(), get_commodity(),
    get_global(), get_latest(), get_panel(),
    countries_df(), tags_df(), table_counts()

For the SQLite Store tab:
    coverage()             -> per (scope,key,field): n, first, last, source
    news_coverage()        -> news totals / tiers / per-source / per-desk /
                              tagged % / DEAD FEEDS
    has_coverage(iso,fld)  -> bool (dropdown grey-out)
    ingest_log_df()        -> per source: last_run, rows (freshness)

"Do I already have this?" checks (ingest skips filled data):
    has_macro / has_market / has_commodity / has_global

Maintenance:
    prune_news(days)       -> delete news older than N days (returns deleted)

Write helper (ingest.py):
    write_rows(table, rows, replace=False)
        replace=False -> INSERT OR IGNORE ; replace=True -> INSERT OR REPLACE
===================================================================
"""
from __future__ import annotations

import datetime as dt
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
# "DO I ALREADY HAVE THIS?"
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


# -------------------------------------------------------------------
# COVERAGE  (SQLite Store tab)
# -------------------------------------------------------------------
def coverage(db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    queries = [
        ("SELECT iso3 AS key,'macro' AS scope,indicator AS field,"
         "COUNT(*) n,MIN(date) first,MAX(date) last,MAX(source_id) source "
         "FROM macro_data GROUP BY iso3,indicator"),
        ("SELECT iso3 AS key,'market' AS scope,series AS field,"
         "COUNT(*) n,MIN(date) first,MAX(date) last,MAX(source_id) source "
         "FROM market_data GROUP BY iso3,series"),
        ("SELECT '-' AS key,'commodity' AS scope,commodity AS field,"
         "COUNT(*) n,MIN(date) first,MAX(date) last,MAX(source_id) source "
         "FROM commodity_data GROUP BY commodity"),
        ("SELECT '-' AS key,'global' AS scope,series AS field,"
         "COUNT(*) n,MIN(date) first,MAX(date) last,MAX(source_id) source "
         "FROM global_market GROUP BY series"),
    ]
    frames = []
    for sql in queries:
        try:
            frames.append(pd.read_sql(sql, conn))
        except Exception:
            pass
    conn.close()
    cols = ["key", "scope", "field", "n", "first", "last", "source"]
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)[cols]


def has_coverage(iso3: str, field: str, db_path=None) -> bool:
    return (has_macro(iso3, field, db_path)
            or has_market(iso3, field, db_path))


def ingest_log_df(db_path=None) -> pd.DataFrame:
    conn = get_conn(db_path)
    try:
        df = pd.read_sql("SELECT source_id, last_run, rows FROM ingest_log "
                         "ORDER BY last_run DESC", conn)
    except Exception:
        df = pd.DataFrame(columns=["source_id", "last_run", "rows"])
    conn.close()
    return df


def news_coverage(db_path=None) -> dict:
    """News stats for the SQLite Store tab: totals, tier + desk breakdown,
    per-source spans, tagged %, and DEAD FEEDS (configured in RSS_FEEDS but
    with zero rows -> likely bad URL / firewalled). Read-only."""
    conn = get_conn(db_path)
    try:
        df = pd.read_sql("SELECT source_id, tier, iso3_tags, ts FROM news", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    if df.empty:
        return {"total": 0, "by_tier": {}, "by_source": pd.DataFrame(),
                "span": ("-", "-"), "tagged": 0, "untagged": 0,
                "tagged_pct": 0.0, "by_desk": {}, "dead_feeds": []}

    desk_by_iso = {i: d for i, n, d, *_ in config.COUNTRIES}
    by_tier = df["tier"].value_counts().to_dict()
    by_source = (df.groupby("source_id")
                   .agg(n=("ts", "size"), first=("ts", "min"), last=("ts", "max"))
                   .reset_index().sort_values("n", ascending=False))
    tags = df["iso3_tags"].fillna("")
    tagged = int((tags.str.len() > 0).sum())
    untagged = len(df) - tagged

    desk_counts: dict = {}
    for s in tags:
        seen = set()
        for iso in [x for x in s.split(",") if x]:
            d = desk_by_iso.get(iso)
            if d and d not in seen:
                seen.add(d)
                desk_counts[d] = desk_counts.get(d, 0) + 1
    desk_counts["(no desk)"] = untagged

    present = set(df["source_id"].unique())
    configured = [f[0] for f in getattr(config, "RSS_FEEDS", [])]
    dead_feeds = [fid for fid in configured if fid not in present]

    return {"total": len(df), "by_tier": by_tier, "by_source": by_source,
            "span": (str(df["ts"].min())[:10], str(df["ts"].max())[:10]),
            "tagged": tagged, "untagged": untagged,
            "tagged_pct": round(100 * tagged / len(df), 1),
            "by_desk": desk_counts, "dead_feeds": dead_feeds}


# -------------------------------------------------------------------
# MAINTENANCE
# -------------------------------------------------------------------
def prune_news(days: int, db_path=None) -> int:
    """Delete news older than `days` days. Returns rows deleted."""
    cutoff = (dt.datetime.now() - dt.timedelta(days=int(days))).isoformat()
    conn = get_conn(db_path)
    cur = conn.execute("DELETE FROM news WHERE ts < ?", (cutoff,))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


if __name__ == "__main__":
    init_db()
    print("[core] table counts:", table_counts())
    nc = news_coverage()
    print(f"[core] news: {nc['total']} rows, tagged {nc['tagged_pct']}%")
