"""
EMDASH :: news_ingest.py

THE NEWS COLLECTOR. Fills the `news` table that already exists in core.py.
Two source types, one shared writer:

  [1] RSS / Atom feeds   -> config.RSS_FEEDS      (curated Tier A / B / C)
  [2] GDELT DOC 2.0 API  -> config.GDELT_*         (global firehose, per-country)

Every headline becomes one row:
    (ts, source_id, tier, iso3_tags, headline, url, tone)

De-dup is automatic: the `news` primary key is (ts, url) and we write with
INSERT OR IGNORE (core.write_rows, replace=False). So re-running only adds
genuinely NEW headlines -- same "skip what we already have" idea as ingest.py.

COUNTRY TAGGING
  RSS headlines have no country field, so we keyword-match the headline text
  against country names + config.NEWS_COUNTRY_ALIASES (currencies, "Fed", etc).
  GDELT rows are already country-scoped (we query one country at a time).

TOPIC BUCKETING (for the Kanban columns)
  Derived at DISPLAY time via topic_of() so we do NOT touch the DB schema.
  app.py imports topic_of(headline) to sort cards into columns
  (Monetary Policy / Inflation / Growth / Politics / Markets).

TONE
  RSS feeds carry no tone            -> stored as None.
  GDELT ArtList carries no per-article tone either -> None for now.
  (Documented upgrade path: enrich tone via GDELT GKG or a local lexicon.)

USAGE
  python news_ingest.py                 # all enabled sources (RSS + GDELT)
  python news_ingest.py --only rss      # just the curated feeds
  python news_ingest.py --only gdelt    # just the firehose
  python news_ingest.py --limit 10      # cap feeds/countries (quick test)
"""
from __future__ import annotations

import argparse
import datetime as dt
import time
import urllib.parse

import requests

import config
import core

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


# ===================================================================
# COUNTRY TAGGING  -- turn "Indonesia cuts rates" into iso3_tags="IDN"
# ===================================================================
def _country_keywords() -> dict[str, str]:
    """Build a {lowercase keyword -> iso3} map from country names + aliases.
    Longer keys first so 'south korea' beats 'korea'-style partials."""
    kw: dict[str, str] = {}
    for iso3, name, *_ in config.COUNTRIES:
        kw[name.lower()] = iso3
    for alias, iso3 in config.NEWS_COUNTRY_ALIASES.items():
        kw[alias.lower()] = iso3
    return kw


def _tag_countries(text: str, kwmap: dict[str, str]) -> str:
    """Return a comma-joined list of iso3s mentioned in `text` (no dups)."""
    if not text:
        return ""
    low = f" {text.lower()} "
    found: list[str] = []
    # match longer keywords first (e.g. 'south africa' before 'africa')
    for keyword in sorted(kwmap, key=len, reverse=True):
        if keyword in low and kwmap[keyword] not in found:
            found.append(kwmap[keyword])
    return ",".join(found)


def topic_of(text: str) -> str:
    """Map a headline to a Kanban column key (config.NEWS_TOPICS).
    Used at DISPLAY time by app.py. First matching bucket wins."""
    if not text:
        return "general"
    low = text.lower()
    for topic, words in config.NEWS_TOPICS.items():
        if any(w in low for w in words):
            return topic
    return "general"


# ===================================================================
# [1] RSS / ATOM FEEDS
# ===================================================================
def _parse_entry_time(entry) -> str:
    """Best-effort ISO timestamp from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return dt.datetime(*t[:6]).isoformat(timespec="seconds")
    # no date on the entry -> stamp it now (still de-dupes on url)
    return dt.datetime.now().isoformat(timespec="seconds")


def fetch_rss(limit: int | None = None, replace: bool = False) -> int:
    """Pull every feed in config.RSS_FEEDS into the news table."""
    try:
        import feedparser
    except ImportError:
        print("    [RSS] feedparser not installed -> `pip install feedparser`")
        return 0

    kwmap = _country_keywords()
    feeds = config.RSS_FEEDS[:limit] if limit else config.RSS_FEEDS
    print(f"[news] RSS -- {len(feeds)} feeds")
    total = 0

    for source_id, name, tier, url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"    [RSS] {source_id}: FAILED ({e})")
            continue
        if not parsed.entries:
            print(f"    [RSS] {source_id}: no entries (check URL)")
            continue

        rows = []
        for e in parsed.entries:
            headline = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if not headline or not link:
                continue
            ts = _parse_entry_time(e)
            iso3_tags = _tag_countries(headline, kwmap)
            # (ts, source_id, tier, iso3_tags, headline, url, tone)
            rows.append((ts, source_id, tier, iso3_tags, headline, link, None))

        n = core.write_rows("news", rows, replace=replace)
        total += n
        print(f"    [RSS] {source_id}: {n} new  ({len(parsed.entries)} seen)")

    core.log_ingest("rss_all", total)
    print(f"[news] RSS new rows: {total}")
    return total


# ===================================================================
# [2] GDELT DOC 2.0  (free global firehose, per-country ArtList)
# ===================================================================
def _gdelt_query(query: str, maxrecords: int, timespan: str) -> list[dict]:
    """Hit the GDELT DOC 2.0 ArtList endpoint. Returns list of article dicts."""
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(maxrecords),
        "timespan": timespan,
        "sort": "datedesc",
    }
    url = f"{GDELT_URL}?{urllib.parse.urlencode(params)}"
    try:
        r = requests.get(url, timeout=45)
        # GDELT returns 429 when rate-limited, or HTML on a bad query
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return []
        return r.json().get("articles", []) or []
    except Exception as e:
        print(f"    [GDELT] query FAILED: {e}")
        return []


def _gdelt_seendate_to_iso(seendate: str) -> str:
    """'20260726T120000Z' -> '2026-07-26T12:00:00'. Falls back to now()."""
    try:
        return dt.datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").isoformat(
            timespec="seconds")
    except Exception:
        return dt.datetime.now().isoformat(timespec="seconds")


def fetch_gdelt(limit: int | None = None, replace: bool = False) -> int:
    """One ArtList query per country -> news table. Country is known, so
    iso3_tags is set directly (no keyword matching needed)."""
    if not config.GDELT_ENABLED:
        print("[news] GDELT disabled in config")
        return 0

    countries = [c for c in config.COUNTRIES
                 if (not config.GDELT_EM_ONLY or c[3] == "EM")]
    if limit:
        countries = countries[:limit]

    print(f"[news] GDELT -- {len(countries)} countries "
          f"(timespan={config.GDELT_TIMESPAN}, tier={config.GDELT_TIER})")
    total = 0

    for iso3, name, *_ in countries:
        # query the country name; optionally restrict language
        q = f'"{name}"'
        if config.GDELT_LANG:
            q += f" sourcelang:{config.GDELT_LANG}"
        articles = _gdelt_query(q, config.GDELT_MAXRECORDS, config.GDELT_TIMESPAN)

        rows = []
        for a in articles:
            headline = (a.get("title") or "").strip()
            link = (a.get("url") or "").strip()
            if not headline or not link:
                continue
            ts = _gdelt_seendate_to_iso(a.get("seendate", ""))
            # (ts, source_id, tier, iso3_tags, headline, url, tone)
            rows.append((ts, "gdelt", config.GDELT_TIER, iso3, headline, link, None))

        n = core.write_rows("news", rows, replace=replace)
        total += n
        print(f"    [GDELT] {iso3}: {n} new  ({len(articles)} seen)")
        time.sleep(config.GDELT_SLEEP_SEC)   # be polite -> avoid 429s

    core.log_ingest("gdelt", total)
    print(f"[news] GDELT new rows: {total}")
    return total


# ===================================================================
# ORCHESTRATION
# ===================================================================
def run_news(only: str | None = None, limit: int | None = None,
             refresh: bool = False) -> None:
    core.init_db()                      # ensure schema + reference tables exist
    replace = refresh                   # --refresh overwrites; default keeps

    if only in (None, "rss") and config.FEATURE_FLAGS.get("ingest_rss", True):
        fetch_rss(limit=limit, replace=replace)
    if only in (None, "gdelt"):
        fetch_gdelt(limit=limit, replace=replace)

    print("[news] table counts:", core.table_counts())
    print("[news] done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["rss", "gdelt"],
                    help="run just one source type")
    ap.add_argument("--limit", type=int,
                    help="cap number of feeds / countries (quick test)")
    ap.add_argument("--refresh", action="store_true",
                    help="overwrite existing rows instead of skipping")
    args = ap.parse_args()
    run_news(only=args.only, limit=args.limit, refresh=args.refresh)
