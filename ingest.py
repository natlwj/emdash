"""
EMDASH :: ingest.py
===================================================================
ALL FETCHERS. Each source: fetch -> clean -> core.write_rows().
Driven by config.FEATURE_FLAGS. run_all() loops enabled sources.

NEW in this version:
    - skip_existing (default ON): if a country/series already has
      data in the DB, DON'T re-download it. Makes re-runs fast and
      lets failed pulls get filled without re-pulling everything.
    - auto-retry on timeout (2 tries, 45s) -> fewer World Bank fails.
    - --refresh flag: force re-pull everything (overwrite).
    - ingest_log freshness stamp per source.

Usage:
    python ingest.py                 # normal: fill gaps, skip filled
    python ingest.py --only worldbank
    python ingest.py --skip-market
    python ingest.py --refresh       # force full re-pull (overwrite)
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
TIMEOUT = 45          # was 30; bumped to reduce timeouts
RETRIES = 2           # try each request up to twice


# ===================================================================
# shared HTTP helper with retry
# ===================================================================
def _get_json(url: str):
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))   # small backoff before retry
    raise last


# ===================================================================
# [1] WORLD BANK  (macro, annual)
# ===================================================================
def _wb_one(iso3, code, years) -> pd.DataFrame:
    end = dt.date.today().year
    start = end - years
    url = (f"{WB_BASE}/country/{iso3}/indicator/{code}"
           f"?date={start}:{end}&format=json&per_page=1000")
    try:
        payload = _get_json(url)
    except Exception as e:
        print(f"    [WB] {iso3} {code} FAILED: {e}")
        return pd.DataFrame(columns=["date", "value"])
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        return pd.DataFrame(columns=["date", "value"])
    rows = [(f"{o['date']}-12-31", float(o["value"]))
            for o in payload[1] if o.get("value") is not None]
    return pd.DataFrame(rows, columns=["date", "value"])


def fetch_worldbank(years=None, skip_existing=True, replace=False) -> int:
    years = years or config.HISTORY["macro_years"]
    print(f"[ingest] World Bank -- {years}y annual macro "
          f"(skip_existing={skip_existing})")
    total = 0
    for iso3, name, *_ in config.COUNTRIES:
        for label, code in config.WB_INDICATORS.items():
            if skip_existing and core.has_macro(iso3, label):
                continue
            df = _wb_one(iso3, code, years)
            if df.empty:
                continue
            rows = [(r.date, iso3, label, r.value, "worldbank", "annual")
                    for r in df.itertuples(index=False)]
            total += core.write_rows("macro_data", rows, replace=replace)
            time.sleep(0.04)
        print(f"    [WB] {iso3} {name}: done")
    core.log_ingest("worldbank", total)
    print(f"[ingest] World Bank new rows: {total}")
    return total


# ===================================================================
# [2] DBNOMICS  (macro, monthly)
# ===================================================================
def _dbnomics_one(provider, dataset, series) -> pd.DataFrame:
    url = (f"https://api.db.nomics.world/v22/series/"
           f"{provider}/{dataset}/{series}?observations=1")
    try:
        js = _get_json(url)
        docs = js["series"]["docs"]
        if not docs:
            return pd.DataFrame(columns=["date", "value"])
        d = docs[0]
        rows = []
        for p, v in zip(d.get("period", []), d.get("value", [])):
            if v is None or v == "NA":
                continue
            try:
                dtp = pd.Period(p, freq="M").to_timestamp("M")
                rows.append((dtp.strftime("%Y-%m-%d"), float(v)))
            except Exception:
                try:
                    rows.append((f"{int(p)}-12-31", float(v)))
                except Exception:
                    continue
        return pd.DataFrame(rows, columns=["date", "value"])
    except Exception as e:
        print(f"    [DBN] {provider}/{dataset}/{series} FAILED: {e}")
        return pd.DataFrame(columns=["date", "value"])


def fetch_dbnomics(skip_existing=True, replace=False) -> int:
    print("[ingest] DBnomics -- monthly macro")
    total = 0
    for label, (provider, dataset, mask) in config.DBN_SERIES.items():
        for iso3, name, *_ in config.COUNTRIES:
            if skip_existing and core.has_macro(iso3, label):
                continue
            iso2 = config.iso3_to_iso2(iso3)
            if not iso2:
                continue
            df = _dbnomics_one(provider, dataset, mask.format(iso2=iso2))
            if df.empty:
                continue
            rows = [(r.date, iso3, label, r.value, "dbnomics", "monthly")
                    for r in df.itertuples(index=False)]
            total += core.write_rows("macro_data", rows, replace=replace)
            time.sleep(0.05)
        print(f"    [DBN] {label}: done")
    core.log_ingest("dbnomics", total)
    print(f"[ingest] DBnomics new rows: {total}")
    return total


# ===================================================================
# [3][4] YAHOO  (FX / commodities / global)
# ===================================================================
def _yahoo(ticker, years) -> pd.DataFrame:
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


def fetch_yahoo_fx(years=None, skip_existing=True, replace=False) -> int:
    years = years or config.HISTORY["market_years"]
    print(f"[ingest] Yahoo FX -- {years}y daily (skip_existing={skip_existing})")
    total = 0
    for iso3, name, _, _, fx in config.COUNTRIES:
        if not fx:
            continue
        if skip_existing and core.has_market(iso3, "FX"):
            continue
        df = _yahoo(fx, years)
        if df.empty:
            print(f"    [YF] {iso3} {fx}: no data")
            continue
        rows = [(r.date, iso3, "FX", r.value, "yahoo_fx")
                for r in df.itertuples(index=False)]
        total += core.write_rows("market_data", rows, replace=replace)
        print(f"    [YF] {iso3} {fx}: {len(rows)}")
    core.log_ingest("yahoo_fx", total)
    print(f"[ingest] Yahoo FX new rows: {total}")
    return total


def fetch_commodities(years=None, skip_existing=True, replace=False) -> int:
    years = years or config.HISTORY["market_years"]
    print(f"[ingest] Yahoo commodities -- {years}y daily")
    total = 0
    for label, ticker in config.COMMODITIES.items():
        if skip_existing and core.has_commodity(label):
            continue
        df = _yahoo(ticker, years)
        if df.empty:
            print(f"    [YF] {label} {ticker}: no data")
            continue
        rows = [(r.date, label, r.value, "yahoo_cmdty")
                for r in df.itertuples(index=False)]
        total += core.write_rows("commodity_data", rows, replace=replace)
        print(f"    [YF] {label}: {len(rows)}")

    print("[ingest] Yahoo global market proxies")
    for label, ticker in config.MARKET_TICKERS.items():
        if skip_existing and core.has_global(label):
            continue
        df = _yahoo(ticker, years)
        if df.empty:
            print(f"    [YF] {label} {ticker}: no data")
            continue
        rows = [(r.date, label, r.value, "yahoo_cmdty")
                for r in df.itertuples(index=False)]
        total += core.write_rows("global_market", rows, replace=replace)
        print(f"    [YF] {label}: {len(rows)}")
    core.log_ingest("yahoo_cmdty", total)
    print(f"[ingest] commodities+global new rows: {total}")
    return total


# ===================================================================
# [5] SEED LOADER
# ===================================================================
def load_seed(replace=False) -> int:
    print("[ingest] seed loader -- CSVs in seed/")
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
            total += core.write_rows("seed_data", rows, replace=replace)
            print(f"    [seed] {csv.name}: {len(rows)}")
        except Exception as e:
            print(f"    [seed] {csv.name} FAILED: {e}")
    print(f"[ingest] seed rows: {total}")
    return total


# ===================================================================
# [6] PHASE-4 STUBS
# ===================================================================
def fetch_gdelt(**kw):       print("[ingest] GDELT stub");        return 0
def fetch_predmarkets(**kw): print("[ingest] predmarkets stub");  return 0
def fetch_trends(**kw):      print("[ingest] Trends stub");       return 0


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
    "seed":        (None,                 load_seed),
}


def run_all(only=None, skip_market=False, refresh=False) -> None:
    core.init_db()
    skip_existing = not refresh          # --refresh forces full re-pull
    for key, (flag, fn) in _DISPATCH.items():
        if only and key not in only:
            continue
        if skip_market and key in ("yahoo_fx", "commodities"):
            continue
        if flag is not None and not config.FEATURE_FLAGS.get(flag, False):
            if not only:
                continue
        if key == "seed":
            fn(replace=refresh)
        else:
            fn(skip_existing=skip_existing, replace=refresh)
    print("[ingest] table counts:", core.table_counts())
    print("[ingest] done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--skip-market", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="force full re-pull (overwrite existing)")
    args = ap.parse_args()
    run_all(only=args.only, skip_market=args.skip_market, refresh=args.refresh)
