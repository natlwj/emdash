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
    - promote a news domain's tier       -> DOMAIN_TIER
    - add / change news topics           -> NEWS_TOPICS
    - tag people/places to a country     -> NEWS_COUNTRY_ALIASES
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
DB_PATH = ROOT / "emdash.sqlite"
SEED_DIR = ROOT / "seed"


# -------------------------------------------------------------------
# FEATURE FLAGS
# -------------------------------------------------------------------
FEATURE_FLAGS = {
    "ingest_worldbank":   True,
    "ingest_dbnomics":    True,
    "ingest_yahoo_fx":    True,
    "ingest_commodities": True,
    "ingest_gdelt":       False,
    "ingest_predmarkets": False,
    "ingest_trends":      False,
    "ingest_rss":         True,
    "module_regime_mrc":  False,
}


# -------------------------------------------------------------------
# COUNTRIES  ::  (iso3, name, desk, dm_em, fx_ticker)
# DESKS: SEA | EASTASIA | CSASIA | LATAM | MEA | EMEUROPE | G10
# -------------------------------------------------------------------
COUNTRIES = [
    ("IDN", "Indonesia",     "SEA",      "EM", "IDR=X"),
    ("MYS", "Malaysia",      "SEA",      "EM", "MYR=X"),
    ("THA", "Thailand",      "SEA",      "EM", "THB=X"),
    ("PHL", "Philippines",   "SEA",      "EM", "PHP=X"),
    ("VNM", "Vietnam",       "SEA",      "EM", "VND=X"),
    ("SGP", "Singapore",     "SEA",      "DM", "SGD=X"),
    ("CHN", "China",         "EASTASIA", "EM", "CNY=X"),
    ("KOR", "South Korea",   "EASTASIA", "EM", "KRW=X"),
    ("TWN", "Taiwan",        "EASTASIA", "EM", "TWD=X"),
    ("HKG", "Hong Kong",     "EASTASIA", "DM", "HKD=X"),
    ("IND", "India",         "CSASIA",   "EM", "INR=X"),
    ("PAK", "Pakistan",      "CSASIA",   "EM", "PKR=X"),
    ("BGD", "Bangladesh",    "CSASIA",   "EM", "BDT=X"),
    ("LKA", "Sri Lanka",     "CSASIA",   "EM", "LKR=X"),
    ("KAZ", "Kazakhstan",    "CSASIA",   "EM", "KZT=X"),
    ("BRA", "Brazil",        "LATAM",    "EM", "BRL=X"),
    ("MEX", "Mexico",        "LATAM",    "EM", "MXN=X"),
    ("CHL", "Chile",         "LATAM",    "EM", "CLP=X"),
    ("COL", "Colombia",      "LATAM",    "EM", "COP=X"),
    ("PER", "Peru",          "LATAM",    "EM", "PEN=X"),
    ("ARG", "Argentina",     "LATAM",    "EM", "ARS=X"),
    ("ZAF", "South Africa",  "MEA",      "EM", "ZAR=X"),
    ("SAU", "Saudi Arabia",  "MEA",      "EM", "SAR=X"),
    ("ARE", "UAE",           "MEA",      "EM", "AED=X"),
    ("EGY", "Egypt",         "MEA",      "EM", "EGP=X"),
    ("NGA", "Nigeria",       "MEA",      "EM", "NGN=X"),
    ("KEN", "Kenya",         "MEA",      "EM", "KES=X"),
    ("POL", "Poland",        "EMEUROPE", "EM", "PLN=X"),
    ("HUN", "Hungary",       "EMEUROPE", "EM", "HUF=X"),
    ("CZE", "Czechia",       "EMEUROPE", "EM", "CZK=X"),
    ("ROU", "Romania",       "EMEUROPE", "EM", "RON=X"),
    ("TUR", "Turkey",        "EMEUROPE", "EM", "TRY=X"),
    ("USA", "United States", "G10",      "DM", ""),
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
# TAGS  ::  (iso3, tag)
# -------------------------------------------------------------------
TAGS = [
    ("SAU", "oil_exporter"), ("ARE", "oil_exporter"), ("NGA", "oil_exporter"),
    ("NOR", "oil_exporter"), ("COL", "oil_exporter"), ("KAZ", "oil_exporter"),
    ("CHL", "metals_exporter"), ("PER", "metals_exporter"),
    ("ZAF", "metals_exporter"), ("AUS", "metals_exporter"), ("BRA", "metals_exporter"),
    ("BRA", "ag_exporter"), ("ARG", "ag_exporter"), ("IDN", "ag_exporter"),
    ("MYS", "ag_exporter"),
    ("KOR", "tech_exporter"), ("TWN", "tech_exporter"), ("SGP", "tech_exporter"),
    ("SAU", "usd_peg"), ("ARE", "usd_peg"), ("HKG", "usd_peg"),
    ("TUR", "high_yield"), ("ARG", "high_yield"), ("EGY", "high_yield"),
    ("NGA", "high_yield"), ("PAK", "high_yield"),
]


# -------------------------------------------------------------------
# SOURCE REGISTRY
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
# WORLD BANK INDICATORS
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

DBN_SERIES = {
    "POLICY_RATE":  ("IMF", "IFS", "M.{iso2}.FPOLM_PA"),
    "CPI_INDEX_M":  ("IMF", "IFS", "M.{iso2}.PCPI_IX"),
}


# -------------------------------------------------------------------
# COMMODITIES / GLOBAL MARKET
# -------------------------------------------------------------------
COMMODITIES = {
    "BRENT": "BZ=F", "WTI": "CL=F", "NATGAS": "NG=F", "COAL": "MTF=F",
    "IRON": "TIO=F", "COPPER": "HG=F", "ALUMIN": "ALI=F", "GOLD": "GC=F",
    "SILVER": "SI=F", "WHEAT": "ZW=F", "CORN": "ZC=F", "SOYBEAN": "ZS=F",
}

MARKET_TICKERS = {
    "DXY": "DX-Y.NYB", "VIX": "^VIX", "MOVE": "^MOVE", "US10Y": "^TNX",
    "SPX": "^GSPC", "EMB": "EMB", "EMHY": "EMHY", "GOLD_ETF": "GLD",
}

HISTORY = {"macro_years": 25, "market_years": 15}


# ===================================================================
# NEWS LAYER
# ===================================================================

# -------------------------------------------------------------------
# RSS_FEEDS  ::  (source_id, name, tier, url)
# -------------------------------------------------------------------
RSS_FEEDS = [
    # ---- Tier A ----
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
    # ---- Tier B ----
    ("bruegel",   "Bruegel (think tank)",         "B", "https://www.bruegel.org/rss.xml"),
    ("cfr",       "Council on Foreign Relations",  "B", "https://www.cfr.org/rss.xml"),
    ("guardian",  "The Guardian (business)",      "B", "https://www.theguardian.com/business/rss"),
    # ---- Tier C ----
    # Substacks: append '/feed' to the base URL.
    # ("noahpinion", "Noahpinion (Substack)",     "C", "https://www.noahpinion.blog/feed"),
]

# -------------------------------------------------------------------
# DOMAIN_TIER  ::  domain -> tier.  Promotes GDELT firehose articles by
# PUBLISHER quality (GDELT tags everything C; a Reuters story deserves A).
# Applied at DISPLAY time in app.py -> fixes existing rows with no re-pull.
# Add a domain = curate your quality list.
# -------------------------------------------------------------------
DOMAIN_TIER = {
    # Tier A: wires / flagship financial press / officials
    "reuters.com": "A", "ft.com": "A", "bloomberg.com": "A",
    "wsj.com": "A", "economist.com": "A", "apnews.com": "A",
    "nytimes.com": "A", "cnbc.com": "A", "imf.org": "A",
    "worldbank.org": "A", "bis.org": "A", "ecb.europa.eu": "A",
    "federalreserve.gov": "A", "bankofengland.co.uk": "A",
    "bankofcanada.ca": "A", "boj.or.jp": "A",
    # Tier B: solid outlets / research
    "theguardian.com": "B", "bbc.com": "B", "bbc.co.uk": "B",
    "aljazeera.com": "B", "scmp.com": "B", "nikkei.com": "B",
    "cfr.org": "B", "bruegel.org": "B", "project-syndicate.org": "B",
    "foreignpolicy.com": "B", "politico.com": "B", "cnn.com": "B",
}

# -------------------------------------------------------------------
# FEED_ORIGIN_ISO  ::  source_id -> iso3 fallback (central-bank feeds).
# -------------------------------------------------------------------
FEED_ORIGIN_ISO = {
    "fed": "USA", "ecb": "EMU", "boe": "GBR", "boj": "JPN", "boc": "CAN",
}

# -------------------------------------------------------------------
# GDELT
# -------------------------------------------------------------------
GDELT_ENABLED     = True
GDELT_TIER        = "C"
GDELT_TIMESPAN    = "3d"
GDELT_MAXRECORDS  = 60
GDELT_LANG        = "english"
GDELT_EM_ONLY     = True
GDELT_SLEEP_SEC   = 2.0

# -------------------------------------------------------------------
# NEWS_COUNTRY_ALIASES  ::  keyword -> iso3.  Includes leaders / institutions /
# currencies / capitals so headlines that never name the country still tag
# (e.g. "Trump" -> USA, "Erdogan" -> TUR, "Lula" -> BRA). Extend freely.
# -------------------------------------------------------------------
NEWS_COUNTRY_ALIASES = {
    # institutions
    "fed": "USA", "federal reserve": "USA", "fomc": "USA", "treasury": "USA",
    "white house": "USA", "congress": "USA", "wall street": "USA",
    "ecb": "EMU", "euro area": "EMU", "eurozone": "EMU", "brussels": "EMU",
    "boj": "JPN", "boe": "GBR", "pboc": "CHN", "rbi": "IND",
    "bank indonesia": "IDN", "bsp": "PHL", "mas": "SGP",
    # leaders (add/adjust as needed)
    "trump": "USA", "biden": "USA", "powell": "USA", "yellen": "USA",
    "xi jinping": "CHN", "xi ": "CHN", "li qiang": "CHN",
    "modi": "IND", "lula": "BRA", "milei": "ARG", "erdogan": "TUR",
    "putin": "RUS", "kishida": "JPN", "ishiba": "JPN", "prabowo": "IDN",
    "marcos": "PHL", "amlo": "MEX", "sheinbaum": "MEX", "ramaphosa": "ZAF",
    "lagarde": "EMU", "sunak": "GBR", "starmer": "GBR",
    # capitals
    "washington": "USA", "beijing": "CHN", "tokyo": "JPN", "jakarta": "IDN",
    "new delhi": "IND", "brasilia": "BRA", "ankara": "TUR", "moscow": "RUS",
    "seoul": "KOR", "pretoria": "ZAF", "buenos aires": "ARG",
    # currencies
    "rupiah": "IDN", "ringgit": "MYS", "baht": "THA", "peso": "PHL",
    "dong": "VNM", "yuan": "CHN", "renminbi": "CHN", "won": "KOR",
    "rupee": "IND", "real": "BRA", "lira": "TUR", "rand": "ZAF",
    "zloty": "POL", "forint": "HUN", "koruna": "CZE", "tenge": "KAZ",
    "naira": "NGA", "yen": "JPN", "sterling": "GBR",
}

# -------------------------------------------------------------------
# NEWS_TOPICS  ::  topic key -> keyword list.  A headline can now match
# MULTIPLE topics (news_ingest.topics_of returns all matches). Expanded to
# shrink the "General" pile. Add a bucket = add a key here.
# -------------------------------------------------------------------
NEWS_TOPICS = {
    "monetary_policy": ["rate", "rates", "central bank", "policy rate", "hike",
                         "rate cut", "hawkish", "dovish", "monetary",
                         "tightening", "easing", "fomc", "boj", "ecb"],
    "inflation":       ["inflation", "cpi", "ppi", "prices", "deflation",
                         "disinflation", "cost of living"],
    "growth":          ["gdp", "growth", "recession", "pmi", "output",
                         "manufacturing", "industrial", "jobs", "unemployment",
                         "payroll", "labour", "labor"],
    "trade":           ["trade", "tariff", "export", "import", "customs",
                         "supply chain", "wto", "sanction"],
    "commodities":     ["oil", "brent", "crude", "opec", "gas", "lng",
                         "copper", "gold", "iron ore", "wheat", "soybean",
                         "commodity", "commodities"],
    "credit_debt":     ["debt", "bond", "yield", "default", "credit",
                         "spread", "downgrade", "rating", "sovereign",
                         "restructuring", "imf loan", "bailout"],
    "fx_markets":      ["currency", "fx", "exchange rate", "devaluation",
                         "peg", "reserves", "capital flows", "depreciat"],
    "equities":        ["stocks", "equity", "equities", "shares", "ipo",
                         "index", "market rally", "selloff"],
    "geopolitics":     ["election", "government", "president", "coup",
                         "protest", "war", "conflict", "minister", "parliament",
                         "coalition", "referendum", "sanctions", "military"],
    "energy":          ["energy", "power", "electricity", "renewable",
                         "nuclear", "coal", "pipeline"],
    "tech":            ["chip", "semiconductor", "ai ", "tech", "data center",
                         "technology", "startup"],
    "china":           ["china", "beijing", "yuan", "pboc", "xi jinping",
                         "property", "evergrande"],
}


# -------------------------------------------------------------------
# LOOK & FEEL  ::  SMU Emerging Markets palette + Segoe UI
# -------------------------------------------------------------------
PALETTE = {
    "canvas":   "#E9EBEF",
    "gold":     "#948A54",
    "navy1":    "#1F497D",
    "navy2":    "#2E5C96",
    "navy3":    "#6593C4",
    "brown":    "#74592D",
    "grey":     "#939DAA",
    "ink":      "#1D2733",
    "muted":    "#6B7480",
    "card":     "#FFFFFF",
    "border":   "#DFE2E8",
    "good":     "#2E7D46",
    "bad":      "#B4453A",
}

FONTS = {
    "ui":   "'Segoe UI', 'Segoe UI Web', system-ui, sans-serif",
    "mono": "'Consolas', 'Segoe UI Mono', monospace",
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def iso3_to_iso2(iso3: str) -> str:
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
