"""
EMDASH :: news_ingest.py   (v2)

THE NEWS COLLECTOR **and** THE TAGGING ENGINE.
  [1] RSS / Atom feeds   -> config.RSS_FEEDS
  [2] GDELT DOC 2.0 API  -> config.GDELT_*

Row: (ts, source_id, tier, iso3_tags, headline, url, tone).
De-dup: primary key (ts, url) + INSERT OR IGNORE -> reruns add only NEW rows.

------------------------------------------------------------------------------
WHAT CHANGED IN v2
------------------------------------------------------------------------------
1. TOPIC TAGGING FIXED.  v1 matched topic keywords with a plain substring test
   (`if w in low`), so short keywords fired inside longer words.  Confirmed
   against your live data:
        "gold"  inside "Goldman"     -> commodities
        "coal"  inside "coalition"   -> energy
        "oil"   inside "turmoil"     -> commodities
        "war"   inside "warning"     -> geopolitics
        "rate"  inside "corporate"   -> central_bank
   Topics drive the Kanban columns, so this was visible on every screen.
   Now every keyword is matched on WORD BOUNDARIES.

2. COUNTRY TAGGING MOVED HERE (from app.py) and made the single source of
   truth.  Previously the good long-form alias table lived in app.py while
   ingest still used the old broken substring matcher -- so rows were written
   to the DB with bad tags and only repaired at display time.  Now BOTH the
   ingest path and the dashboard call the same functions, so new rows are
   correct on the way in and old rows are still repaired on the way out.

3. ONE COMBINED REGEX INSTEAD OF ~250 SEPARATE ONES.  Measured on 4,000
   headlines: 250 individual compiled regexes took 1,557 ms; a single
   alternation regex scanned with findall takes 130 ms.  ~12x faster, with
   identical output.  Same trick for topics.

4. BULK HELPERS: tag_countries_many() / topics_of_many() for the dashboard,
   which re-derives tags for every row on load.

5. PREFIX KEYWORDS.  Some config keywords are deliberately word STEMS
   ("depreciat" should match depreciated/depreciation).  A trailing "*" in a
   config keyword now means "prefix match"; the three legacy stems are also
   auto-detected so existing config keeps working.

USAGE
  python news_ingest.py                 # RSS + GDELT
  python news_ingest.py --only rss
  python news_ingest.py --only gdelt
  python news_ingest.py --limit 10
  python news_ingest.py --selftest      # tagging tests, no network, no DB
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import time
import urllib.parse

import requests

import config
import core

import os


GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Many feeds (Bruegel, Reddit, Cloudflare-fronted sites) return HTTP 403 to
# feedparser's default "feedparser/6.x" User-Agent. Present a normal browser UA
# so they serve us the feed. This alone revives several "dead" feeds.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# ===================================================================
# COUNTRY ALIASES
#
# RULES OF THUMB when extending:
#   * >= 4 characters, or it will fire on noise.
#   * Never add a plain English word ("real", "won", "dong", "rand", "mas").
#     Qualify it: "brazilian real", "korean won", "south african rand".
#   * Prefer the long form AND the well-known abbreviation as separate keys.
#
# config.NEWS_COUNTRY_ALIASES is MERGED on top of this table, so anything you
# add there keeps working -- except entries shorter than 4 characters or on the
# blocklist below, which are ignored because they caused the original bugs.
# ===================================================================
BASE_ALIASES: dict[str, str] = {
    # ---------- SOUTHEAST ASIA ----------
    "bank indonesia": "IDN", "indonesian": "IDN", "jakarta": "IDN",
    "rupiah": "IDN", "prabowo": "IDN",
    "bank negara malaysia": "MYS", "bank negara": "MYS", "malaysian": "MYS",
    "kuala lumpur": "MYS", "ringgit": "MYS", "anwar ibrahim": "MYS",
    "bank of thailand": "THA", "thai baht": "THA", "thailand": "THA",
    "bangkok": "THA", "thai": "THA",
    "bangko sentral ng pilipinas": "PHL", "bangko sentral": "PHL",
    "philippine peso": "PHL", "philippines": "PHL", "manila": "PHL",
    "state bank of vietnam": "VNM", "vietnamese dong": "VNM", "vietnam": "VNM",
    "hanoi": "VNM", "vietnamese": "VNM",
    "monetary authority of singapore": "SGP", "singapore dollar": "SGP",
    "singapore": "SGP", "singaporean": "SGP",
    # ---------- EAST ASIA ----------
    "people's bank of china": "CHN", "peoples bank of china": "CHN",
    "pboc": "CHN", "chinese yuan": "CHN", "renminbi": "CHN", "beijing": "CHN",
    "chinese": "CHN", "shanghai": "CHN", "china": "CHN", "xi jinping": "CHN",
    "bank of korea": "KOR", "korean won": "KOR", "south korea": "KOR",
    "seoul": "KOR", "korean": "KOR",
    "central bank of the republic of china": "TWN", "taiwan": "TWN",
    "taipei": "TWN", "taiwanese": "TWN", "new taiwan dollar": "TWN",
    "hong kong monetary authority": "HKG", "hong kong dollar": "HKG",
    "hong kong": "HKG", "hkma": "HKG",
    # ---------- CENTRAL & SOUTH ASIA ----------
    "reserve bank of india": "IND", "indian rupee": "IND", "india": "IND",
    "mumbai": "IND", "new delhi": "IND", "indian": "IND", "modi": "IND",
    "state bank of pakistan": "PAK", "pakistani rupee": "PAK",
    "pakistan": "PAK", "islamabad": "PAK", "karachi": "PAK",
    "bangladesh bank": "BGD", "bangladesh": "BGD", "dhaka": "BGD", "taka": "BGD",
    "central bank of sri lanka": "LKA", "sri lanka": "LKA", "colombo": "LKA",
    "national bank of kazakhstan": "KAZ", "kazakhstan": "KAZ",
    "kazakh tenge": "KAZ", "almaty": "KAZ", "astana": "KAZ",
    # ---------- LATAM ----------
    "banco central do brasil": "BRA", "central bank of brazil": "BRA",
    "brazilian real": "BRA", "brazil": "BRA", "brasilia": "BRA",
    "sao paulo": "BRA", "brazilian": "BRA", "lula": "BRA",
    "banco de mexico": "MEX", "banxico": "MEX", "mexican peso": "MEX",
    "mexico": "MEX", "mexico city": "MEX", "mexican": "MEX", "sheinbaum": "MEX",
    "banco central de chile": "CHL", "chilean peso": "CHL", "chile": "CHL",
    "santiago": "CHL", "chilean": "CHL",
    "banco de la republica": "COL", "colombian peso": "COL",
    "colombia": "COL", "bogota": "COL", "colombian": "COL",
    "banco central de reserva del peru": "PER", "peruvian sol": "PER",
    "peru": "PER", "lima": "PER", "peruvian": "PER",
    "banco central de la republica argentina": "ARG",
    "argentine peso": "ARG", "argentina": "ARG", "buenos aires": "ARG",
    "argentine": "ARG", "milei": "ARG",
    # ---------- MIDDLE EAST & AFRICA ----------
    "south african reserve bank": "ZAF", "south african rand": "ZAF",
    "south africa": "ZAF", "johannesburg": "ZAF", "pretoria": "ZAF",
    "saudi central bank": "SAU", "saudi arabia": "SAU", "saudi riyal": "SAU",
    "riyadh": "SAU", "saudi": "SAU",
    "central bank of the uae": "ARE", "united arab emirates": "ARE",
    "abu dhabi": "ARE", "dubai": "ARE", "uae dirham": "ARE",
    "central bank of egypt": "EGY", "egyptian pound": "EGY", "egypt": "EGY",
    "cairo": "EGY", "egyptian": "EGY",
    "central bank of nigeria": "NGA", "nigerian naira": "NGA",
    "nigeria": "NGA", "lagos": "NGA", "abuja": "NGA", "nigerian": "NGA",
    "central bank of kenya": "KEN", "kenyan shilling": "KEN", "kenya": "KEN",
    "nairobi": "KEN", "kenyan": "KEN",
    # ---------- EM EUROPE ----------
    "narodowy bank polski": "POL", "national bank of poland": "POL",
    "polish zloty": "POL", "poland": "POL", "warsaw": "POL", "polish": "POL",
    "magyar nemzeti bank": "HUN", "national bank of hungary": "HUN",
    "hungarian forint": "HUN", "hungary": "HUN", "budapest": "HUN",
    "czech national bank": "CZE", "czech koruna": "CZE",
    "czech republic": "CZE", "czechia": "CZE", "prague": "CZE",
    "national bank of romania": "ROU", "romanian leu": "ROU",
    "romania": "ROU", "bucharest": "ROU", "romanian": "ROU",
    "central bank of the republic of turkiye": "TUR",
    "central bank of turkey": "TUR", "turkish lira": "TUR",
    "turkey": "TUR", "turkiye": "TUR", "ankara": "TUR", "istanbul": "TUR",
    "erdogan": "TUR", "turkish": "TUR",
    # ---------- G10 ----------
    "federal reserve": "USA", "fomc": "USA", "the fed": "USA",
    "united states": "USA", "washington": "USA", "wall street": "USA",
    "u.s. dollar": "USA", "us dollar": "USA", "american": "USA",
    "treasury department": "USA", "powell": "USA", "trump": "USA",
    "european central bank": "EMU", "eurozone": "EMU", "euro area": "EMU",
    "frankfurt": "EMU", "lagarde": "EMU", "the euro": "EMU",
    "bank of japan": "JPN", "japanese yen": "JPN", "japan": "JPN",
    "tokyo": "JPN", "japanese": "JPN",
    "bank of england": "GBR", "united kingdom": "GBR", "britain": "GBR",
    "british pound": "GBR", "pound sterling": "GBR", "london": "GBR",
    "british": "GBR", "threadneedle": "GBR",
    "bank of canada": "CAN", "canadian dollar": "CAN", "canada": "CAN",
    "ottawa": "CAN", "canadian": "CAN",
    "reserve bank of australia": "AUS", "australian dollar": "AUS",
    "australia": "AUS", "sydney": "AUS", "canberra": "AUS", "australian": "AUS",
    "reserve bank of new zealand": "NZL", "new zealand": "NZL",
    "wellington": "NZL", "new zealand dollar": "NZL",
    "swiss national bank": "CHE", "swiss franc": "CHE", "switzerland": "CHE",
    "zurich": "CHE", "swiss": "CHE",
    "norges bank": "NOR", "norwegian krone": "NOR", "norway": "NOR",
    "oslo": "NOR", "norwegian": "NOR",
    "sveriges riksbank": "SWE", "riksbank": "SWE", "swedish krona": "SWE",
    "sweden": "SWE", "stockholm": "SWE", "swedish": "SWE",
    # ---------- CENTRAL-BANK ABBREVIATIONS ----------
    # Safe ONLY because matching is word-boundary based: "\becb\b" cannot fire
    # inside another word. Deliberately EXCLUDED: "fed" ("fed up", "he fed"),
    # "mas", "real", "won", "dong", "rand" -- all common English words.
    "ecb": "EMU", "boj": "JPN", "boe": "GBR", "pboc": "CHN", "rbi": "IND",
    "snb": "CHE", "bok": "KOR", "bsp": "PHL", "bnm": "MYS", "sarb": "ZAF",
    "cbrt": "TUR", "banxico": "MEX", "rbnz": "NZL", "rba": "AUS",
    "hkma": "HKG", "sama": "SAU", "cbn": "NGA", "mnb": "HUN", "cnb": "CZE",
}

# Words we refuse to match even if they appear in config aliases, because they
# are ordinary English and produced the original mis-tagging
# ("mas" inside "Christmas" -> Singapore).
ALIAS_BLOCKLIST = {"mas", "real", "won", "dong", "rand", "fed", "boe", "boj",
                   "ecb", "rbi", "bsp", "baht", "yen", "yuan", "lira", "modi",
                   "lula", "amlo", "sek", "nok"}

# Keywords that are STEMS, not whole words: match a prefix, no trailing \b.
# You can also mark any config keyword as a stem by ending it with "*".
LEGACY_PREFIXES = {"depreciat", "appreciat", "geopolitic"}


def _pattern_for(keyword: str) -> str:
    """Regex fragment for one keyword.

    Leading \\b always. Trailing \\b unless the keyword is a stem (ends with
    "*" in config, or is one of the legacy stems), because "depreciat" must
    match "depreciated" and "depreciation".
    """
    kw = keyword.strip().lower()
    prefix = kw.endswith("*") or kw in LEGACY_PREFIXES
    kw = kw.rstrip("*").strip()
    if not kw:
        return ""
    frag = r"\b" + re.escape(kw)
    # a trailing \b only makes sense if the keyword ends in a word character
    if not prefix and kw[-1].isalnum():
        frag += r"\b"
    return frag


# ===================================================================
# COUNTRY TAGGING
# ===================================================================
def _build_alias_table() -> dict[str, str]:
    """BASE_ALIASES + config aliases + plain country names."""
    table = dict(BASE_ALIASES)
    for alias, iso3 in getattr(config, "NEWS_COUNTRY_ALIASES", {}).items():
        a = str(alias).lower().strip()
        if len(a) >= 4 and a not in ALIAS_BLOCKLIST:
            table.setdefault(a, iso3)
    for iso3, name, *_ in config.COUNTRIES:
        table.setdefault(str(name).lower(), iso3)
    return table


ALIAS_TABLE = _build_alias_table()

# ONE combined alternation regex instead of ~250 separate ones.
# Longest alias first so "bank of korea" wins before "korea".
_ALIAS_KEYS = sorted(ALIAS_TABLE, key=len, reverse=True)
COUNTRY_RX = re.compile("|".join(_pattern_for(k) for k in _ALIAS_KEYS if _pattern_for(k)))

# findall returns the matched TEXT, so we look the iso3 back up here.
_ALIAS_LOOKUP = {k: v for k, v in ALIAS_TABLE.items()}


def tag_countries(text: str) -> str:
    """Comma-separated iso3 tags for one headline (word-boundary safe).

    Order of appearance is preserved and duplicates removed, so a headline
    naming Brazil twice yields "BRA", not "BRA,BRA".
    """
    if not text:
        return ""
    low = str(text).lower()
    found: list[str] = []
    for m in COUNTRY_RX.findall(low):
        iso3 = _ALIAS_LOOKUP.get(m)
        if iso3 is None:
            # stem match: findall returned e.g. "depreciated" -- resolve by prefix
            for k, v in _ALIAS_LOOKUP.items():
                if m.startswith(k):
                    iso3 = v
                    break
        if iso3 and iso3 not in found:
            found.append(iso3)
    return ",".join(found)


def tag_countries_many(texts) -> list[str]:
    """Bulk version for the dashboard (which re-tags every row on load)."""
    return [tag_countries(t) for t in texts]


# ===================================================================
# TOPIC TAGGING
# ===================================================================
def _build_topic_lookup():
    """keyword -> [topics].  A keyword can belong to several topics (a CPI
    print is both econ_data and central_bank) -- overlap is intended."""
    lookup: dict[str, list[str]] = {}
    for topic, words in config.NEWS_TOPICS.items():
        for w in words:
            k = str(w).strip().lower().rstrip("*").strip()
            if not k:
                continue
            lookup.setdefault(k, [])
            if topic not in lookup[k]:
                lookup[k].append(topic)
    return lookup


TOPIC_LOOKUP = _build_topic_lookup()
_TOPIC_KEYS = sorted(TOPIC_LOOKUP, key=len, reverse=True)
TOPIC_RX = re.compile("|".join(_pattern_for(k) for k in _TOPIC_KEYS if _pattern_for(k)))


def topics_of(text: str) -> list[str]:
    """All topics whose keywords appear in the headline (multi-tag).

    v2: WORD-BOUNDARY matching. v1 used `if w in low`, which tagged "Goldman"
    as commodities ("gold"), "coalition" as energy ("coal"), "turmoil" as
    commodities ("oil"), and "Warning" as geopolitics ("war").
    """
    if not text:
        return ["general"]
    low = str(text).lower()
    hits: list[str] = []
    for m in TOPIC_RX.findall(low):
        topics = TOPIC_LOOKUP.get(m)
        if topics is None:
            for k, v in TOPIC_LOOKUP.items():
                if m.startswith(k):
                    topics = v
                    break
        for t in (topics or []):
            if t not in hits:
                hits.append(t)
    return hits or ["general"]


def topics_of_many(texts) -> list[list[str]]:
    """Bulk version for the dashboard."""
    return [topics_of(t) for t in texts]


def topic_of(text: str) -> str:
    """First matching topic (backward-compatible single tag)."""
    return topics_of(text)[0]


# ===================================================================
# [1] RSS
# ===================================================================
def _parse_entry_time(entry) -> str:
    """Feed timestamp as an ISO string.

    IMPORTANT: feedparser normalises published_parsed to **UTC**, and we store
    it naive (no tz suffix). The dashboard converts to local time for display
    using config.NEWS_TZ_OFFSET_HOURS. Do not "fix" this by writing local time
    into the DB -- storing UTC and converting at the edge is the correct shape.

    GUARD: some feeds (boc, bis_press) publish malformed/future dates. Any
    timestamp more than a day ahead of now is clamped to now, so a bad feed
    can't park itself permanently at the top of the feed.
    """
    now = dt.datetime.utcnow()
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                parsed = dt.datetime(*t[:6])
            except Exception:
                continue
            if parsed > now + dt.timedelta(days=1):
                parsed = now                      # clamp future -> now
            return parsed.isoformat(timespec="seconds")
    return now.isoformat(timespec="seconds")


def fetch_rss(limit: int | None = None, replace: bool = False) -> int:
    try:
        import feedparser
    except ImportError:
        print("    [RSS] feedparser not installed -> pip install feedparser")
        return 0

    origin = getattr(config, "FEED_ORIGIN_ISO", {})
    feeds = config.RSS_FEEDS[:limit] if limit else config.RSS_FEEDS
    print(f"[news] RSS -- {len(feeds)} feeds")
    total = 0

    for source_id, name, tier, url in feeds:
        try:
            parsed = feedparser.parse(url, agent=BROWSER_UA)
        except Exception as e:
            print(f"    [RSS] {source_id}: FAILED ({e})")
            continue
        status = getattr(parsed, "status", "?")
        if not parsed.entries:
            print(f"    [RSS] {source_id}: no entries "
                  f"(HTTP {status} -- check URL / UA / firewall)")
            continue

        rows = []
        for e in parsed.entries:
            headline = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if not headline or not link:
                continue
            ts = _parse_entry_time(e)
            iso3_tags = tag_countries(headline)          # v2: word-boundary
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
    """GDELT seendate ends in 'Z' -- it is UTC. Stored naive, like RSS."""
    try:
        return dt.datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").isoformat(
            timespec="seconds")
    except Exception:
        return dt.datetime.utcnow().isoformat(timespec="seconds")


def fetch_gdelt(limit: int | None = None, replace: bool = False) -> int:
    timespan = os.getenv("EMDASH_GDELT_TIMESPAN") or config.GDELT_TIMESPAN
    if not config.GDELT_ENABLED:
        print("[news] GDELT disabled in config")
        return 0

    countries = [c for c in config.COUNTRIES
                 if (not config.GDELT_EM_ONLY or c[3] == "EM")]
    if limit:
        countries = countries[:limit]

    print(f"[news] GDELT -- {len(countries)} countries "
          f"(timespan={timespan}, tier={config.GDELT_TIER})")
    total = 0

    for iso3, name, *_ in countries:
        q = f'"{name}"'
        if config.GDELT_LANG:
            q += f" sourcelang:{config.GDELT_LANG}"
        articles = _gdelt_query(q, config.GDELT_MAXRECORDS, timespan)

        rows = []
        for a in articles:
            headline = (a.get("title") or "").strip()
            link = (a.get("url") or "").strip()
            if not headline or not link:
                continue
            ts = _gdelt_seendate_to_iso(a.get("seendate", ""))
            # GDELT already tells us which country query matched, but the
            # headline may name others too -- keep the query country FIRST,
            # then append anything else the matcher finds.
            extra = tag_countries(headline)
            tags = iso3
            for t in extra.split(","):
                if t and t != iso3:
                    tags += "," + t
            rows.append((ts, "gdelt", config.GDELT_TIER, tags, headline, link, None))

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
    removed = core.dedupe_news()
    if removed:
        print(f"[news] de-duped {removed} rows sharing a URL")
    print("[news] table counts:", core.table_counts())
    print("[news] done.")


# ===================================================================
# SELF-TEST  (no network, no DB)
# ===================================================================
def _selftest():
    country_cases = [
        # the original bugs -- all must now be UNTAGGED
        ("Christmas Day trading volumes hit record low", ""),
        ("Investors fed up with real returns as stocks won gains", ""),
        ("Brand new factory opens in Detroit", ""),
        ("Modi announces plan to modify tariffs", "IND"),
        # long-form institutions
        ("Bangko Sentral ng Pilipinas cuts policy rate", "PHL"),
        ("Monetary Authority of Singapore tightens policy", "SGP"),
        ("Banco Central do Brasil signals pause", "BRA"),
        ("Bank of England raises Bank Rate", "GBR"),
        # abbreviations are safe under word boundaries
        ("ECB holds rates steady", "EMU"),
        ("The Fed is expected to cut in September", "USA"),
        # qualified ambiguous words
        ("Korean won slides to two-year low", "KOR"),
        ("Brazilian real rallies on rate bets", "BRA"),
    ]
    topic_cases = [
        # the v1 topic bugs -- these keywords must NOT fire any more
        ("Goldman Sachs raises year-end target", "commodities"),
        ("Coalition talks collapse after setbacks", "energy"),
        ("Markets in turmoil as risk appetite evaporates", "commodities"),
        ("Warning signs mount for global growth", "geopolitics"),
        ("Corporate bond issuance accelerates", "central_bank"),
    ]

    print("=" * 72)
    print("COUNTRY TAGGING")
    print("=" * 72)
    cok = 0
    for text, want in country_cases:
        got = tag_countries(text)
        ok = (got == want)
        cok += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:44]:46} -> "
              f"{got or '(none)':10} want {want or '(none)'}")

    print()
    print("=" * 72)
    print("TOPIC TAGGING  (the listed topic must NOT be present)")
    print("=" * 72)
    tok = 0
    for text, bad in topic_cases:
        got = topics_of(text)
        ok = bad not in got
        tok += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:44]:46} -> "
              f"{', '.join(got)[:34]:36} (no '{bad}')")

    print()
    print("=" * 72)
    print("TOPICS STILL FIRE WHEN THEY SHOULD")
    print("=" * 72)
    positive = [
        ("Gold prices hit a record high", "commodities"),
        ("Coal output falls in Shanxi", "energy"),
        ("Oil slips as OPEC weighs output", "commodities"),
        ("War in the region escalates", "geopolitics"),
        ("Fed holds interest rate steady", "central_bank"),
        ("Rupiah depreciated sharply", "fx"),          # stem test
    ]
    pok = 0
    for text, want in positive:
        got = topics_of(text)
        ok = want in got
        pok += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:44]:46} -> "
              f"{', '.join(got)[:34]:36} (has '{want}')")

    total = cok + tok + pok
    n = len(country_cases) + len(topic_cases) + len(positive)
    print(f"\n  {total}/{n} passed")
    print(f"  alias table: {len(ALIAS_TABLE)} entries -> 1 combined regex")
    print(f"  topic table: {len(TOPIC_LOOKUP)} keywords -> 1 combined regex")
    return total == n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["rss", "gdelt"], help="run one source type")
    ap.add_argument("--limit", type=int, help="cap feeds / countries")
    ap.add_argument("--refresh", action="store_true", help="overwrite existing rows")
    ap.add_argument("--selftest", action="store_true",
                    help="tagging tests only (no network, no DB)")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(0 if _selftest() else 1)
    run_news(only=args.only, limit=args.limit, refresh=args.refresh)
