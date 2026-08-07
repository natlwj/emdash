"""
EMDASH :: ingest.py   (v3)
===================================================================
ALL FETCHERS. Each source: fetch -> clean -> core.write_rows().
Driven by config.FEATURE_FLAGS. run_all() loops enabled sources.

Kept from v1/v2 (unchanged behaviour):
    - skip_existing (default ON): if a country/series already has data, DON'T
      re-download it. Fast re-runs; failed pulls get filled without a full
      re-pull.
    - auto-retry on timeout (2 tries, 45s).
    - --refresh: force full re-pull (overwrite).
    - ingest_log freshness stamp per source.
    - FRED credit-spread collector (v2), split globals fetcher (v2), wired
      dead flags (v2), DEFAULT_FLAGS safety net (v2), loud GDELT pointer (v2).

------------------------------------------------------------------
WHAT CHANGED IN v3   (matches config.py v3)
------------------------------------------------------------------
1. TIME WINDOW IS A DATE, NOT A COUNT.
   Market collectors now pass yfinance start=config.MARKET_START ("1950-01-01"
   by default) instead of period="15y". The SOURCE still caps the real earliest
   date; this just asks for everything. World Bank uses config.MACRO_START_YEAR
   as the ?date= lower bound. HISTORY year-counts remain a fallback.
   ** skip_existing means lowering MARKET_START does NOT extend an already-
      populated series on a normal run. Use --refresh (or --only X --refresh)
      to overwrite with the longer history. A smart extend-backward check is
      planned for the core.py phase. **

2. NEW COLLECTOR: fetch_equities()  (config.EQUITY_INDICES)
   Per-country stock index -> market_data, series="EQUITY", source_id="yahoo_eq".
   A near-copy of fetch_yahoo_fx: iso3 in dict = pull; not in dict = no rows.

3. NEW COLLECTOR: fetch_yields()  (config.SOVEREIGN_YIELDS)
   Sovereign bond yields per country per tenor -> market_data, series
   "Y2"/"Y5"/"Y10"/"Y30". Each tenor is a ("fred"|"yahoo", id) spec, so a
   country can mix sources. US full curve already lives in globals (MARKET_
   TICKERS); this is the per-country layer.

4. NEW COLLECTOR: fetch_fred_fx()  (config.FX_FRED)
   Deep-history FX backfill from FRED's DEX* series (reach the 1970s-90s vs
   Yahoo's ~2003). Written to a SEPARATE series "FX_FRED" (NOT "FX") on
   purpose: some DEX* pairs are USD-per-LCY (inverted) vs Yahoo's LCY-per-USD,
   so mixing them into one series would corrupt direction. The core.py/app.py
   phase decides how to present/join FX vs FX_FRED; ingest just stores both
   cleanly and non-destructively.

5. THREE NEW FLAGS WIRED: ingest_yahoo_eq, ingest_yields, ingest_fred_fx.
   --only accepts: equities, yields, fred_fx.

Usage:
    python ingest.py                      # fill gaps, skip filled
    python ingest.py --list               # what would run, and why
    python ingest.py --only worldbank
    python ingest.py --only equities      # per-country stock indices
    python ingest.py --only yields        # sovereign bond yields
    python ingest.py --only fred_fx       # deep-history FX backfill
    python ingest.py --only globals       # DXY/VIX/MOVE/BTC + US curve
    python ingest.py --only fred          # credit spreads
    python ingest.py --only commodities --refresh   # settles COAL
    python ingest.py --skip-market
    python ingest.py --refresh            # force full re-pull (overwrite)
===================================================================
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import time

import pandas as pd
import requests

import config
import core

WB_BASE = "https://api.worldbank.org/v2"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
TIMEOUT = 45
RETRIES = 2

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 EMDASH-ingest/3.0")

# Market window (v3): a start DATE, not a year count.
MARKET_START = getattr(config, "MARKET_START", "1950-01-01")
MACRO_START_YEAR = int(getattr(config, "MACRO_START_YEAR", 1960))


# ===================================================================
# shared HTTP helpers with retry
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
            time.sleep(1.5 * (attempt + 1))
    raise last


def _get_text(url: str) -> str:
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": _UA})
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


# ===================================================================
# shared Yahoo helper  (v3: start-date aware)
# ===================================================================
def _yahoo(ticker, start=None, years=None) -> pd.DataFrame:
    """One Yahoo series -> DataFrame[date, value] (Close).

    v3: prefers start=MARKET_START (pull everything the source has) over a
    fixed year-count. Falls back to period="{years}y" if no start is given.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("    [YF] yfinance not installed -> pip install yfinance")
        return pd.DataFrame(columns=["date", "value"])
    try:
        if start:
            df = yf.download(ticker, start=start, interval="1d",
                             progress=False, auto_adjust=False, threads=False)
        else:
            yrs = years or config.HISTORY["market_years"]
            df = yf.download(ticker, period=f"{yrs}y", interval="1d",
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


# ===================================================================
# [1] WORLD BANK  (macro, annual)
# ===================================================================
def _wb_one(iso3, code, start_year, end_year) -> pd.DataFrame:
    url = (f"{WB_BASE}/country/{iso3}/indicator/{code}"
           f"?date={start_year}:{end_year}&format=json&per_page=2000")
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


def fetch_worldbank(skip_existing=True, replace=False) -> int:
    end = dt.date.today().year
    start = MACRO_START_YEAR
    print(f"[ingest] World Bank -- annual macro since {start} "
          f"(skip_existing={skip_existing})")
    total = 0
    for iso3, name, *_ in config.COUNTRIES:
        for label, code in config.WB_INDICATORS.items():
            if skip_existing and core.has_macro(iso3, label):
                continue
            df = _wb_one(iso3, code, start, end)
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
            print(f"    [DBN] {provider}/{dataset}/{series}: no series published")
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
                print(f"    [DBN] {iso3}: no ISO2 mapping in config -- skipped")
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
# [3] YAHOO  (FX)
# ===================================================================
def fetch_yahoo_fx(skip_existing=True, replace=False) -> int:
    print(f"[ingest] Yahoo FX -- daily since {MARKET_START} "
          f"(skip_existing={skip_existing})")
    total = 0
    for iso3, name, _, _, fx in config.COUNTRIES:
        if not fx:
            continue          # USA / dollarised / EUR users (app substitutes)
        if skip_existing and core.has_market(iso3, "FX"):
            continue
        df = _yahoo(fx, start=MARKET_START)
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


# ===================================================================
# [3b] YAHOO  (equity indices)  -- NEW in v3
# ===================================================================
def fetch_equities(skip_existing=True, replace=False) -> int:
    """Per-country stock index -> market_data, series='EQUITY'.

    config.EQUITY_INDICES holds only countries with a free Yahoo index; the
    rest are simply absent (no blank rows). Same shape as fetch_yahoo_fx.
    """
    idx = getattr(config, "EQUITY_INDICES", {})
    print(f"[ingest] Yahoo equity indices -- {len(idx)} markets, daily since "
          f"{MARKET_START} (skip_existing={skip_existing})")
    total = 0
    for iso3, ticker in idx.items():
        if skip_existing and core.has_market(iso3, "EQUITY"):
            continue
        df = _yahoo(ticker, start=MARKET_START)
        if df.empty:
            print(f"    [YF] {iso3} {ticker}: no data")
            continue
        rows = [(r.date, iso3, "EQUITY", r.value, "yahoo_eq")
                for r in df.itertuples(index=False)]
        total += core.write_rows("market_data", rows, replace=replace)
        print(f"    [YF] {iso3} {ticker}: {len(rows)}")
    core.log_ingest("yahoo_eq", total)
    print(f"[ingest] equity indices new rows: {total}")
    return total


# ===================================================================
# [3c] SOVEREIGN YIELDS  -- NEW in v3
# ===================================================================
_TENOR_SERIES = {"2Y": "Y2", "5Y": "Y5", "10Y": "Y10", "30Y": "Y30"}


def fetch_yields(skip_existing=True, replace=False) -> int:
    """Per-country government bond yields -> market_data, series Y2/Y5/Y10/Y30.

    config.SOVEREIGN_YIELDS[iso3] = {tenor: (src, id)} where src is 'fred' or
    'yahoo'. Each tenor is fetched independently, so partial curves are fine.
    """
    spec = getattr(config, "SOVEREIGN_YIELDS", {})
    n_series = sum(len(v) for v in spec.values())
    print(f"[ingest] Sovereign yields -- {n_series} series across "
          f"{len(spec)} countries (skip_existing={skip_existing})")
    total = 0
    for iso3, tenors in spec.items():
        for tenor, (src, ident) in tenors.items():
            series = _TENOR_SERIES.get(tenor, f"Y{tenor}")
            if skip_existing and core.has_market(iso3, series):
                continue
            if src == "fred":
                df = _fred_one(ident)
            elif src == "yahoo":
                df = _yahoo(ident, start=MARKET_START)
            else:
                print(f"    [YLD] {iso3} {tenor}: unknown source '{src}'")
                continue
            if df.empty:
                print(f"    [YLD] {iso3} {tenor} ({src}:{ident}): no data")
                continue
            source_id = "fred" if src == "fred" else "yahoo_yld"
            rows = [(r.date, iso3, series, r.value, source_id)
                    for r in df.itertuples(index=False)]
            total += core.write_rows("market_data", rows, replace=replace)
            print(f"    [YLD] {iso3} {tenor} ({src}): {len(rows)}")
            time.sleep(0.15)
    core.log_ingest("yields", total)
    print(f"[ingest] sovereign yields new rows: {total}")
    return total


# ===================================================================
# [4] YAHOO  (commodities)
# ===================================================================
def fetch_commodities(skip_existing=True, replace=False) -> int:
    """Commodity futures -> commodity_data.

    NOTE ON COAL: skip_existing checks 'has ANY rows', not 'is current'. COAL
    has rows, so a normal run always skips it. Prove staleness with:
        python ingest.py --only commodities --refresh
    """
    print(f"[ingest] Yahoo commodities -- daily since {MARKET_START} "
          f"(skip_existing={skip_existing})")
    total = 0
    for label, ticker in config.COMMODITIES.items():
        if skip_existing and core.has_commodity(label):
            continue
        df = _yahoo(ticker, start=MARKET_START)
        if df.empty:
            print(f"    [YF] {label} {ticker}: no data")
            continue
        rows = [(r.date, label, r.value, "yahoo_cmdty")
                for r in df.itertuples(index=False)]
        total += core.write_rows("commodity_data", rows, replace=replace)
        print(f"    [YF] {label}: {len(rows)}")
    core.log_ingest("yahoo_cmdty", total)
    print(f"[ingest] commodities new rows: {total}")
    return total


# ===================================================================
# [5] YAHOO  (global market gauges)
# ===================================================================
def fetch_globals(skip_existing=True, replace=False) -> int:
    """DXY / VIX / MOVE / SPX / EMB / BTC / US curve ... -> global_market.

    Run this after adding anything to config.MARKET_TICKERS (the MRC's gauges
    plus the US Treasury curve live here).
    """
    print(f"[ingest] Yahoo global gauges -- daily since {MARKET_START} "
          f"(skip_existing={skip_existing})")
    total = 0
    for label, ticker in config.MARKET_TICKERS.items():
        if skip_existing and core.has_global(label):
            continue
        df = _yahoo(ticker, start=MARKET_START)
        if df.empty:
            print(f"    [YF] {label} {ticker}: no data")
            continue
        rows = [(r.date, label, r.value, "yahoo_glob")
                for r in df.itertuples(index=False)]
        total += core.write_rows("global_market", rows, replace=replace)
        print(f"    [YF] {label}: {len(rows)}")
    core.log_ingest("yahoo_glob", total)
    print(f"[ingest] global gauges new rows: {total}")
    return total


# ===================================================================
# [6] FRED  (credit spreads)
# ===================================================================
def _fred_one(series_id: str) -> pd.DataFrame:
    """One FRED series via the public CSV endpoint (no API key).

    Header changed over the years ("DATE,<ID>" vs "observation_date,<ID>"), so
    take the FIRST column as date and SECOND as value by position. Missing
    observations are published as "." and dropped (never interpolated).
    """
    url = FRED_CSV.format(sid=series_id)
    try:
        text = _get_text(url)
    except Exception as e:
        print(f"    [FRED] {series_id} FAILED: {e}")
        return pd.DataFrame(columns=["date", "value"])
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as e:
        print(f"    [FRED] {series_id} unparseable CSV: {e}")
        return pd.DataFrame(columns=["date", "value"])
    if df.shape[1] < 2 or df.empty:
        print(f"    [FRED] {series_id}: empty / unexpected shape {df.shape}")
        return pd.DataFrame(columns=["date", "value"])
    out = df.iloc[:, :2].copy()
    out.columns = ["date", "value"]
    out["value"] = pd.to_numeric(out["value"], errors="coerce")   # "." -> NaN
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna()
    if out.empty:
        return pd.DataFrame(columns=["date", "value"])
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.reset_index(drop=True)


def fetch_fred(skip_existing=True, replace=False) -> int:
    """ICE BofA option-adjusted spreads -> global_market.

    mrc.py already registers IG_OAS / BBB_OAS / HY_OAS as optional gauges, so
    they start voting automatically once these rows exist -- no code change.
    FIREWALL: a ConnectionReset here is the office blocking fred.stlouisfed.org,
    not a config error (see config DATA GAPS).
    """
    series = getattr(config, "FRED_SERIES", {})
    if not series:
        print("[ingest] FRED -- nothing in config.FRED_SERIES")
        return 0
    print(f"[ingest] FRED -- {len(series)} credit-spread series "
          f"(skip_existing={skip_existing})")
    total = 0
    for label, sid in series.items():
        if skip_existing and core.has_global(label):
            continue
        df = _fred_one(sid)
        if df.empty:
            print(f"    [FRED] {label} ({sid}): no data")
            continue
        rows = [(r.date, label, r.value, "fred")
                for r in df.itertuples(index=False)]
        total += core.write_rows("global_market", rows, replace=replace)
        print(f"    [FRED] {label} ({sid}): {len(rows)}")
        time.sleep(0.3)
    core.log_ingest("fred", total)
    print(f"[ingest] FRED new rows: {total}")
    return total


# ===================================================================
# [6b] FRED FX  (deep-history FX backfill)  -- NEW in v3
# ===================================================================
def fetch_fred_fx(skip_existing=True, replace=False) -> int:
    """Deep-history daily FX from FRED DEX* -> market_data, series='FX_FRED'.

    Written to FX_FRED, NOT FX, on purpose: some DEX* pairs are USD-per-LCY
    (inverted) vs Yahoo's LCY-per-USD, so mixing them into one series would
    corrupt direction. Presenting/joining FX vs FX_FRED is a core/app decision;
    ingest just stores both cleanly. See config.FX_FRED (# VERIFY direction).
    """
    fxf = getattr(config, "FX_FRED", {})
    print(f"[ingest] FRED FX (deep history) -- {len(fxf)} series "
          f"(skip_existing={skip_existing})")
    total = 0
    for iso3, sid in fxf.items():
        if skip_existing and core.has_market(iso3, "FX_FRED"):
            continue
        df = _fred_one(sid)
        if df.empty:
            print(f"    [FRED-FX] {iso3} ({sid}): no data")
            continue
        rows = [(r.date, iso3, "FX_FRED", r.value, "fred_fx")
                for r in df.itertuples(index=False)]
        total += core.write_rows("market_data", rows, replace=replace)
        print(f"    [FRED-FX] {iso3} ({sid}): {len(rows)}")
        time.sleep(0.3)
    core.log_ingest("fred_fx", total)
    print(f"[ingest] FRED FX new rows: {total}")
    return total


# ===================================================================
# [7] SEED LOADER
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
# [8] STUBS / POINTERS
# ===================================================================
def fetch_gdelt(**kw):
    """NOT the real GDELT collector -- that is news_ingest.fetch_gdelt()."""
    print("[ingest] GDELT is handled by news_ingest.py, not ingest.py")
    print("         run:  python news_ingest.py --only gdelt")
    return 0


def fetch_predmarkets(**kw):
    print("[ingest] predmarkets stub (not built)")
    return 0


def fetch_trends(**kw):
    print("[ingest] Trends stub (not built)")
    return 0


# ===================================================================
# [9] ORCHESTRATION
# ===================================================================
# key -> (feature flag, function, default-if-flag-missing)
_DISPATCH = {
    "worldbank":   ("ingest_worldbank",   fetch_worldbank,   True),
    "dbnomics":    ("ingest_dbnomics",    fetch_dbnomics,    True),
    "yahoo_fx":    ("ingest_yahoo_fx",    fetch_yahoo_fx,    True),
    "equities":    ("ingest_yahoo_eq",    fetch_equities,    True),
    "yields":      ("ingest_yields",      fetch_yields,      True),
    "fred_fx":     ("ingest_fred_fx",     fetch_fred_fx,     False),
    "commodities": ("ingest_commodities", fetch_commodities, True),
    "globals":     ("ingest_globals",     fetch_globals,     True),
    "fred":        ("ingest_fred",        fetch_fred,        False),
    "gdelt":       ("ingest_gdelt",       fetch_gdelt,       False),
    "predmarkets": ("ingest_predmarkets", fetch_predmarkets, False),
    "trends":      ("ingest_trends",      fetch_trends,      False),
    "seed":        (None,                 load_seed,         True),
}

MARKET_KEYS = ("yahoo_fx", "equities", "yields", "fred_fx",
               "commodities", "globals")


def _enabled(flag, default) -> bool:
    if flag is None:
        return True
    return bool(config.FEATURE_FLAGS.get(flag, default))


def list_sources() -> None:
    """Print every source, its flag and whether it would run. No network."""
    print("=" * 72)
    print("EMDASH INGEST SOURCES")
    print("=" * 72)
    print(f"  {'key':<13} {'flag':<22} {'state':<9} note")
    for key, (flag, fn, default) in _DISPATCH.items():
        on = _enabled(flag, default)
        note = ""
        if key == "gdelt":
            note = "-> news_ingest.py"
        elif key in ("predmarkets", "trends"):
            note = "not built"
        elif key == "fred" and on:
            note = f"{len(getattr(config, 'FRED_SERIES', {}))} series"
        elif key == "fred_fx":
            note = f"{len(getattr(config, 'FX_FRED', {}))} series"
        elif key == "globals":
            note = f"{len(config.MARKET_TICKERS)} tickers"
        elif key == "commodities":
            note = f"{len(config.COMMODITIES)} tickers"
        elif key == "equities":
            note = f"{len(getattr(config, 'EQUITY_INDICES', {}))} markets"
        elif key == "yields":
            n = sum(len(v) for v in getattr(config, 'SOVEREIGN_YIELDS', {}).values())
            note = f"{n} tenor-series"
        elif key == "yahoo_fx":
            note = f"{sum(1 for *_, fx in [(i, fx) for i, n, d, dm, fx in config.COUNTRIES] if fx)} currencies"
        elif key == "worldbank":
            note = f"{len(config.COUNTRIES)}c x {len(config.WB_INDICATORS)} indic."
        missing = (flag is not None and flag not in config.FEATURE_FLAGS)
        state = "ON" if on else "off"
        if missing:
            state += "*"
            note = (note + "  *flag missing, using default").strip()
        print(f"  {key:<13} {str(flag):<22} {state:<9} {note}")
    print(f"\n  market window: since {MARKET_START} | macro since {MACRO_START_YEAR}")
    print("  * = flag absent from config.FEATURE_FLAGS; built-in default used.")


def run_all(only=None, skip_market=False, refresh=False) -> None:
    core.init_db()
    skip_existing = not refresh
    if only:
        unknown = [k for k in only if k not in _DISPATCH]
        if unknown:
            print(f"[ingest] unknown --only key(s): {', '.join(unknown)}")
            print(f"[ingest] valid keys: {', '.join(_DISPATCH)}")
            return
    for key, (flag, fn, default) in _DISPATCH.items():
        if only and key not in only:
            continue
        if skip_market and key in MARKET_KEYS:
            continue
        # An explicit --only overrides a disabled flag (you asked by name).
        if not _enabled(flag, default) and not only:
            continue
        if key == "seed":
            fn(replace=refresh)
        else:
            fn(skip_existing=skip_existing, replace=refresh)
    print("[ingest] table counts:", core.table_counts())
    print("[ingest] done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*",
                    help=f"one or more of: {', '.join(_DISPATCH)}")
    ap.add_argument("--skip-market", action="store_true",
                    help="skip all daily-market collectors")
    ap.add_argument("--refresh", action="store_true",
                    help="force full re-pull (overwrite existing)")
    ap.add_argument("--list", action="store_true",
                    help="show every source and whether it would run")
    args = ap.parse_args()
    if args.list:
        list_sources()
    else:
        run_all(only=args.only, skip_market=args.skip_market,
                refresh=args.refresh)
