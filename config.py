"""
EMDASH :: config.py
===================================================================
THE CONTROL PANEL. This is the only file you edit to change *what*
EMDASH covers or how it looks. No logic lives here -- pure settings.

Edit here to:
    - add / remove a country            -> COUNTRIES
    - regroup desks or tags             -> COUNTRIES / TAGS
    - add / change a data source        -> SOURCES + INDICATOR maps
    - add / change a macro indicator     -> WB_INDICATORS / DBN_SERIES
    - add / change a market series       -> FX handled per-country; MARKET_TICKERS
    - add / change a commodity           -> COMMODITIES
    - add / change a NEWS feed           -> RSS_FEEDS / GDELT_* / NEWS_*
    - change colours / fonts            -> PALETTE / FONTS
    - turn a whole module on/off        -> FEATURE_FLAGS

Everything downstream (core, ingest, news_ingest, signals, app) reads from here.
===================================================================
"""

from pathlib import Path

# -------------------------------------------------------------------
# PATHS
# -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "emdash.sqlite"      # the ONE data file (gitignored)
SEED_DIR = ROOT / "seed"              # one-time paid-source exports (Bloomberg etc.)


# -------------------------------------------------------------------
# FEATURE FLAGS  -- flip a module on/off without touching other code
# -------------------------------------------------------------------
FEATURE_FLAGS = {
    "ingest_worldbank":   True,
    "ingest_dbnomics":    True,
    "ingest_yahoo_fx":    True,
    "ingest_commodities": True,
    "ingest_gdelt":       False,   # Phase 4
    "ingest_predmarkets": False,   # Phase 4
    "ingest_trends":      False,   # Phase 4
    "ingest_rss":         True,    # NEWS: curated RSS/Atom feeds (news_ingest.py)
    "module_regime_mrc":  False,   # Phase 5
}


# -------------------------------------------------------------------
# COUNTRIES  ::  (iso3, name, desk, dm_em, fx_ticker)
# -------------------------------------------------------------------
# desk = SMUEM's 6 EM desks + "G10" for developed markets.
# fx_ticker is the Yahoo Finance symbol (LCY per USD). "" = none / peg / n.a.
#
# DESKS: SEA | EASTASIA | CSASIA | LATAM | MEA | EMEUROPE | G10
# -------------------------------------------------------------------
COUNTRIES = [
    # ---- SEA ----
    ("IDN", "Indonesia",     "SEA",      "EM", "IDR=X"),
    ("MYS", "Malaysia",      "SEA",      "EM", "MYR=X"),
    ("THA", "Thailand",      "SEA",      "EM", "THB=X"),
    ("PHL", "Philippines",   "SEA",      "EM", "PHP=X"),
    ("VNM", "Vietnam",       "SEA",      "EM", "VND=X"),
    ("SGP", "Singapore",     "SEA",      "DM", "SGD=X"),
    # ---- EAST ASIA ----
    ("CHN", "China",         "EASTASIA", "EM", "CNY=X"),
    ("KOR", "South Korea",   "EASTASIA", "EM", "KRW=X"),
    ("TWN", "Taiwan",        "EASTASIA", "EM", "TWD=X"),
    ("HKG", "Hong Kong",     "EASTASIA", "DM", "HKD=X"),
    # ---- CENTRAL / SOUTH ASIA ----
    ("IND", "India",         "CSASIA",   "EM", "INR=X"),
    ("PAK", "Pakistan",      "CSASIA",   "EM", "PKR=X"),
    ("BGD", "Bangladesh",    "CSASIA",   "EM", "BDT=X"),
    ("LKA", "Sri Lanka",     "CSASIA",   "EM", "LKR=X"),
    ("KAZ", "Kazakhstan",    "CSASIA",   "EM", "KZT=X"),
    # ---- LATAM ----
    ("BRA", "Brazil",        "LATAM",    "EM", "BRL=X"),
    ("MEX", "Mexico",        "LATAM",    "EM", "MXN=X"),
    ("CHL", "Chile",         "LATAM",    "EM", "CLP=X"),
    ("COL", "Colombia",      "LATAM",    "EM", "COP=X"),
    ("PER", "Peru",          "LATAM",    "EM", "PEN=X"),
    ("ARG", "Argentina",     "LATAM",    "EM", "ARS=X"),
    # ---- MEA (Middle East + Africa) ----
    ("ZAF", "South Africa",  "MEA",      "EM", "ZAR=X"),
    ("SAU", "Saudi Arabia",  "MEA",      "EM", "SAR=X"),
    ("ARE", "UAE",           "MEA",      "EM", "AED=X"),
    ("EGY", "Egypt",         "MEA",      "EM", "EGP=X"),
    ("NGA", "Nigeria",       "MEA",      "EM", "NGN=X"),
    ("KEN", "Kenya",         "MEA",      "EM", "KES=X"),
    # ---- EMERGING EUROPE ----
    ("POL", "Poland",        "EMEUROPE", "EM", "PLN=X"),
    ("HUN", "Hungary",       "EMEUROPE", "EM", "HUF=X"),
    ("CZE", "Czechia",       "EMEUROPE", "EM", "CZK=X"),
    ("ROU", "Romania",       "EMEUROPE", "EM", "RON=X"),
    ("TUR", "Turkey",        "EMEUROPE", "EM", "TRY=X"),
    # ---- G10 (Developed Markets) ----
    ("USA", "United States", "G10",      "DM", ""),       # base currency
    ("EMU", "Eurozone",      "G10",      "DM", "EUR=X"),
    ("JPN", "Japan",         "G10",      "DM", "JPY=X"),
    ("GBR", "United Kingdom","G10",      "DM", "GBP=X"),
    ("CAN", "Canada",        "G10",      "DM", "CAD=X"),
    ("AUS", "Australia",     "G10",      "DM", "AUD=X"),
    ("NZL", "New Zealand",   "G10",      "DM", "NZD=X"),
    ("CHE", "Switzerland",   "G10",      "DM", "CHF=X"),
    ("NOR", "Norway",        "G10",      "DM", "NOK=X"),
    ("SWE", "Sweden",        "G10",      "DM", "SEK=X"),
]

# Human-readable desk labels for the UI
DESK_LABELS = {
    "SEA":      "Southeast Asia",
    "EASTASIA": "East Asia",
    "CSASIA":   "Central & South Asia",
    "LATAM":    "Latin America",
    "MEA":      "Middle East & Africa",
    "EMEUROPE": "Emerging Europe",
    "G10":      "Developed Markets (G10)",
}


# -------------------------------------------------------------------
# TAGS  ::  derived cross-country groups. (iso3, tag)
# One country can carry many tags. Queried on-click in the dashboard.
# -------------------------------------------------------------------
TAGS = [
    # oil / energy exporters
    ("SAU", "oil_exporter"), ("ARE", "oil_exporter"), ("NGA", "oil_exporter"),
    ("NOR", "oil_exporter"), ("COL", "oil_exporter"), ("KAZ", "oil_exporter"),
    # metals / mining exporters
    ("CHL", "metals_exporter"), ("PER", "metals_exporter"),
    ("ZAF", "metals_exporter"), ("AUS", "metals_exporter"),
    ("BRA", "metals_exporter"),
    # ag exporters
    ("BRA", "ag_exporter"), ("ARG", "ag_exporter"), ("IDN", "ag_exporter"),
    ("MYS", "ag_exporter"),
    # tech / semis exporters
    ("KOR", "tech_exporter"), ("TWN", "tech_exporter"), ("SGP", "tech_exporter"),
    # USD peg / managed
    ("SAU", "usd_peg"), ("ARE", "usd_peg"), ("HKG", "usd_peg"),
    # high-yield / fragile
    ("TUR", "high_yield"), ("ARG", "high_yield"), ("EGY", "high_yield"),
    ("NGA", "high_yield"), ("PAK", "high_yield"),
]


# -------------------------------------------------------------------
# SOURCE REGISTRY  ::  (source_id, name, type, tier, frequency)
# type: macro | market | commodity | alt | news
# tier: A (primary/official) | B (commentary) | C (informal)
# The ingest layer loops these; each maps to a fetcher in ingest.py.
# -------------------------------------------------------------------
SOURCES = [
    ("worldbank",   "World Bank",        "macro",     "A", "annual"),
    ("dbnomics",    "DBnomics (IMF/OECD/ECB agg.)", "macro", "A", "monthly"),
    ("yahoo_fx",    "Yahoo Finance (FX)", "market",   "A", "daily"),
    ("yahoo_cmdty", "Yahoo Finance (Commodities)", "commodity", "A", "daily"),
    ("gdelt",       "GDELT",             "news",      "A", "15min"),
    ("polymarket",  "Polymarket",        "alt",       "C", "hourly"),
    ("kalshi",      "Kalshi",            "alt",       "C", "hourly"),
    ("gtrends",     "Google Trends",     "alt",       "C", "daily"),
    ("seed",        "Seed (Bloomberg exports)", "market", "A", "static"),
]


# -------------------------------------------------------------------
# WORLD BANK INDICATORS  ::  label -> WB code   (annual, broad coverage)
# -------------------------------------------------------------------
WB_INDICATORS = {
    "GDP_YOY":      "NY.GDP.MKTP.KD.ZG",
    "CPI_YOY":      "FP.CPI.TOTL.ZG",
    "CURR_ACC_GDP": "BN.CAB.XOKA.GD.ZS",
    "GOV_DEBT_GDP": "GC.DOD.TOTL.GD.ZS",
    "UNEMPLOYMENT": "SL.UEM.TOTL.ZS",
    "EXPORTS_GDP":  "NE.EXP.GNFS.ZS",
    "FDI_GDP":      "BX.KLT.DINV.WD.GD.ZS",
    "RESERVES_USD": "FI.RES.TOTL.CD",
}


# -------------------------------------------------------------------
# DBNOMICS SERIES  ::  label -> (provider, dataset, series_mask)
# Higher-frequency macro. Mask uses DBnomics dotted series codes.
# NOTE: coverage varies by country; ingest flags gaps rather than faking.
# These are examples for the pipeline; expand freely -- config only.
# -------------------------------------------------------------------
DBN_SERIES = {
    # IMF International Financial Statistics - policy rate (monthly)
    # provider/dataset/series pattern; ingest.py fills country code in mask
    "POLICY_RATE":  ("IMF", "IFS", "M.{iso2}.FPOLM_PA"),
    "CPI_INDEX_M":  ("IMF", "IFS", "M.{iso2}.PCPI_IX"),
}


# -------------------------------------------------------------------
# COMMODITIES  ::  label -> Yahoo futures ticker
# -------------------------------------------------------------------
COMMODITIES = {
    "BRENT":   "BZ=F",
    "WTI":     "CL=F",
    "NATGAS":  "NG=F",
    "COAL":    "MTF=F",
    "IRON":    "TIO=F",
    "COPPER":  "HG=F",
    "ALUMIN":  "ALI=F",
    "GOLD":    "GC=F",
    "SILVER":  "SI=F",
    "WHEAT":   "ZW=F",
    "CORN":    "ZC=F",
    "SOYBEAN": "ZS=F",
}


# -------------------------------------------------------------------
# GLOBAL MARKET SERIES  ::  label -> Yahoo ticker (risk/regime proxies)
# Used by signals + MRC as global risk-appetite reads.
# -------------------------------------------------------------------
MARKET_TICKERS = {
    "DXY":     "DX-Y.NYB",   # US dollar index
    "VIX":     "^VIX",       # equity vol
    "MOVE":    "^MOVE",      # rate vol (may be spotty on Yahoo)
    "US10Y":   "^TNX",       # US 10y yield (x10)
    "SPX":     "^GSPC",      # S&P 500
    "EMB":     "EMB",        # EM USD sovereign ETF (credit proxy)
    "EMHY":    "EMHY",       # EM high-yield ETF (credit proxy)
    "GOLD_ETF":"GLD",
}


# -------------------------------------------------------------------
# INGEST WINDOWS  ::  how much history to pull
# -------------------------------------------------------------------
HISTORY = {
    "macro_years":  25,   # World Bank / DBnomics
    "market_years": 15,   # Yahoo FX / commodities / market
}


# ===================================================================
# NEWS LAYER  ::  feeds live here (control panel); logic lives in
# news_ingest.py. All headlines land in the `news` table (core.py).
# ===================================================================

# -------------------------------------------------------------------
# RSS_FEEDS  ::  (source_id, name, tier, url)
# tier A = official / wires | B = research / commentary | C = niche / blogs
# Add a feed = add a line. news_ingest.py needs NO edits.
# NOTE: feed URLs drift over time -- if one goes quiet, verify the URL
# on the publisher's site and update it here. (Verified live Jul-2026.)
# -------------------------------------------------------------------
RSS_FEEDS = [
    # ---- Tier A : central banks / official bodies / wires ----
    ("fed",       "US Federal Reserve (press)",  "A", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ecb",       "European Central Bank (press)","A", "https://www.ecb.europa.eu/rss/press.html"),
    ("boe",       "Bank of England (news)",       "A", "https://www.bankofengland.co.uk/rss/news"),
    ("boj",       "Bank of Japan (what's new)",   "A", "https://www.boj.or.jp/en/rss/whatsnew.xml"),
    ("boc",       "Bank of Canada",               "A", "https://www.bankofcanada.ca/feed/"),
    ("imf",       "IMF (news)",                   "A", "https://www.imf.org/en/News/RSS?Language=ENG"),
    ("bis_press", "BIS (press releases)",         "A", "https://www.bis.org/doclist/all_pressrels.rss"),
    ("bis_speech","BIS (central banker speeches)","A", "https://www.bis.org/doclist/cbspeeches.rss"),
    ("ft_em",     "FT Emerging Markets",          "A", "https://www.ft.com/emerging-markets?format=rss"),
    ("ft_econ",   "FT Global Economy",            "A", "https://www.ft.com/global-economy?format=rss"),
    ("ft_mkts",   "FT Markets",                   "A", "https://www.ft.com/markets?format=rss"),

    # ---- Tier B : research / think tanks / commentary ----
    #   (add bank research + think-tank feeds here as you find them)
    ("bruegel",   "Bruegel (think tank)",         "B", "https://www.bruegel.org/rss.xml"),

    # ---- Tier C : niche / independent / substacks / blogs ----
    #   Substacks: append '/feed' to the base URL -> instant RSS.
    #   Example placeholders -- swap for the writers you actually follow:
    # ("noahpinion", "Noahpinion (Substack)",     "C", "https://www.noahpinion.blog/feed"),
    # ("em_sherpa",  "EM Sherpa (Substack)",      "C", "https://emsherpa.substack.com/feed"),
]

# -------------------------------------------------------------------
# GDELT  ::  free global news firehose (per-country ArtList query).
# No API key. Rolling ~3-month window. Rate-limited -> we sleep between calls.
# Treated as a lower tier by default (unfiltered aggregation); the article
# domain is preserved in the URL so you can promote trusted domains later.
# -------------------------------------------------------------------
GDELT_ENABLED     = True
GDELT_TIER        = "C"      # firehose = default low tier; refine later
GDELT_TIMESPAN    = "3d"     # how far back per run (e.g. '24h', '3d', '1w')
GDELT_MAXRECORDS  = 60       # max articles per country per run (<=250)
GDELT_LANG        = "english"  # restrict to English coverage ("" = all)
GDELT_EM_ONLY     = True     # True = only pull EM countries (saves volume)
GDELT_SLEEP_SEC   = 1.2      # pause between country calls (avoid 429s)

# -------------------------------------------------------------------
# NEWS_COUNTRY_ALIASES  ::  extra keyword -> iso3 hints for tagging
# headlines that don't literally say the country name (currencies,
# central banks, capitals, common shorthand). Keys are matched
# case-insensitively as whole words against the headline.
# -------------------------------------------------------------------
NEWS_COUNTRY_ALIASES = {
    # institutions / shorthand
    "fed": "USA", "federal reserve": "USA", "fomc": "USA", "treasury": "USA",
    "ecb": "EMU", "euro area": "EMU", "eurozone": "EMU",
    "boj": "JPN", "boe": "GBR", "pboc": "CHN", "rbi": "IND",
    "bank indonesia": "IDN", "bsp": "PHL", "mas": "SGP",
    # currencies
    "rupiah": "IDN", "ringgit": "MYS", "baht": "THA", "peso": "PHL",
    "dong": "VNM", "yuan": "CHN", "renminbi": "CHN", "won": "KOR",
    "rupee": "IND", "real": "BRA", "lira": "TUR", "rand": "ZAF",
    "zloty": "POL", "forint": "HUN", "koruna": "CZE", "tenge": "KAZ",
    "naira": "NGA", "yen": "JPN", "sterling": "GBR",
}

# -------------------------------------------------------------------
# NEWS_TOPICS  ::  headline keyword -> Kanban column. Derived at DISPLAY
# time (news_ingest.topic_of), so no DB column / schema change needed.
# First bucket whose keywords match wins; order matters.
# -------------------------------------------------------------------
NEWS_TOPICS = {
    "monetary_policy": ["rate", "rates", "central bank", "policy", "hike",
                         "cut", "hawkish", "dovish", "inflation target",
                         "monetary", "tightening", "easing"],
    "inflation":       ["inflation", "cpi", "prices", "deflation",
                         "disinflation", "ppi", "cost of living"],
    "growth":          ["gdp", "growth", "recession", "pmi", "output",
                         "manufacturing", "unemployment", "jobs", "trade"],
    "politics":        ["election", "government", "president", "coup",
                         "protest", "sanction", "war", "conflict", "minister",
                         "parliament", "reform", "fiscal"],
    "markets":         ["bond", "yield", "equity", "stocks", "currency",
                         "fx", "default", "credit", "spread", "capital",
                         "reserves", "devaluation"],
}


# -------------------------------------------------------------------
# LOOK & FEEL  ::  SMU Emerging Markets palette + Segoe UI
# -------------------------------------------------------------------
PALETTE = {
    "canvas":   "#F2F2F2",   # light grey background
    "gold":     "#8C7604",   # highlight / alert accent
    "navy1":    "#071359",   # darkest navy (headers / anchors)
    "navy2":    "#04198C",   # mid navy
    "navy3":    "#051DA6",   # bright navy (links / active)
    "ink":      "#1a1a1a",   # body text
    "muted":    "#6b7280",   # secondary text
    "card":     "#FFFFFF",   # island card background
    "border":   "#d9dbe3",   # card borders
    "good":     "#0f7a3d",   # positive
    "bad":      "#b02a2a",   # negative
}

FONTS = {
    "ui":   "'Segoe UI', 'Segoe UI Web', system-ui, sans-serif",
    "mono": "'Consolas', 'Segoe UI Mono', monospace",  # numeric tables only
}


# -------------------------------------------------------------------
# Small helpers so other files don't re-derive these constantly.
# (Kept here because they're pure config-derived lookups.)
# -------------------------------------------------------------------
def iso3_to_iso2(iso3: str) -> str:
    """Rough ISO3->ISO2 map for DBnomics/IMF masks. Extend as needed."""
    _MAP = {
        "IDN": "ID", "MYS": "MY", "THA": "TH", "PHL": "PH", "VNM": "VN",
        "SGP": "SG", "CHN": "CN", "KOR": "KR", "TWN": "TW", "HKG": "HK",
        "IND": "IN", "PAK": "PK", "BGD": "BD", "LKA": "LK", "KAZ": "KZ",
        "BRA": "BR", "MEX": "MX", "CHL": "CL", "COL": "CO", "PER": "PE",
        "ARG": "AR", "ZAF": "ZA", "SAU": "SA", "ARE": "AE", "EGY": "EG",
        "NGA": "NG", "KEN": "KE", "POL": "PL", "HUN": "HU", "CZE": "CZ",
        "ROU": "RO", "TUR": "TR", "USA": "US", "EMU": "U2", "JPN": "JP",
        "GBR": "GB", "CAN": "CA", "AUS": "AU", "NZL": "NZ", "CHE": "CH",
        "NOR": "NO", "SWE": "SE",
    }
    return _MAP.get(iso3, "")
