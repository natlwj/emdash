"""
EMDASH :: ingest.py
===================================================================
ALL FETCHERS, one file. Each source is a function with the same
shape: fetch -> clean -> return tidy rows -> core.write_rows().

Driven by config.FEATURE_FLAGS. run_all() loops enabled sources.
To add a source: write one fetch_* function + one FEATURE_FLAG +
one SOURCES row in config. Nothing else changes.

Sections:
    [1] WORLD BANK        (macro, annual)      -> macro_data
    [2] DBNOMICS          (macro, monthly)     -> macro_data
    [3] YAHOO FX          (market, daily)      -> market_data
    [4] YAHOO COMMODITIES + GLOBAL (daily)     -> commodity_data / global_market
    [5] SEED LOADER       (Bloomberg CSVs)     -> seed_data
    [6] PHASE-4 STUBS     (GDELT/predmkts/trends)
    [7] run_all()

Usage:
    python ingest.py                # respects FEATURE_FLAGS
    python ingest.py --only worldbank yahoo_fx
    python ingest.py --skip-market
===================================================================
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import pandas as pd
import requests

import config
import core

WB_BASE = "https://api.worldbank.org/v2"


# ===================================================================
# [1] WORLD BANK  (macro, annual)
# ===================================================================
def _wb_one(iso3: str, code: str, years: int) -> pd.DataFrame:
    end = dt.date.today().year
    start = end - years
    url = (f"{WB_BASE}/country/{iso3}/indicator/{code}"
           f"?date={start}:{end}&format=json&per_page=1000")
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"    [WB] {iso3} {code} FAILED: {e}")
        return pd.DataFrame(columns=["date", "value"])
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        return pd.DataFrame(columns=["date", "value"])
    rows = [(f"{o['date']}-12-31", float(o["value"]))
            for o in payload[1] if o.get("value") is not None]
    return pd.DataFrame(rows, columns=["date", "value"])


def fetch_worldbank(years: int | None = None) -> int:
    years = years or config.HISTORY["macro_years"]
    print(f"[ingest] World Bank -- {years}y annual macro")
    total = 0
    for iso3, name, *_ in config.COUNTRIES:
        for label, code in config.WB_INDICATORS.items():
            df = _wb_one(iso3, code, years)
            if df.empty:
                continue
            rows = [(r.date, iso3, label, r.value, "worldbank", "annual")
                    for r in df.itertuples(index=False)]
            total += core.write_rows("macro_data", rows)
            time.sleep(0.04)
        print(f"    [WB] {iso3} {name}: done")
    print(f"[ingest] World Bank rows: {total}")
    return total


# ===================================================================
# [2] DBNOMICS  (macro, monthly)  -- IMF/OECD/ECB via one aggregator
# ===================================================================
def _dbnomics_one(provider: str, dataset: str, series: str) -> pd.DataFrame:
    """Hit DBnomics REST API for a single series code."""
    url = (f"https://api.db.nomics.world/v22/series/"
           f"{provider}/{dataset}/{series}?observations=1")
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        js = r.json()
        docs = js["series"]["docs"]
        if not docs:
            return pd.DataFrame(columns=["date", "value"])
        d = docs[0]
        periods = d.get("period", [])
        values = d.get("value", [])
        rows = []
        for p, v in zip(periods, values):
            if v is None or v == "NA":
                continue
            # DBnomics monthly period like '2025-01' -> month-end date
            try:
                dtp = pd.Period(p, freq="M").to_timestamp("M")
                rows.append((dtp.strftime("%Y-%m-%d"), float(v)))
            except Exception:
                # annual or other; best-effort year-end
                try:
                    rows.append((f"{int(p)}-12-31", float(v)))
                except Exception:
                    continue
        return pd.DataFrame(rows, columns=["date", "value"])
    except Exception as e:
        print(f"    [DBN] {provider}/{dataset}/{series} FAILED: {e}")
        return pd.DataFrame(columns=["date", "value"])


def fetch_dbnomics() -> int:
    print("[ingest] DBnomics -- monthly macro (IMF/OECD/ECB agg.)")
    total = 0
    for label, (provider, dataset, mask) in config.DBN_SERIES.items():
        for iso3, name, *_ in config.COUNTRIES:
            iso2 = config.iso3_to_iso2(iso3)
            if not iso2:
                continue
            series = mask.format(iso2=iso2)
            df = _dbnomics_one(provider, dataset, series)
            if df.empty:
                continue
            rows = [(r.date, iso3, label, r.value, "dbnomics", "monthly")
                    for r in df.itertuples(index=False)]
            total += core.write_rows("macro_data", rows)
            time.sleep(0.05)
        print(f"    [DBN] {label}: done")
    print(f"[ingest] DBnomics rows: {total}")
    return total


# ===================================================================
# [3] YAHOO FX  (market, daily)
# ===================================================================
def _yahoo(ticker: str, years: int) -> pd.DataFrame:
    import yfinance as yf
    try:
        df = yf.download(ticker, period=f"{years}y", interval="1d",
                         progress=False, auto_adjust=False, threads=False)
    except Exception as e:
        print(f"    [YF] {ticker} FAILED: {e}")
        return pd.DataFrame(columns=["date", "value"])
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "value"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    if "Close" not in df.columns:
        return pd.DataFrame(columns=["date", "value"])
    out = df[["Close"]].reset_index()
    out.columns = ["date", "value"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out.dropna()


def fetch_yahoo_fx(years: int | None = None) -> int:
    years = years or config.HISTORY["market_years"]
    print(f"[ingest] Yahoo FX -- {years}y daily")
    total = 0
    for iso3, name, _, _, fx in config.COUNTRIES:
        if not fx:
            continue
        df = _yahoo(fx, years)
        if df.empty:
            print(f"    [YF] {iso3} {fx}: no data")
            continue
        rows = [(r.date, iso3, "FX", r.value, "yahoo_fx")
                for r in df.itertuples(index=False)]
        total += core.write_rows("market_data", rows)
        print(f"    [YF] {iso3} {fx}: {len(rows)}")
    print(f"[ingest] Yahoo FX rows: {total}")
    return total


# ===================================================================
# [4] YAHOO COMMODITIES + GLOBAL MARKET  (daily)
# ===================================================================
def fetch_commodities(years: int | None = None) -> int:
    years = years or config.HISTORY["market_years"]
    print(f"[ingest] Yahoo commodities -- {years}y daily")
    total = 0
    for label, ticker in config.COMMODITIES.items():
        df = _yahoo(ticker, years)
        if df.empty:
            print(f"    [YF] {label} {ticker}: no data")
            continue
        rows = [(r.date, label, r.value, "yahoo_cmdty")
                for r in df.itertuples(index=False)]
        total += core.write_rows("commodity_data", rows)
        print(f"    [YF] {label}: {len(rows)}")
    print(f"[ingest] commodity rows: {total}")

    print("[ingest] Yahoo global market proxies")
    gtotal = 0
    for label, ticker in config.MARKET_TICKERS.items():
        df = _yahoo(ticker, years)
        if df.empty:
            print(f"    [YF] {label} {ticker}: no data")
            continue
        rows = [(r.date, label, r.value, "yahoo_cmdty")
                for r in df.itertuples(index=False)]
        gtotal += core.write_rows("global_market", rows)
        print(f"    [YF] {label}: {len(rows)}")
    print(f"[ingest] global_market rows: {gtotal}")
    return total + gtotal


# ===================================================================
# [5] SEED LOADER  -- one-time Bloomberg exports dropped in seed/*.csv
# Expected CSV columns: date, iso3, series, value[, note]
# ===================================================================
def load_seed() -> int:
    print("[ingest] seed loader -- Bloomberg/manual CSVs in seed/")
    total = 0
    if not config.SEED_DIR.exists():
        print("    (no seed dir)")
        return 0
    for csv in sorted(config.SEED_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(csv)
            df.columns = [c.strip().lower() for c in df.columns]
            if "note" not in df.columns:
                df["note"] = csv.stem
            rows = [(str(r.date), str(r.iso3), str(r.series),
                     float(r.value), str(r.note))
                    for r in df.itertuples(index=False)]
            total += core.write_rows("seed_data", rows)
            print(f"    [seed] {csv.name}: {len(rows)}")
        except Exception as e:
            print(f"    [seed] {csv.name} FAILED: {e}")
    print(f"[ingest] seed rows: {total}")
    return total


# ===================================================================
# [6] PHASE-4 STUBS  (kept minimal; flesh out when flags flip on)
# ===================================================================
def fetch_gdelt() -> int:
    print("[ingest] GDELT stub -- enable in Phase 4")
    return 0


def fetch_predmarkets() -> int:
    print("[ingest] prediction markets stub -- enable in Phase 4")
    return 0


def fetch_trends() -> int:
    print("[ingest] Google Trends stub -- enable in Phase 4")
    return 0


# ===================================================================
# [7] ORCHESTRATION
# ===================================================================
_DISPATCH = {
    "worldbank":   ("ingest_worldbank",   fetch_worldbank),
    "dbnomics":    ("ingest_dbnomics",    fetch_dbnomics),
    "yahoo_fx":    ("ingest_yahoo_fx",    fetch_yahoo_fx),
    "commodities": ("ingest_commodities", fetch_commodities),
    "gdelt":       ("ingest_gdelt",       fetch_gdelt),
    "predmarkets": ("ingest_predmarkets", fetch_predmarkets),
    "trends":      ("ingest_trends",      fetch_trends),
    "seed":        (None,                 load_seed),  # always allowed
}


def run_all(only=None, skip_market=False) -> None:
    core.init_db()
    for key, (flag, fn) in _DISPATCH.items():
        if only and key not in only:
            continue
        if skip_market and key in ("yahoo_fx", "commodities"):
            continue
        if flag is not None and not config.FEATURE_FLAGS.get(flag, False):
            if not only:
                continue
        fn()
    print("[ingest] table counts:", core.table_counts())
    print("[ingest] done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="subset of sources to run")
    ap.add_argument("--skip-market", action="store_true")
    args = ap.parse_args()
    run_all(only=args.only, skip_market=args.skip_market)
