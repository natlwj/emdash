"""
EMDASH :: status.py

DATA STATUS / COVERAGE + FEED CHECK  --  a handover-friendly "what's actually in
the warehouse, and are my feeds alive?" report, without opening the .sqlite.

USAGE  (PowerShell, in the EMDASH folder)
    python status.py                 # warehouse coverage report
    python status.py --csv           # also write emdash_coverage.csv
    python status.py --country IDN   # zoom into one country's macro coverage
    python status.py --stale 60      # flag market/global series stale > N days
    python status.py --feeds         # NEW: live-check RSS feeds (needs internet)
                                     #      also suggests candidate feeds to add

The --feeds mode replaces the old separate check_feeds.py (kept lean: one file).
It reads config.RSS_FEEDS -- no feed list is hard-coded except the CANDIDATES
suggestions you can confirm and paste in.
"""
from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd

import config
import core


# ===================================================================
# WAREHOUSE COVERAGE
# ===================================================================
def _grouped(sql: str) -> pd.DataFrame:
    conn = core.get_conn()
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


def table_counts_report() -> None:
    print("=" * 72)
    print("EMDASH DATA STATUS   ·   " + dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 72)
    try:
        counts = core.table_counts()
    except Exception:
        counts = {}
    print("\nROW COUNTS PER TABLE")
    for k, v in counts.items():
        flag = "  (empty / unbuilt)" if not v else ""
        print(f"  {k:16} {('' if v is None else f'{v:>10,}')}{flag}")


def macro_coverage(only_country=None) -> pd.DataFrame:
    df = _grouped("SELECT iso3, indicator, COUNT(*) n FROM macro_data "
                  "GROUP BY iso3, indicator")
    if df.empty:
        return df
    inds = list(config.WB_INDICATORS) + list(config.DBN_SERIES)
    isos = [i for i, *_ in config.COUNTRIES]
    if only_country:
        isos = [only_country]
    return (df.pivot_table(index="iso3", columns="indicator", values="n",
                          fill_value=0, aggfunc="sum")
              .reindex(index=isos, columns=inds, fill_value=0).astype(int))


def print_macro_coverage(only_country=None) -> None:
    mat = macro_coverage(only_country)
    if mat.empty:
        print("\n(no macro_data rows)")
        return
    print("\nMACRO COVERAGE  (row counts; '.' = MISSING)")
    inds = list(mat.columns)
    print("  " + "iso ".ljust(6) + " ".join(f"{c[:8]:>9}" for c in inds))
    empties = []
    for iso, row in mat.iterrows():
        cells = []
        for cc in inds:
            v = int(row[cc])
            cells.append(("." if v == 0 else str(v)).rjust(9))
            if v == 0:
                empties.append((iso, cc))
        print(f"  {iso:5} " + " ".join(cells))
    print(f"\n  MISSING cells: {len(empties)}")
    by_ind: dict[str, list] = {}
    for iso, cc in empties:
        by_ind.setdefault(cc, []).append(iso)
    for cc, isos in sorted(by_ind.items(), key=lambda x: -len(x[1])):
        print(f"    {cc:14} missing for {len(isos):>2}: {', '.join(isos)}")


def print_market_coverage() -> None:
    df = _grouped("SELECT iso3, series, COUNT(*) n, MIN(date) mn, MAX(date) mx "
                  "FROM market_data GROUP BY iso3, series")
    print("\nMARKET (FX) COVERAGE")
    if df.empty:
        print("  (none)"); return
    print(f"  countries with FX: {df['iso3'].nunique()}   rows: {int(df['n'].sum()):,}")
    print(f"  date span: {df['mn'].min()[:10]} -> {df['mx'].max()[:10]}")


def print_other_coverage() -> None:
    for table, keycol, label in (("global_market", "series", "GLOBAL MARKET"),
                                 ("commodity_data", "commodity", "COMMODITIES")):
        df = _grouped(f"SELECT {keycol} k, COUNT(*) n, MIN(date) mn, MAX(date) mx "
                      f"FROM {table} GROUP BY {keycol}")
        print(f"\n{label} COVERAGE")
        if df.empty:
            print("  (none)"); continue
        for _, r in df.sort_values("k").iterrows():
            print(f"  {r['k']:10} n={int(r['n']):>6,}  {r['mn'][:10]} -> {r['mx'][:10]}")


def print_freshness(stale_days=60) -> None:
    print(f"\nFRESHNESS  (flagging market/global/commodity series stale > {stale_days}d)")
    cutoff = (dt.datetime.now() - dt.timedelta(days=stale_days)).strftime("%Y-%m-%d")
    any_stale = False
    for table, keycol in (("market_data", "iso3 || '·' || series"),
                          ("global_market", "series"),
                          ("commodity_data", "commodity")):
        df = _grouped(f"SELECT {keycol} k, MAX(date) mx FROM {table} GROUP BY {keycol}")
        if df.empty:
            continue
        for _, r in df[df["mx"] < cutoff].iterrows():
            print(f"  STALE  {r['k']:20} last {r['mx'][:10]}")
            any_stale = True
    if not any_stale:
        print("  all series fresh ✔")


# ===================================================================
# RSS FEED CHECK  (--feeds; needs internet)  -- folded in from check_feeds.py
# ===================================================================
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 EMDASH-feedcheck/1.0")

# Candidate feeds to consider adding. Confirm they work from YOUR network (this
# is exactly what --feeds does) before pasting into config.RSS_FEEDS.
CANDIDATES = [
    ("rbi",         "Reserve Bank of India",    "A", "https://www.rbi.org.in/Scripts/Rss.aspx", "IND"),
    ("bcb",         "Banco Central do Brasil",  "A", "https://www.bcb.gov.br/api/feed/sitebcb/pt-br/ultimas", "BRA"),
    ("banxico",     "Banco de Mexico",          "A", "https://www.banxico.org.mx/rss/rss.xml", "MEX"),
    ("sarb",        "South African Reserve Bank","A","https://www.resbank.co.za/en/home/publications/RssFeed", "ZAF"),
    ("cbrt",        "Central Bank of Turkey",   "A", "https://www.tcmb.gov.tr/rss/announcements_eng.xml", "TUR"),
    ("bok",         "Bank of Korea",            "A", "https://www.bok.or.kr/eng/bbs/E0000634/news.rss", "KOR"),
    ("rba",         "Reserve Bank of Australia","A", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "AUS"),
    ("nikkei_asia", "Nikkei Asia",              "B", "https://asia.nikkei.com/rss/feed/nar", None),
    ("diplomat",    "The Diplomat",             "B", "https://thediplomat.com/feed/", None),
    ("aljazeera",   "Al Jazeera",               "B", "https://www.aljazeera.com/xml/rss/all.xml", None),
    ("scmp_econ",   "SCMP Economy",             "B", "https://www.scmp.com/rss/318198/feed", None),
    ("piie",        "PIIE",                     "B", "https://www.piie.com/rss.xml", None),
    ("cepr_vox",    "VoxEU / CEPR",             "B", "https://cepr.org/rss.xml", None),
    ("imf_blog",    "IMF Blog",                 "B", "https://www.imf.org/en/Blogs/rss", None),
]


def _check_feed(url, timeout):
    try:
        import requests
        import feedparser
    except Exception:
        return "NODEP", 0, "-"
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return "DEAD", 0, "-"
        d = feedparser.parse(r.content)
    except Exception:
        return "DEAD", 0, "-"
    n = len(d.entries)
    if n == 0:
        return "EMPTY", 0, "-"
    import time
    newest = "-"
    for e in d.entries[:5]:
        st = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        if st:
            newest = time.strftime("%Y-%m-%d", st); break
    return "OK", n, newest


def _feed_row(status, n, newest, sid, name, origin=None):
    tag = {"OK": "OK  ", "EMPTY": "EMPTY", "DEAD": "DEAD ", "NODEP": "NODEP"}[status]
    ori = f"  origin={origin}" if origin else ""
    print(f"  {tag} {n:>4} entries  {newest:<11} {sid:<12} {name}{ori}")


def print_feeds(timeout=10) -> None:
    print("\n" + "=" * 72)
    print("RSS FEED CHECK   (needs internet; OK = paste to config, DEAD = drop)")
    print("=" * 72)
    try:
        import requests, feedparser  # noqa
    except Exception:
        print("\n  Missing deps. Run:  python -m pip install feedparser requests")
        return
    print("\nCURRENT config.RSS_FEEDS")
    ok = dead = empty = 0
    for sid, name, tier, url in config.RSS_FEEDS:
        st, n, newest = _check_feed(url, timeout)
        _feed_row(st, n, newest, sid, name)
        ok += st == "OK"; dead += st == "DEAD"; empty += st == "EMPTY"
    print(f"\n  summary: {ok} OK · {empty} empty · {dead} dead  (of {len(config.RSS_FEEDS)})")

    print("\nCANDIDATE FEEDS (confirm before adding)")
    add, origins = [], []
    for sid, name, tier, url, origin in CANDIDATES:
        st, n, newest = _check_feed(url, timeout)
        _feed_row(st, n, newest, sid, name, origin)
        if st == "OK":
            add.append(f'    ("{sid}", "{name}", "{tier}", "{url}"),')
            if origin:
                origins.append(f'    "{sid}": "{origin}",')
    if add:
        print("\n  --- paste working candidates into RSS_FEEDS: ---")
        print("\n".join(add))
        if origins:
            print("\n  --- and into FEED_ORIGIN_ISO: ---")
            print("\n".join(origins))


# ===================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--country")
    ap.add_argument("--stale", type=int, default=60)
    ap.add_argument("--feeds", action="store_true", help="live-check RSS feeds")
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    if args.feeds:
        print_feeds(args.timeout)
        return

    table_counts_report()
    print_macro_coverage(args.country)
    print_market_coverage()
    print_other_coverage()
    print_freshness(args.stale)
    if args.csv:
        out = config.ROOT / "emdash_coverage.csv"
        macro_coverage(args.country).to_csv(out)
        print(f"\n[status] wrote coverage matrix -> {out}")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
