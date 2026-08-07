"""
EMDASH :: ingest.py   (v2)
===================================================================
ALL FETCHERS. Each source: fetch -> clean -> core.write_rows().
Driven by config.FEATURE_FLAGS. run_all() loops enabled sources.

Kept from v1 (unchanged behaviour):
    - skip_existing (default ON): if a country/series already has
      data in the DB, DON'T re-download it. Makes re-runs fast and
      lets failed pulls get filled without re-pulling everything.
    - auto-retry on timeout (2 tries, 45s) -> fewer World Bank fails.
    - --refresh flag: force re-pull everything (overwrite).
    - ingest_log freshness stamp per source.

------------------------------------------------------------------
WHAT CHANGED IN v2
------------------------------------------------------------------
1. NEW: FRED COLLECTOR (credit spreads).
   config.FRED_SERIES listed the ICE BofA OAS series but nothing read
   it, so filling that dict did nothing. There is now a real collector
   using FRED's public CSV endpoint -- no API key required:
       https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
   Rows land in global_market alongside VIX/DXY, which means mrc.py
   picks them up automatically (it already knows the keys IG_OAS,
   BBB_OAS, HY_OAS) and they appear as Event Study signals/targets.
   This is what the CIO asked for: a direct credit read instead of
   inferring credit stress from vol.

2. GLOBALS SPLIT INTO THEIR OWN FETCHER.
   v1 pulled global_market inside fetch_commodities as a second loop.
   It worked, but it had two side effects:
     (a) global rows were stamped source_id="yahoo_cmdty" -- the
         COMMODITY source id -- so provenance was wrong;
     (b) commodities and globals shared one ingest_log stamp, so you
         could not tell which of the two had actually run.
   fetch_globals() is now separate, writes source_id="yahoo_glob",
   and stamps its own ingest_log row.

3. THE TWO DEAD FLAGS ARE NOW WIRED.
   config v2 added ingest_globals and ingest_fred, but v1's _DISPATCH
   never referenced them -- dead config, which is worse than no config.
   Both are now real dispatch entries with their own --only keys.

4. DEFAULT_FLAGS SAFETY NET.
   run_all() used config.FEATURE_FLAGS.get(flag, False), so a NEW flag
   missing from an older config.py silently disabled that collector.
   Defaults are now explicit per source, so an out-of-date config.py
   degrades sensibly instead of quietly skipping work.

5. GDELT STUB RENAMED AND MADE LOUD.
   ingest.fetch_gdelt was a stub returning 0 while news_ingest.py held
   the real fetcher -- same function name in two files. Running
   "python ingest.py --only gdelt" silently did nothing. It now prints
   where the real collector lives.

6. --only accepts the new keys: globals, fred.
   Also --list to print every source, its flag and its current state.

Usage:
    python ingest.py                      # normal: fill gaps, skip filled
    python ingest.py --list               # what would run, and why
    python ingest.py --only worldbank
    python ingest.py --only globals       # DXY/VIX/MOVE/BTC...
    python ingest.py --only fred          # credit spreads
    python ingest.py --only commodities --refresh    # settles the COAL question
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
TIMEOUT = 45          # bumped from 30 to reduce timeouts
RETRIES = 2           # try each request up to twice

# Browser-ish UA: some public endpoints (BIS, occasionally FRED behind a
# corporate proxy) reject the default python-requests agent.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 EMDASH-ingest/2.0")


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
            time.sleep(1.5 * (attempt + 1))   # small backoff before retry
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
            # NOT an error: the provider genuinely has no series under this
            # mask for this country. Printed so a coverage gap is visible
            # rather than silent (v1 returned quietly and looked identical
            # to a country that was never attempted).
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
                # v2: say so. v1 skipped in silence, which made a config gap
                # indistinguishable from a provider gap.
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
def _yahoo(ticker, years) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        print("    [YF] yfinance not installed -> pip install yfinance")
        return pd.DataFrame(columns=["date", "value"])
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
            continue          # USA: the dollar IS the base (app substitutes DXY)
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


# ===================================================================
# [4] YAHOO  (commodities)
# ===================================================================
def fetch_commodities(years=None, skip_existing=True, replace=False) -> int:
    """Commodity futures only.

    v1 also pulled global_market here as a second loop. That is now
    fetch_globals(), so each has its own source_id and its own freshness
    stamp -- see the module docstring.

    NOTE ON COAL: skip_existing checks 'does this commodity have ANY rows?',
    not 'is it current'. COAL has rows, so a normal run always skips it. If
    COAL looks stale, that is the reason -- prove it with:
        python ingest.py --only commodities --refresh
    """
    years = years or config.HISTORY["market_years"]
    print(f"[ingest] Yahoo commodities -- {years}y daily "
          f"(skip_existing={skip_existing})")
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
    core.log_ingest("yahoo_cmdty", total)
    print(f"[ingest] commodities new rows: {total}")
    return total


# ===================================================================
# [5] YAHOO  (global market gauges)  -- split out in v2
# ===================================================================
def fetch_globals(years=None, skip_existing=True, replace=False) -> int:
    """DXY / VIX / MOVE / SPX / EMB / BTC ... -> global_market.

    These are the MRC's gauges, so this is the collector to run after adding
    anything to config.MARKET_TICKERS. BTC is new in config v2 and has no rows
    yet, so a NORMAL run will pull it -- no --refresh needed.
    """
    years = years or config.HISTORY["market_years"]
    print(f"[ingest] Yahoo global gauges -- {years}y daily "
          f"(skip_existing={skip_existing})")
    total = 0
    for label, ticker in config.MARKET_TICKERS.items():
        if skip_existing and core.has_global(label):
            continue
        df = _yahoo(ticker, years)
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
# [6] FRED  (credit spreads)  -- NEW in v2
# ===================================================================
def _fred_one(series_id: str) -> pd.DataFrame:
    """One FRED series via the public CSV endpoint (no API key needed).

    FRED's CSV header has changed over the years -- older exports use
    "DATE,<SERIES_ID>" and newer ones "observation_date,<SERIES_ID>" -- so we
    take the FIRST column as the date and the SECOND as the value rather than
    hard-coding a name. Missing observations are published as "." and are
    dropped (never interpolated).
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

    Why these matter (CIO, 30 Jul 2026): VIX reads across to INVESTMENT GRADE
    spreads and MOVE to HIGH YIELD. Carrying the spreads themselves lets the
    regime classifier see credit stress directly instead of inferring it.

    mrc.py already registers IG_OAS / BBB_OAS / HY_OAS as optional gauges, so
    they start voting automatically once these rows exist -- no code change.
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
        time.sleep(0.3)                      # be polite to the endpoint
    core.log_ingest("fred", total)
    print(f"[ingest] FRED new rows: {total}")
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
    """NOT the real GDELT collector.

    The working one is news_ingest.fetch_gdelt(). v1 had a same-named stub
    here, so 'python ingest.py --only gdelt' silently did nothing and looked
    like a broken feature. It now says where to go.
    """
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
# The third element matters: config.FEATURE_FLAGS.get(flag, False) meant a NEW
# flag absent from an older config.py silently disabled that collector. An
# out-of-date config now degrades sensibly instead of quietly skipping work.
_DISPATCH = {
    "worldbank":   ("ingest_worldbank",   fetch_worldbank,   True),
    "dbnomics":    ("ingest_dbnomics",    fetch_dbnomics,    True),
    "yahoo_fx":    ("ingest_yahoo_fx",    fetch_yahoo_fx,    True),
    "commodities": ("ingest_commodities", fetch_commodities, True),
    "globals":     ("ingest_globals",     fetch_globals,     True),
    "fred":        ("ingest_fred",        fetch_fred,        False),
    "gdelt":       ("ingest_gdelt",       fetch_gdelt,       False),
    "predmarkets": ("ingest_predmarkets", fetch_predmarkets, False),
    "trends":      ("ingest_trends",      fetch_trends,      False),
    "seed":        (None,                 load_seed,         True),
}

MARKET_KEYS = ("yahoo_fx", "commodities", "globals")


def _enabled(flag, default) -> bool:
    if flag is None:
        return True
    return bool(config.FEATURE_FLAGS.get(flag, default))


def list_sources() -> None:
    """Print every source, its flag and whether it would run. No network."""
    print("=" * 68)
    print("EMDASH INGEST SOURCES")
    print("=" * 68)
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
        elif key == "globals":
            note = f"{len(config.MARKET_TICKERS)} tickers"
        elif key == "commodities":
            note = f"{len(config.COMMODITIES)} tickers"
        missing = (flag is not None and flag not in config.FEATURE_FLAGS)
        state = "ON" if on else "off"
        if missing:
            state += "*"
            note = (note + "  *flag missing from config, using default").strip()
        print(f"  {key:<13} {str(flag):<22} {state:<9} {note}")
    print("\n  * = flag not present in config.FEATURE_FLAGS; the built-in "
          "default was used.")


def run_all(only=None, skip_market=False, refresh=False) -> None:
    core.init_db()
    skip_existing = not refresh          # --refresh forces full re-pull
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
        # An explicit --only overrides a disabled flag (you asked for it by
        # name), which is the v1 behaviour and is deliberate.
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
                    help="skip yahoo_fx / commodities / globals")
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
