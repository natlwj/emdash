"""
EMDASH :: news_ingest.py

THE NEWS COLLECTOR. Fills the `news` table in core.py.
  [1] RSS / Atom feeds   -> config.RSS_FEEDS
  [2] GDELT DOC 2.0 API  -> config.GDELT_*

Row: (ts, source_id, tier, iso3_tags, headline, url, tone).
De-dup: primary key (ts, url) + INSERT OR IGNORE -> reruns add only NEW rows.

COUNTRY TAGGING: keyword-match headline vs country names + NEWS_COUNTRY_ALIASES
(now incl. leaders/capitals, e.g. "Trump"->USA). Fallback to FEED_ORIGIN_ISO.

TOPICS: topics_of() returns a LIST (a headline can be multi-tagged). topic_of()
kept for backward-compat (returns the first). Both read config.NEWS_TOPICS.

USAGE
  python news_ingest.py                 # RSS + GDELT
  python news_ingest.py --only rss
  python news_ingest.py --only gdelt
  python news_ingest.py --limit 10
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
# TAGGING
# ===================================================================
def _country_keywords() -> dict[str, str]:
    kw: dict[str, str] = {}
    for iso3, name, *_ in config.COUNTRIES:
        kw[name.lower()] = iso3
    for alias, iso3 in config.NEWS_COUNTRY_ALIASES.items():
        kw[alias.lower()] = iso3
    return kw


def _tag_countries(text: str, kwmap: dict[str, str]) -> str:
    if not text:
        return ""
    low = f" {text.lower()} "
    found: list[str] = []
    for keyword in sorted(kwmap, key=len, reverse=True):
        if keyword in low and kwmap[keyword] not in found:
            found.append(kwmap[keyword])
    return ",".join(found)


def topics_of(text: str) -> list[str]:
    """All topics whose keywords appear in the headline (multi-tag)."""
    if not text:
        return ["general"]
    low = text.lower()
    hits = [t for t, words in config.NEWS_TOPICS.items()
            if any(w in low for w in words)]
    return hits or ["general"]


def topic_of(text: str) -> str:
    """First matching topic (backward-compatible single tag)."""
    return topics_of(text)[0]


# ===================================================================
# [1] RSS
# ===================================================================
def _parse_entry_time(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return dt.datetime(*t[:6]).isoformat(timespec="seconds")
    return dt.datetime.now().isoformat(timespec="seconds")


def fetch_rss(limit: int | None = None, replace: bool = False) -> int:
    try:
        import feedparser
    except ImportError:
        print("    [RSS] feedparser not installed -> `pip install feedparser`")
        return 0

    kwmap = _country_keywords()
    origin = getattr(config, "FEED_ORIGIN_ISO", {})
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
            if not iso3_tags and source_id in origin:
                iso3_tags = origin[source_id]
            rows.append((ts, source_id, tier, iso3_tags, headline, link, None))

        n = core.write_rows("news", rows, replace=replace)
        total += n
        print(f"    [RSS] {source_id}: {n} new  ({len(parsed.entries)} seen)")

    core.log_ingest("rss_all", total)
    print(f"[news] RSS new rows: {total}")
    return total


# ===================================================================
# [2] GDELT
# ===================================================================
def _gdelt_query(query: str, maxrecords: int, timespan: str) -> list[dict]:
    params = {
        "query": query, "mode": "ArtList", "format": "json",
        "maxrecords": str(maxrecords), "timespan": timespan, "sort": "datedesc",
    }
    url = f"{GDELT_URL}?{urllib.parse.urlencode(params)}"
    try:
        r = requests.get(url, timeout=45)
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return []
        return r.json().get("articles", []) or []
    except Exception as e:
        print(f"    [GDELT] query FAILED: {e}")
        return []


def _gdelt_seendate_to_iso(seendate: str) -> str:
    try:
        return dt.datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").isoformat(
            timespec="seconds")
    except Exception:
        return dt.datetime.now().isoformat(timespec="seconds")


def fetch_gdelt(limit: int | None = None, replace: bool = False) -> int:
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
            rows.append((ts, "gdelt", config.GDELT_TIER, iso3, headline, link, None))

        n = core.write_rows("news", rows, replace=replace)
        total += n
        print(f"    [GDELT] {iso3}: {n} new  ({len(articles)} seen)")
        time.sleep(config.GDELT_SLEEP_SEC)

    core.log_ingest("gdelt", total)
    print(f"[news] GDELT new rows: {total}")
    return total


# ===================================================================
# ORCHESTRATION
# ===================================================================
def run_news(only: str | None = None, limit: int | None = None,
             refresh: bool = False) -> None:
    core.init_db()
    replace = refresh
    if only in (None, "rss") and config.FEATURE_FLAGS.get("ingest_rss", True):
        fetch_rss(limit=limit, replace=replace)
    if only in (None, "gdelt"):
        fetch_gdelt(limit=limit, replace=replace)
    print("[news] table counts:", core.table_counts())
    print("[news] done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["rss", "gdelt"], help="run one source type")
    ap.add_argument("--limit", type=int, help="cap feeds / countries")
    ap.add_argument("--refresh", action="store_true", help="overwrite existing rows")
    args = ap.parse_args()
    run_news(only=args.only, limit=args.limit, refresh=args.refresh)
