"""
EMDASH :: config.py

THE CONTROL PANEL. This is the only file you edit to change WHAT EMDASH covers
or how it looks. No logic lives here -- pure settings.

Edit here to:
  - add / remove a country            -> COUNTRIES
  - regroup desks or tags             -> COUNTRIES / TAGS
  - add / change a data source        -> SOURCES + INDICATOR maps
  - add / change a macro indicator    -> WB_INDICATORS / DBN_SERIES
  - add / change a market series      -> FX per-country; MARKET_TICKERS
  - add / change a commodity          -> COMMODITIES
  - add / change a NEWS feed          -> RSS_FEEDS / GDELT_* / NEWS_*
  - promote a news domain's tier      -> DOMAIN_TIER
  - add / change news topics          -> NEWS_TOPICS
  - tag people/places to a country    -> NEWS_COUNTRY_ALIASES
  - change colours / fonts            -> PALETTE / FONTS
  - turn a whole module on/off        -> FEATURE_FLAGS

Everything downstream (core, ingest, news_ingest, signals, app) reads from here.

DESK CODES (renamed to a clean 3-5 letter convention):
    SEA · EAS · CSA · LATAM · MEA · EME · G10
"""
from pathlib import Path

# -------------------------------------------------------------------
# PATHS
# -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "emdash.sqlite"
SEED_DIR = ROOT / "seed"

# -------------------------------------------------------------------
# FEATURE FLAGS  ::  the single master on/off switches.
# NOTE: GDELT is now driven ONLY by this flag (see GDELT_ENABLED below) so there
# is one source of truth -- no more "flag says off but GDELT still ran".
# -------------------------------------------------------------------
FEATURE_FLAGS = {
    "ingest_worldbank":   True,
    "ingest_dbnomics":    True,
    "ingest_yahoo_fx":    True,
    "ingest_commodities": True,
    "ingest_gdelt":       True,      # <- was False while GDELT still ran; reconciled
    "ingest_predmarkets": False,
    "ingest_trends":      False,
    "ingest_rss":         True,
    "module_regime_mrc":  False,
}

# -------------------------------------------------------------------
# COUNTRIES  ::  (iso3, name, desk, dm_em, fx_ticker)
#   fx_ticker = Yahoo Finance symbol for that currency vs USD ("IDR=X" =
#   rupiah/USD). Empty "" means no FX to pull (USA: the dollar IS the base).
# DESKS: SEA | EAS | CSA | LATAM | MEA | EME | G10
# -------------------------------------------------------------------
COUNTRIES = [
    ("IDN", "Indonesia",     "SEA",   "EM", "IDR=X"),
    ("MYS", "Malaysia",      "SEA",   "EM", "MYR=X"),
    ("THA", "Thailand",      "SEA",   "EM", "THB=X"),
    ("PHL", "Philippines",   "SEA",   "EM", "PHP=X"),
    ("VNM", "Vietnam",       "SEA",   "EM", "VND=X"),
    ("SGP", "Singapore",     "SEA",   "DM", "SGD=X"),
    ("CHN", "China",         "EAS",   "EM", "CNY=X"),
    ("KOR", "South Korea",   "EAS",   "EM", "KRW=X"),
    ("TWN", "Taiwan",        "EAS",   "EM", "TWD=X"),
    ("HKG", "Hong Kong",     "EAS",   "DM", "HKD=X"),
    ("IND", "India",         "CSA",   "EM", "INR=X"),
    ("PAK", "Pakistan",      "CSA",   "EM", "PKR=X"),
    ("BGD", "Bangladesh",    "CSA",   "EM", "BDT=X"),
    ("LKA", "Sri Lanka",     "CSA",   "EM", "LKR=X"),
    ("KAZ", "Kazakhstan",    "CSA",   "EM", "KZT=X"),
    ("BRA", "Brazil",        "LATAM", "EM", "BRL=X"),
    ("MEX", "Mexico",        "LATAM", "EM", "MXN=X"),
    ("CHL", "Chile",         "LATAM", "EM", "CLP=X"),
    ("COL", "Colombia",      "LATAM", "EM", "COP=X"),
    ("PER", "Peru",          "LATAM", "EM", "PEN=X"),
    ("ARG", "Argentina",     "LATAM", "EM", "ARS=X"),
    ("ZAF", "South Africa",  "MEA",   "EM", "ZAR=X"),
    ("SAU", "Saudi Arabia",  "MEA",   "EM", "SAR=X"),
    ("ARE", "UAE",           "MEA",   "EM", "AED=X"),
    ("EGY", "Egypt",         "MEA",   "EM", "EGP=X"),
    ("NGA", "Nigeria",       "MEA",   "EM", "NGN=X"),
    ("KEN", "Kenya",         "MEA",   "EM", "KES=X"),
    ("POL", "Poland",        "EME",   "EM", "PLN=X"),
    ("HUN", "Hungary",       "EME",   "EM", "HUF=X"),
    ("CZE", "Czechia",       "EME",   "EM", "CZK=X"),
    ("ROU", "Romania",       "EME",   "EM", "RON=X"),
    ("TUR", "Turkey",        "EME",   "EM", "TRY=X"),
    ("USA", "United States", "G10",   "DM", ""),
    ("EMU", "Eurozone",      "G10",   "DM", "EUR=X"),
    ("JPN", "Japan",         "G10",   "DM", "JPY=X"),
    ("GBR", "United Kingdom","G10",   "DM", "GBP=X"),
    ("CAN", "Canada",        "G10",   "DM", "CAD=X"),
    ("AUS", "Australia",     "G10",   "DM", "AUD=X"),
    ("NZL", "New Zealand",   "G10",   "DM", "NZD=X"),
    ("CHE", "Switzerland",   "G10",   "DM", "CHF=X"),
    ("NOR", "Norway",        "G10",   "DM", "NOK=X"),
    ("SWE", "Sweden",        "G10",   "DM", "SEK=X"),
]

# Full names (values) shown in the desk dropdown; keys are the 3-5 letter codes.
DESK_LABELS = {
    "SEA":   "Southeast Asia",
    "EAS":   "East Asia",
    "CSA":   "Central & South Asia",
    "LATAM": "Latin America",
    "MEA":   "Middle East & Africa",
    "EME":   "Emerging Europe",
    "G10":   "Developed Markets (G10)",
}

# -------------------------------------------------------------------
# TAGS  ::  (iso3, tag)
#   A lightweight labelling layer that groups countries by CHARACTERISTIC rather
#   than geography (e.g. every oil exporter, every USD peg). A country can carry
#   several tags. Stored in the DB (country_tags); hook for future cross-cutting
#   views like "all oil_exporter FX when Brent spikes". Not yet used in the UI.
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
#   DBnomics is an AGGREGATOR: it re-hosts IMF, OECD, ECB, Eurostat, BIS, World
#   Bank, national stats offices and more. We currently only query IMF/IFS from
#   it (see DBN_SERIES) -- lots more macro is available by adding series codes.
# -------------------------------------------------------------------
SOURCES = [
    ("worldbank",   "World Bank",                     "macro",     "A", "annual"),
    ("dbnomics",    "DBnomics (IMF/OECD/ECB/... agg.)","macro",    "A", "monthly"),
    ("yahoo_fx",    "Yahoo Finance (FX)",             "market",    "A", "daily"),
    ("yahoo_cmdty", "Yahoo Finance (Commodities)",    "commodity", "A", "daily"),
    ("gdelt",       "GDELT",                          "news",      "A", "15min"),
    ("polymarket",  "Polymarket",                     "alt",       "C", "hourly"),
    ("kalshi",      "Kalshi",                         "alt",       "C", "hourly"),
    ("gtrends",     "Google Trends",                  "alt",       "C", "daily"),
    ("seed",        "Seed (Bloomberg exports)",       "market",    "A", "static"),
]

# -------------------------------------------------------------------
# WORLD BANK INDICATORS  ::  friendly name -> World Bank API code.
#   ingest.py loops these codes against the World Bank REST API and stores each
#   under your friendly name in macro_data. To add one: find its code on
#   data.worldbank.org, add a line, re-run  python ingest.py.
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
    # ---- expansion candidates (uncomment + re-run ingest.py) ----
    # "GDP_PC_USD":   "NY.GDP.PCAP.CD",        # GDP per capita, USD
    # "IMPORTS_GDP":  "NE.IMP.GNFS.ZS",        # imports % of GDP
    # "GROSS_SAVINGS":"NY.GNS.ICTR.ZS",        # gross savings % of GDP
    # "BROAD_MONEY":  "FM.LBL.BMNY.GD.ZS",     # broad money % of GDP
    # "LENDING_RATE": "FR.INR.LEND",           # lending interest rate %
}

# DBnomics series  ::  friendly name -> (provider, dataset, series-mask)
#   IMF IFS masks below are verified. Expansion codes are COMMENTED because each
#   should be confirmed on db.nomics.world before trusting (a wrong code just
#   404s -- harmless but noisy). Uncomment the ones you want + re-run ingest.py.
DBN_SERIES = {
    "POLICY_RATE":  ("IMF", "IFS", "M..FPOLM_PA"),
    "CPI_INDEX_M":  ("IMF", "IFS", "M..PCPI_IX"),
    # ---- expansion candidates (VERIFY codes on db.nomics.world first) ----
    # "FX_RATE_M":    ("IMF", "IFS", "M..ENDA_XDC_USD_RATE"),  # period-end FX
    # "RESERVES_M":   ("IMF", "IFS", "M..RAFA_USD"),           # reserves, USD
    # "EXPORTS_M":    ("IMF", "IFS", "M..TXG_FOB_USD"),        # exports, USD
    # "IMPORTS_M":    ("IMF", "IFS", "M..TMG_CIF_USD"),        # imports, USD
    # "M2_M":         ("IMF", "IFS", "M..FMB_XDC"),            # broad money
    # "IP_INDEX_M":   ("OECD","MEI", "..PRMNTO01.IXOBSA.M"),   # industrial prod.
}

# -------------------------------------------------------------------
# COMMODITIES / GLOBAL MARKET  ::  friendly name -> Yahoo Finance ticker.
#   COMMODITIES  -> stored in commodity_data (futures prices, daily).
#   MARKET_TICKERS -> stored in global_market (risk gauges, daily).
#   See what's actually stored:  python status.py
# -------------------------------------------------------------------
COMMODITIES = {
    "BRENT": "BZ=F", "WTI": "CL=F", "NATGAS": "NG=F", "COAL": "MTF=F",
    "IRON": "TIO=F", "COPPER": "HG=F", "ALUMIN": "ALI=F", "GOLD": "GC=F",
    "SILVER": "SI=F", "WHEAT": "ZW=F", "CORN": "ZC=F", "SOYBEAN": "ZS=F",
    # ---- expansion (DISABLED: uncomment the ones you want, then ingest.py) ----
    # "PLATINUM":  "PL=F",
    # "PALLADIUM": "PA=F",
    # "GASOLINE":  "RB=F",
    # "HEATOIL":   "HO=F",
    # "SUGAR":     "SB=F",
    # "COFFEE":    "KC=F",
    # "COCOA":     "CC=F",
    # "COTTON":    "CT=F",
    # "LUMBER":    "LBR=F",
    # "CATTLE":    "LE=F",
    # "LEANHOGS":  "HE=F",
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
#   Feeds you SUBSCRIBE to; you set each feed's tier once. Validate liveness with
#   python status.py --feeds  (also suggests extra candidate feeds to add).
# -------------------------------------------------------------------
RSS_FEEDS = [
    # ---- Tier A ----
    ("fed",       "US Federal Reserve (press)",   "A", "https://www.federalreserve.gov/feeds/press_all.xml"),
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
    ("cfr",       "Council on Foreign Relations", "B", "https://www.cfr.org/rss.xml"),
    ("guardian",  "The Guardian (business)",      "B", "https://www.theguardian.com/business/rss"),
    # ---- Tier C ----
    # Substacks: append '/feed' to the base URL.
    # ("noahpinion", "Noahpinion (Substack)",     "C", "https://www.noahpinion.blog/feed"),
]

# -------------------------------------------------------------------
# DOMAIN_TIER  ::  domain -> tier.  Promotes GDELT firehose articles by
# PUBLISHER quality (GDELT tags everything C; a Reuters story deserves A).
# Applied at DISPLAY time in app.py -> fixes existing rows with no re-pull.
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
#   A central-bank headline often never names its country ("Outlook for Prices").
#   This tags anything from that feed to its home country by default.
# -------------------------------------------------------------------
FEED_ORIGIN_ISO = {
    "fed": "USA", "ecb": "EMU", "boe": "GBR", "boj": "JPN", "boc": "CAN",
}

# -------------------------------------------------------------------
# GDELT  ::  we CALL GDELT's search API (not an RSS): "articles mentioning
# [country] in the last TIMESPAN". It returns a fixed set of columns
# (title/url/date/domain/lang/country) -- no sentiment field to configure.
# GDELT_SLEEP_SEC spaces out requests so GDELT doesn't rate-limit us (429).
# -------------------------------------------------------------------
GDELT_ENABLED     = FEATURE_FLAGS["ingest_gdelt"]   # single source of truth now
GDELT_TIER        = "C"
GDELT_TIMESPAN    = "3d"
GDELT_MAXRECORDS  = 60
GDELT_LANG        = "english"
GDELT_EM_ONLY     = False    # <- now includes Developed Markets too
GDELT_SLEEP_SEC   = 2.0

# -------------------------------------------------------------------
# NEWS_COUNTRY_ALIASES  ::  keyword -> iso3.
#   Lets headlines that never name the country still get tagged. Organised
#   country-by-country for readability: leaders, institutions, capital,
#   currency all sit together. Extend freely.
# -------------------------------------------------------------------
NEWS_COUNTRY_ALIASES = {
    # --- United States ---
    "fed": "USA", "federal reserve": "USA", "fomc": "USA", "treasury": "USA",
    "white house": "USA", "congress": "USA", "wall street": "USA",
    "trump": "USA", "biden": "USA", "powell": "USA", "yellen": "USA",
    "washington": "USA",
    # --- Eurozone ---
    "ecb": "EMU", "euro area": "EMU", "eurozone": "EMU", "brussels": "EMU",
    "lagarde": "EMU",
    # --- China ---
    "pboc": "CHN", "beijing": "CHN", "xi jinping": "CHN", "li qiang": "CHN",
    "yuan": "CHN", "renminbi": "CHN",
    # --- Japan ---
    "boj": "JPN", "tokyo": "JPN", "kishida": "JPN", "ishiba": "JPN", "yen": "JPN",
    # --- United Kingdom ---
    "boe": "GBR", "sunak": "GBR", "starmer": "GBR", "sterling": "GBR",
    # --- India ---
    "rbi": "IND", "modi": "IND", "new delhi": "IND", "rupee": "IND",
    # --- Indonesia ---
    "bank indonesia": "IDN", "jakarta": "IDN", "prabowo": "IDN", "rupiah": "IDN",
    # --- Philippines ---
    "bsp": "PHL", "marcos": "PHL",
    # --- Singapore ---
    "mas": "SGP",
    # --- Malaysia / Thailand / Vietnam ---
    "ringgit": "MYS", "baht": "THA", "dong": "VNM",
    # --- South Korea ---
    "seoul": "KOR", "won": "KOR",
    # --- Brazil ---
    "lula": "BRA", "brasilia": "BRA", "real": "BRA",
    # --- Mexico ---
    "amlo": "MEX", "sheinbaum": "MEX",
    # --- Argentina ---
    "milei": "ARG", "buenos aires": "ARG",
    # --- Turkey ---
    "erdogan": "TUR", "ankara": "TUR", "lira": "TUR",
    # --- South Africa ---
    "ramaphosa": "ZAF", "pretoria": "ZAF", "rand": "ZAF",
    # --- CEE currencies ---
    "zloty": "POL", "forint": "HUN", "koruna": "CZE", "tenge": "KAZ",
    # --- Nigeria ---
    "naira": "NGA",
    # (removed dangling "putin"/"moscow" -> RUS: Russia is not in COUNTRIES.
    #  add ("RUS", "Russia", "EME", "EM", "RUB=X") above first if you want it.)
}

# -------------------------------------------------------------------
# NEWS_TOPICS  ::  topic key -> keyword list.  A headline can match MULTIPLE
# topics (news_ingest.topics_of returns all matches; overlap is intended, e.g.
# a CPI print tags both econ_data and central_bank). Add a bucket = add a key.
# -------------------------------------------------------------------
NEWS_TOPICS = {
    "central_bank":  ["rate", "rates", "central bank", "policy rate", "hike",
                      "rate cut", "hawkish", "dovish", "monetary", "tightening",
                      "easing", "fomc", "boj", "ecb", "pboc", "rate decision",
                      "interest rate"],
    "econ_data":     ["gdp", "cpi", "ppi", "inflation", "pmi", "payroll",
                      "payrolls", "unemployment", "jobs", "retail sales",
                      "industrial production", "trade balance", "data print",
                      "forecast", "revised"],
    "trade":         ["trade", "tariff", "export", "import", "customs",
                      "supply chain", "wto"],
    "rates_credit":  ["bond", "yield", "debt", "default", "credit", "spread",
                      "downgrade", "rating", "sovereign", "restructuring",
                      "treasury", "curve", "duration", "imf loan", "bailout"],
    "fx":            ["currency", "fx", "exchange rate", "devaluation", "peg",
                      "reserves", "capital flows", "depreciat", "appreciat"],
    "commodities":   ["oil", "brent", "crude", "opec", "gas", "lng", "copper",
                      "gold", "iron ore", "wheat", "soybean", "commodity",
                      "commodities", "metals"],
    "equities":      ["stocks", "equity", "equities", "shares", "ipo", "index",
                      "market rally", "selloff"],
    "energy":        ["energy", "power", "electricity", "renewable", "nuclear",
                      "coal", "pipeline"],
    "technology":    ["chip", "semiconductor", "ai ", "tech", "data center",
                      "technology", "startup", "artificial intelligence"],
    "geopolitics":   ["election", "government", "president", "coup", "protest",
                      "war", "conflict", "minister", "parliament", "coalition",
                      "referendum", "sanctions", "military", "geopolitic"],
    "china":         ["china", "beijing", "yuan", "pboc", "xi jinping",
                      "property", "evergrande"],
}

# -------------------------------------------------------------------
# LOOK & FEEL  ::  SMU Emerging Markets palette + Segoe UI.
#   Charts (drawn in Python by app.py) read PALETTE/FONTS from here; the
#   HTML/layout reads the mirrored values in assets/emdash.css. Edit a colour in
#   BOTH places to keep charts and page in sync.
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
    "ui": "'Segoe UI', 'Segoe UI Web', system-ui, sans-serif",
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def iso3_to_iso2(iso3: str) -> str:
    """3-letter -> 2-letter ISO country code (e.g. 'IDN' -> 'ID'). Some APIs /
    flag utilities want the short code. Utility kept ready for future use."""
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
