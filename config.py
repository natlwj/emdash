"""
EMDASH :: config.py   (v2)

THE CONTROL PANEL. This is the only file you edit to change WHAT EMDASH covers
or how it looks. No logic lives here -- pure settings.

Edit here to:
  - add / remove a country            -> COUNTRIES
  - regroup desks or tags             -> COUNTRIES / TAGS
  - add / change a data source        -> SOURCES + INDICATOR maps
  - add / change a macro indicator    -> WB_INDICATORS / DBN_SERIES
  - add / change a market series      -> FX per-country; MARKET_TICKERS
  - add / change a commodity          -> COMMODITIES
  - add / change a credit spread      -> FRED_SERIES
  - add / change a NEWS feed          -> RSS_FEEDS / GDELT_* / NEWS_*
  - promote a news domain's tier      -> DOMAIN_TIER
  - add / change news topics          -> NEWS_TOPICS
  - tag people/places to a country    -> NEWS_COUNTRY_ALIASES
  - change colours / fonts            -> PALETTE / FONTS
  - tune the regime classifier        -> MRC_*
  - turn a whole module on/off        -> FEATURE_FLAGS

Everything downstream (core, ingest, news_ingest, signals, mrc, app) reads
from here.

DESK CODES: SEA . EAS . CSA . LATAM . MEA . EME . G10

------------------------------------------------------------------------------
WHAT CHANGED IN v2
------------------------------------------------------------------------------
1. FEATURE_FLAGS split into INGEST flags and MODULE flags, and the module
   flags are now meant to be READ BY app.py to show/hide tabs.  In v1 the
   flags existed but app.py never looked at them -- `module_regime_mrc` was
   False while the MRC tab rendered perfectly happily.  Dead config is worse
   than no config, so these are now wired.
2. NEW MRC BLOCK -- every regime-classifier knob in one place, including
   MRC_MIN_DAYS (the anti-flicker hysteresis you asked to be settable).
3. NEW FRED_SERIES BLOCK -- credit spreads (BBB / IG / HY OAS) as a live,
   uncommented dict.  ** Needs a FRED collector in ingest.py ** -- see the
   note in that block.  Nothing here fabricates data.
4. BTC added to MARKET_TICKERS (CIO asked for it as a risk-appetite gauge).
5. NEWS DISPLAY BLOCK -- timezone and favicon settings.  Feed timestamps are
   stored in UTC; NEWS_TZ_OFFSET_HOURS converts them for display.
6. Data-gap candidates documented inline (see DATA GAPS at the bottom).
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
#
# ingest_*  -> read by ingest.py / news_ingest.py: should this collector run?
# module_*  -> read by app.py: should this TAB be built at all?
#
# NOTE (v2): the module_* flags are only meaningful once app.py actually
# consults them.  If your app.py still ignores them, flipping one will have
# no effect -- that was the v1 bug.
# -------------------------------------------------------------------
FEATURE_FLAGS = {
    # ---- collectors ----
    "ingest_worldbank":   True,
    "ingest_dbnomics":    True,
    "ingest_yahoo_fx":    True,
    "ingest_commodities": True,
    "ingest_globals":     True,     # NEW: DXY/VIX/MOVE/... + BTC (MARKET_TICKERS)
    "ingest_fred":        False,    # NEW: credit spreads. Flip ON once the
                                    #      FRED collector exists in ingest.py.
    "ingest_gdelt":       True,
    "ingest_rss":         True,
    "ingest_predmarkets": False,
    "ingest_trends":      False,
    # ---- dashboard tabs ----
    "module_news":        True,
    "module_country":     True,
    "module_event_study": True,
    "module_regime_mrc":  True,     # was False in v1 while the tab still ran
}

# -------------------------------------------------------------------
# COUNTRIES  ::  (iso3, name, desk, dm_em, fx_ticker)
# fx_ticker = Yahoo Finance symbol for that currency vs USD ("IDR=X" =
# rupiah/USD). Empty "" means no FX to pull (USA: the dollar IS the base;
# app.py substitutes DXY so the USA row behaves like every other country).
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
    # ---- expansion candidates (uncomment + re-run ingest.py) ----
    # ("RUS", "Russia",      "EME",   "EM", "RUB=X"),   # then re-add putin/moscow aliases
    # ("ISR", "Israel",      "MEA",   "DM", "ILS=X"),
    # ("QAT", "Qatar",       "MEA",   "EM", "QAR=X"),
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
# A lightweight labelling layer that groups countries by CHARACTERISTIC rather
# than geography (e.g. every oil exporter, every USD peg). A country can carry
# several tags. Stored in the DB (country_tags); hook for future cross-cutting
# views like "all oil_exporter FX when Brent spikes". Not yet used in the UI.
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
# DBnomics is an AGGREGATOR: it re-hosts IMF, OECD, ECB, Eurostat, BIS, World
# Bank, national stats offices and more. We currently only query IMF/IFS from
# it (see DBN_SERIES) -- lots more macro is available by adding series codes.
# -------------------------------------------------------------------
SOURCES = [
    ("worldbank",   "World Bank",                      "macro",     "A", "annual"),
    ("dbnomics",    "DBnomics (IMF/OECD/ECB/... agg.)", "macro",    "A", "monthly"),
    ("yahoo_fx",    "Yahoo Finance (FX)",              "market",    "A", "daily"),
    ("yahoo_cmdty", "Yahoo Finance (Commodities)",     "commodity", "A", "daily"),
    ("yahoo_glob",  "Yahoo Finance (Global markets)",  "market",    "A", "daily"),
    ("fred",        "FRED / ICE BofA (credit spreads)", "market",   "A", "daily"),
    ("gdelt",       "GDELT",                           "news",      "A", "15min"),
    ("polymarket",  "Polymarket",                      "alt",       "C", "hourly"),
    ("kalshi",      "Kalshi",                          "alt",       "C", "hourly"),
    ("gtrends",     "Google Trends",                   "alt",       "C", "daily"),
    ("seed",        "Seed (Bloomberg exports)",        "market",    "A", "static"),
]

# -------------------------------------------------------------------
# WORLD BANK INDICATORS  ::  friendly name -> World Bank API code.
# ingest.py loops these codes against the World Bank REST API and stores each
# under your friendly name in macro_data. To add one: find its code on
# data.worldbank.org, add a line, re-run  python ingest.py.
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
# IMF IFS masks below are verified. Expansion codes are COMMENTED because each
# should be confirmed on db.nomics.world before trusting (a wrong code just
# 404s -- harmless but noisy). Uncomment the ones you want + re-run ingest.py.
DBN_SERIES = {
    "POLICY_RATE":  ("IMF", "IFS", "M.{iso2}.FPOLM_PA"),
    "CPI_INDEX_M":  ("IMF", "IFS", "M.{iso2}.PCPI_IX"),
    # ---- expansion candidates (VERIFY codes on db.nomics.world first) ----
    # "FX_RATE_M":    ("IMF", "IFS", "M.{iso2}.ENDA_XDC_USD_RATE"),  # period-end FX
    # "RESERVES_M":   ("IMF", "IFS", "M.{iso2}.RAFA_USD"),           # reserves, USD
    # "EXPORTS_M":    ("IMF", "IFS", "M.{iso2}.TXG_FOB_USD"),        # exports, USD
    # "IMPORTS_M":    ("IMF", "IFS", "M.{iso2}.TMG_CIF_USD"),        # imports, USD
    # "M2_M":         ("IMF", "IFS", "M.{iso2}.FMB_XDC"),            # broad money
    # "IP_INDEX_M":   ("OECD","MEI", "{iso2}.PRMNTO01.IXOBSA.M"),    # industrial prod.
}

# -------------------------------------------------------------------
# COMMODITIES / GLOBAL MARKET  ::  friendly name -> Yahoo Finance ticker.
#   COMMODITIES    -> stored in commodity_data (futures prices, daily).
#   MARKET_TICKERS -> stored in global_market  (risk gauges, daily).
# See what's actually stored:  python status.py
# -------------------------------------------------------------------
COMMODITIES = {
    "BRENT": "BZ=F", "WTI": "CL=F", "NATGAS": "NG=F", "COAL": "MTF=F",
    "IRON": "TIO=F", "COPPER": "HG=F", "ALUMIN": "ALI=F", "GOLD": "GC=F",
    "SILVER": "SI=F", "WHEAT": "ZW=F", "CORN": "ZC=F", "SOYBEAN": "ZS=F",
    # NOTE on COAL ("MTF=F"): status.py reports it stale since 2025-12-26.
    # That is NOT proof the ticker died -- ingest.py's skip_existing defaults
    # to True, so COAL is skipped on every normal run once it has ANY rows.
    # Settle it with:   python ingest.py --only commodities --refresh
    # If it stays empty after that, THEN the symbol needs replacing.
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
    # ---- v2 additions ----
    "BTC": "BTC-USD",          # CIO: risk-appetite / liquidity proxy for the MRC
    # ---- expansion candidates ----
    # "US2Y":     "^IRX",      # 13-week bill (proxy; ^UST2Y is not on Yahoo)
    # "VVIX":     "^VVIX",     # vol of vol
    # "HYG":      "HYG",       # US HY ETF (price proxy for HY risk)
    # "LQD":      "LQD",       # US IG ETF
    # "EEM":      "EEM",       # EM equity
    # "FXI":      "FXI",       # China equity
}

HISTORY = {"macro_years": 25, "market_years": 15}

# -------------------------------------------------------------------
# CREDIT SPREADS  ::  friendly name -> FRED series id.        [v2: NEW BLOCK]
#
# You already carry the EMB / EMHY *ETFs* (price proxies) in MARKET_TICKERS.
# The actual OPTION-ADJUSTED SPREADS -- the credit read a PM actually wants --
# are published FREE by the St. Louis Fed (FRED, ICE BofA indices), daily, in %.
#
# WHY THESE MATTER FOR THE MRC (CIO, 30 Jul 2026):
#   VIX  (equity vol) reads across to INVESTMENT GRADE spreads
#   MOVE (rates vol)  reads across to HIGH YIELD spreads
# so carrying the spreads themselves lets the regime classifier see credit
# stress directly instead of inferring it from vol.
#
# ** NOT WIRED YET -- HONEST NOTE **
# ingest.py currently pulls World Bank / DBnomics / Yahoo only. It has NO FRED
# collector, so filling this dict alone does nothing. Two ways to turn it on:
#   (A) tiny FRED CSV collector -- no API key needed:
#         https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>
#       parse date,value ; write into global_market like any other global series
#   (B) route via DBnomics provider "FRED" (the aggregator you already use)
#       -- VERIFY each code on db.nomics.world/FRED before trusting it.
# Then set FEATURE_FLAGS["ingest_fred"] = True.
#
# The IDs below are the standard ICE BofA OAS series (stable, widely cited).
# -------------------------------------------------------------------
FRED_SERIES = {
    "IG_OAS":      "BAMLC0A0CM",            # ICE BofA US Corporate (IG) OAS
    "BBB_OAS":     "BAMLC0A4CBBB",          # ICE BofA US Corporate BBB OAS
    "HY_OAS":      "BAMLH0A0HYM2",          # ICE BofA US High Yield OAS
    "EM_CORP_OAS": "BAMLEMCBPIOAS",         # ICE BofA EM Corporate OAS
    "EM_HY_OAS":   "BAMLEMHBHYCRPIOAS",     # ICE BofA EM High Yield OAS
    "EM_SOV_OAS":  "BAMLEMPBPUBSICRPIOAS",  # ICE BofA EM Public Sovereign OAS
    # ---- context series (optional) ----
    # "US_HY_YIELD": "BAMLH0A0HYM2EY",      # US HY effective yield
    # "TED_SPREAD":  "TEDRATE",             # discontinued 2022 -- kept as a note
}

# USD SWAP SPREADS -- KIV, deliberately NOT here.
# The CIO asked for USD swap spreads in the MRC. There is no clean FREE daily
# source: FRED's swap series (DSWP2/DSWP10) were DISCONTINUED in 2016, and
# constructing the spread (swap rate - Treasury yield) needs a swap curve that
# is not freely published daily. Plan: pull from Bloomberg (xbbg/pdblp -> BDH)
# on the terminal machine into global_market as "SWAP_SPREAD_10Y".
# ** LICENSING: Bloomberg data generally may not leave the terminal. Check with
#    Johnson / compliance BEFORE it lands in a shared SQLite. **
# mrc.py already knows the key "SWAP_SPREAD_10Y" and will start using it
# automatically the moment rows appear -- no code change needed.

# ===================================================================
# MACRO REGIME CLASSIFIER (MRC)                          [v2: NEW BLOCK]
# Read by mrc.py. Every knob the classifier uses lives here.
# ===================================================================

# Rolling window for gauge z-scores (~1 trading year).
MRC_Z_WINDOW = 252

# How strong a z-score must be to "count".
MRC_HI = 0.75          # above this = high / stressed / strong
MRC_LO = -0.75         # below this = low / calm / weak
MRC_STABLE = 0.5       # |z| below this = "stable / quiet" (Goldilocks test)
MRC_MIN_SCORE = 2.0    # a bucket must reach this many votes or the day is Neutral

# ANTI-FLICKER (hysteresis). A new regime must hold for this many consecutive
# days before it is confirmed; until then the previous regime is carried
# forward. v1 had no smoothing at all, which is why the ribbon changed colour
# almost daily. Set to 1 to disable smoothing entirely.
#   5  = responsive, still much cleaner than raw
#   10 = medium
#   20 = only shows big regime shifts
MRC_MIN_DAYS = 5

# ===================================================================
# NEWS LAYER
# ===================================================================

# -------------------------------------------------------------------
# NEWS DISPLAY  ::  timezone + publisher icons.            [v2: NEW BLOCK]
#
# TIMEZONE -- IMPORTANT AND EASY TO GET WRONG.
# Feed timestamps are stored in the DB as UTC: news_ingest._parse_entry_time
# uses feedparser's published_parsed (normalised to UTC), and GDELT's seendate
# ends in "Z" (also UTC). So a card showing "07:29" is 15:29 in Singapore.
# Set the offset for display and app.py will convert + label it.
#   Singapore / SGT = UTC+8
# -------------------------------------------------------------------
NEWS_TZ_OFFSET_HOURS = 8
NEWS_TZ_LABEL = "SGT"
NEWS_SHOW_TZ_BADGE = True      # show the little "SGT" chip next to each time

# Publisher favicons next to the source name in each news card.
# Served by DuckDuckGo's icon proxy, browser-cached, ~30 unique domains, and
# costs ZERO Python time. But it IS an external request from your network --
# if the office blocks it you'll get broken images, so this is a one-line
# off switch.
SHOW_FAVICONS = True
FAVICON_URL = "https://icons.duckduckgo.com/ip3/{domain}.ico"

# -------------------------------------------------------------------
# RSS_FEEDS  ::  (source_id, name, tier, url)
# Feeds you SUBSCRIBE to; you set each feed's tier once. Validate liveness with
#   python status.py --feeds     (also suggests extra candidate feeds to add).
# CURATED 2026-07-29 from a --feeds pass (results in comments).
# Legend: OK = live & recent; DEAD = HTTP fail; EMPTY = 0 entries.
# Re-run --feeds periodically; feeds rot.
# -------------------------------------------------------------------
RSS_FEEDS = [
    # ---- Tier A ----
    ("fed",        "US Federal Reserve (press)",   "A", "https://www.federalreserve.gov/feeds/press_all.xml"),   # OK
    # ecb: old ".../rss/press.html" was an HTML PAGE, not a feed -> always DEAD.
    # ECB still publishes RSS but the current press-feed URL must be grabbed from
    # https://www.ecb.europa.eu/home/html/rss.en.html and re-tested with --feeds.
    # Left commented rather than ship a guessed URL. (Eurozone still covered via FT/GDELT.)
    # ("ecb",      "European Central Bank (press)","A", "PASTE_CURRENT_ECB_PRESS_RSS_HERE"),
    ("boe",        "Bank of England (news)",       "A", "https://www.bankofengland.co.uk/rss/news"),             # OK
    ("boj",        "Bank of Japan (what's new)",   "A", "https://www.boj.or.jp/en/rss/whatsnew.xml"),            # OK
    ("boc",        "Bank of Canada",               "A", "https://www.bankofcanada.ca/feed/"),                    # OK
    ("imf",        "IMF (news)",                   "A", "https://www.imf.org/en/news/rss"),                      # FIXED
    # bis_*: DEAD on the 2026-07-29 check, BUT these URLs are confirmed-correct on
    # bis.org/rss/index.htm -> almost certainly an office-network / user-agent block,
    # not a bad URL. Kept ACTIVE; re-test off-network. Drop only if still dead there.
    ("bis_press",  "BIS (press releases)",         "A", "https://www.bis.org/doclist/all_pressrels.rss"),        # DEAD@office?
    ("bis_speech", "BIS (central banker speeches)","A", "https://www.bis.org/doclist/cbspeeches.rss"),           # DEAD@office?
    ("ft_em",      "FT Emerging Markets",          "A", "https://www.ft.com/emerging-markets?format=rss"),       # OK
    ("ft_econ",    "FT Global Economy",            "A", "https://www.ft.com/global-economy?format=rss"),         # OK
    ("ft_mkts",    "FT Markets",                   "A", "https://www.ft.com/markets?format=rss"),                # OK
    ("bok",        "Bank of Korea (news)",         "A", "https://www.bok.or.kr/eng/bbs/E0000634/news.rss"),      # OK
    # ---- Tier B ----
    ("bruegel",    "Bruegel (think tank)",         "B", "https://www.bruegel.org/rss.xml"),                      # OK
    # cfr: rss.xml gone (DEAD, no clean replacement) -> DROPPED.
    ("guardian",   "The Guardian (business)",      "B", "https://www.theguardian.com/business/rss"),             # OK
    ("nikkei_asia","Nikkei Asia",                  "B", "https://asia.nikkei.com/rss/feed/nar"),                 # OK
    ("diplomat",   "The Diplomat (Asia)",          "B", "https://thediplomat.com/feed/"),                        # OK
    ("aljazeera",  "Al Jazeera",                   "B", "https://www.aljazeera.com/xml/rss/all.xml"),            # OK
    ("scmp_econ",  "SCMP Economy",                 "B", "https://www.scmp.com/rss/318198/feed"),                 # OK
    # ---- candidates confirmed OK by status.py --feeds but not yet enabled ----
    # Uncomment any of these to widen EM coverage (they were in status.CANDIDATES):
    # ("rbi",      "Reserve Bank of India",        "A", "https://www.rbi.org.in/Scripts/Rss.aspx"),
    # ("bcb",      "Banco Central do Brasil",      "A", "https://www.bcb.gov.br/api/feed/sitebcb/pt-br/ultimas"),
    # ("banxico",  "Banco de Mexico",              "A", "https://www.banxico.org.mx/rss/rss.xml"),
    # ("sarb",     "South African Reserve Bank",   "A", "https://www.resbank.co.za/en/home/publications/RssFeed"),
    # ("cbrt",     "Central Bank of Turkey",       "A", "https://www.tcmb.gov.tr/rss/announcements_eng.xml"),
    # ("rba",      "Reserve Bank of Australia",    "A", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"),
    # ("piie",     "PIIE",                         "B", "https://www.piie.com/rss.xml"),
    # ("imf_blog", "IMF Blog",                     "B", "https://www.imf.org/en/Blogs/rss"),
    # ---- Tier C ----
    # cepr_vox: "OK" on check but newest item was 2024-04-18 (dormant) -> left out.
    # ("cepr_vox", "VoxEU / CEPR",                 "B", "https://cepr.org/rss.xml"),
    # Substacks: append '/feed' to the base URL.
    # ("noahpinion", "Noahpinion (Substack)",      "C", "https://www.noahpinion.blog/feed"),
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
    "bankofcanada.ca": "A", "boj.or.jp": "A", "bok.or.kr": "A",
    # Tier B: solid outlets / research
    "theguardian.com": "B", "bbc.com": "B", "bbc.co.uk": "B",
    "aljazeera.com": "B", "scmp.com": "B", "nikkei.com": "B",
    "asia.nikkei.com": "B", "thediplomat.com": "B",
    "cfr.org": "B", "bruegel.org": "B", "project-syndicate.org": "B",
    "foreignpolicy.com": "B", "politico.com": "B", "cnn.com": "B",
}

# -------------------------------------------------------------------
# FEED_ORIGIN_ISO  ::  source_id -> iso3 fallback (central-bank feeds).
# A central-bank headline often never names its country ("Outlook for Prices").
# This tags anything from that feed to its home country by default.
# -------------------------------------------------------------------
FEED_ORIGIN_ISO = {
    "fed": "USA", "ecb": "EMU", "boe": "GBR", "boj": "JPN", "boc": "CAN",
    "bok": "KOR",
    # add alongside any central-bank feed you enable above:
    # "rbi": "IND", "bcb": "BRA", "banxico": "MEX", "sarb": "ZAF",
    # "cbrt": "TUR", "rba": "AUS",
}

# -------------------------------------------------------------------
# GDELT  ::  we CALL GDELT's search API (not an RSS): "articles mentioning
# [country] in the last TIMESPAN". It returns a fixed set of columns
# (title/url/date/domain/lang/country) -- no sentiment field to configure.
# GDELT_SLEEP_SEC spaces out requests so GDELT doesn't rate-limit us (429).
# -------------------------------------------------------------------
GDELT_ENABLED     = FEATURE_FLAGS["ingest_gdelt"]   # single source of truth
GDELT_TIER        = "C"
GDELT_TIMESPAN    = "3d"
GDELT_MAXRECORDS  = 60
GDELT_LANG        = "english"
GDELT_EM_ONLY     = False    # includes Developed Markets too
GDELT_SLEEP_SEC   = 2.0

# -------------------------------------------------------------------
# NEWS_COUNTRY_ALIASES  ::  keyword -> iso3.
# Lets headlines that never name the country still get tagged.
#
# ** HOW THESE ARE USED (changed in app.py v4) **
# app.py no longer does plain substring matching. It merges this table into its
# own long-form alias table and matches on WORD BOUNDARIES. Two consequences:
#   1. Entries SHORTER THAN 4 CHARACTERS ARE IGNORED here (they fire on noise).
#   2. Entries on app.ALIAS_BLOCKLIST are ignored even if listed here, because
#      they are ordinary English words that caused the original mis-tagging:
#         "mas"  -> matched inside "Christ-MAS-Day"  -> Singapore
#         "rand" -> matched inside "b-RAND"          -> South Africa
#         "real" / "won" / "dong" / "fed" -- same class of problem
#      Use the QUALIFIED form instead: "brazilian real", "korean won",
#      "south african rand", "the fed".
# The entries below are kept as-is for backward compatibility; the blocked ones
# are marked so you know they are inert.
# -------------------------------------------------------------------
NEWS_COUNTRY_ALIASES = {
    # --- United States ---
    "fed": "USA",                 # BLOCKED (use "the fed" / "federal reserve")
    "federal reserve": "USA", "fomc": "USA", "treasury": "USA",
    "white house": "USA", "congress": "USA", "wall street": "USA",
    "trump": "USA", "biden": "USA", "powell": "USA", "yellen": "USA",
    "washington": "USA",
    # --- Eurozone ---
    "ecb": "EMU",                 # BLOCKED here, but app.py adds it safely
    "euro area": "EMU", "eurozone": "EMU", "brussels": "EMU",
    "lagarde": "EMU",
    # --- China ---
    "pboc": "CHN", "beijing": "CHN", "xi jinping": "CHN", "li qiang": "CHN",
    "yuan": "CHN",                # BLOCKED (use "chinese yuan")
    "renminbi": "CHN",
    # --- Japan ---
    "boj": "JPN",                 # BLOCKED here; app.py adds it safely
    "tokyo": "JPN", "kishida": "JPN", "ishiba": "JPN",
    "yen": "JPN",                 # BLOCKED (use "japanese yen")
    # --- United Kingdom ---
    "boe": "GBR",                 # BLOCKED here; app.py adds it safely
    "sunak": "GBR", "starmer": "GBR", "sterling": "GBR",
    # --- India ---
    "rbi": "IND",                 # BLOCKED here; app.py adds it safely
    "modi": "IND",                # BLOCKED (fires inside "modify")
    "new delhi": "IND", "rupee": "IND",
    # --- Indonesia ---
    "bank indonesia": "IDN", "jakarta": "IDN", "prabowo": "IDN", "rupiah": "IDN",
    # --- Philippines ---
    "bsp": "PHL",                 # BLOCKED here; app.py adds it safely
    "marcos": "PHL",
    # --- Singapore ---
    "mas": "SGP",                 # BLOCKED (the Christmas bug). Use the long form.
    "monetary authority of singapore": "SGP",
    # --- Malaysia / Thailand / Vietnam ---
    "ringgit": "MYS",
    "baht": "THA",                # BLOCKED (use "thai baht")
    "dong": "VNM",                # BLOCKED (use "vietnamese dong")
    # --- South Korea ---
    "seoul": "KOR",
    "won": "KOR",                 # BLOCKED (use "korean won")
    # --- Brazil ---
    "lula": "BRA",                # BLOCKED (fires inside "Lulu", "Zulu")
    "brasilia": "BRA",
    "real": "BRA",                # BLOCKED (use "brazilian real")
    # --- Mexico ---
    "amlo": "MEX",                # BLOCKED
    "sheinbaum": "MEX",
    # --- Argentina ---
    "milei": "ARG", "buenos aires": "ARG",
    # --- Turkey ---
    "erdogan": "TUR", "ankara": "TUR",
    "lira": "TUR",                # BLOCKED (use "turkish lira")
    # --- South Africa ---
    "ramaphosa": "ZAF", "pretoria": "ZAF",
    "rand": "ZAF",                # BLOCKED (use "south african rand")
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
#
# ** KNOWN ISSUE -- KIV, you said you'd tune these later **
# news_ingest.topics_of still does PLAIN SUBSTRING matching, so short keywords
# fire inside longer words. Confirmed false positives from your live data:
#     "gold"  inside "Goldman"     -> commodities
#     "coal"  inside "coalition"   -> energy
#     "oil"   inside "turmoil"     -> commodities
#     "war"   inside "warning"     -> geopolitics
#     "rate"  inside "corporate"   -> central_bank
# The fix is word-boundary matching in news_ingest.topics_of (same fix already
# applied to country tags in app.py v4). The keyword lists below are fine as
# data -- it is the MATCHER that needs changing, not these words.
# Keywords marked [SHORT] are the ones that misfire under substring matching.
# -------------------------------------------------------------------
NEWS_TOPICS = {
    "central_bank":  ["rate", "rates", "central bank", "policy rate", "hike",      # [SHORT] rate
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
    "commodities":   ["oil", "brent", "crude", "opec", "gas", "lng", "copper",   # [SHORT] oil, gas
                      "gold", "iron ore", "wheat", "soybean", "commodity",       # [SHORT] gold
                      "commodities", "metals"],
    "equities":      ["stocks", "equity", "equities", "shares", "ipo", "index",
                      "market rally", "selloff"],
    "energy":        ["energy", "power", "electricity", "renewable", "nuclear",
                      "coal", "pipeline"],                                        # [SHORT] coal
    "technology":    ["chip", "semiconductor", "ai ", "tech", "data center",     # [SHORT] chip, ai, tech
                      "technology", "startup", "artificial intelligence"],
    "geopolitics":   ["election", "government", "president", "coup", "protest",  # [SHORT] war, coup
                      "war", "conflict", "minister", "parliament", "coalition",
                      "referendum", "sanctions", "military", "geopolitic"],
    "china":         ["china", "beijing", "yuan", "pboc", "xi jinping",
                      "property", "evergrande"],
}

# -------------------------------------------------------------------
# LOOK & FEEL  ::  SMU Emerging Markets palette + Segoe UI.
# Charts (drawn in Python by app.py) read PALETTE/FONTS from here; the
# HTML/layout reads the mirrored values in assets/emdash.css. Edit a colour in
# BOTH places to keep charts and page in sync.
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

# Regime colours (mirrored in emdash.css for the ribbon legend).
REGIME_COLORS = {
    "Risk-Off":   PALETTE["bad"],
    "Risk-On":    PALETTE["good"],
    "Goldilocks": PALETTE["gold"],
    "Neutral":    PALETTE["grey"],
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def iso3_to_iso2(iso3: str) -> str:
    """3-letter -> 2-letter ISO country code (e.g. 'IDN' -> 'ID').

    Used by ingest.py to build DBnomics/IMF series masks. All 42 countries in
    COUNTRIES are mapped, so a missing POLICY_RATE is NOT caused by a gap here
    -- it means IMF IFS returned nothing for that mask.
    """
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


# ===================================================================
# DATA GAPS  ::  what is missing and what to do about it   [v2: NEW]
# From your own `python status.py` run (29 Jul 2026). This is documentation,
# not code -- it stops you chasing series that genuinely do not exist.
# ===================================================================
#
# CONFIRMED SOURCE GAP (do not chase):
#   TWN (Taiwan), everything    Taiwan is not a World Bank / IMF reporting
#                               member. No WDI, no IFS. Needs a different
#                               provider (Taiwan DGBAS / CBC, or commercial).
#
# BY DESIGN (not a bug):
#   USA FX                      FX is quoted LCY-per-USD, so the dollar has no
#                               rate against itself. app.py substitutes DXY.
#                               ** If USA FX still shows empty somewhere, the
#                                  place to check is app.FX_ISOS, which filters
#                                  on `if fx` and therefore drops USA from the
#                                  Event Study cross-section. **
#
# NEEDS INVESTIGATION (a wrong mask, not a missing country):
#   POLICY_RATE missing for     TWN PAK LKA ARE HUN CZE SWE
#   CPI_INDEX_M missing for     TWN ARG EMU AUS NZL
#   iso3_to_iso2 maps ALL of these, so ingest is asking correctly and DBnomics
#   is returning an empty docs list. Test one by hand in a browser:
#     https://api.db.nomics.world/v22/series/IMF/IFS/M.SE.FPOLM_PA?observations=1
#   If that 404s or returns no docs, the MASK is wrong for that country (some
#   countries publish under a different IFS concept code), not your code.
#
#   GOV_DEBT_GDP missing for 17 countries -- this one IS expected: the World
#   Bank reports general-government debt for only a subset of countries/years.
#   For full coverage switch to IMF WEO / GFS (both available on DBnomics).
#
# FRESHNESS:
#   COAL stale since 2025-12-26 -- see the note in COMMODITIES above. Almost
#   certainly skip_existing, not a dead ticker. Prove it with --refresh.
#
# RECOMMENDED NEXT PULLS (in priority order):
#   1. FRED credit spreads (FRED_SERIES above)  -- biggest analytical gain;
#      gives the MRC a direct credit read instead of inferring from vol.
#   2. BTC (already added to MARKET_TICKERS)    -- one line, CIO asked for it.
#   3. The 6 central-bank RSS feeds commented out above -- news coverage is
#      your real data gap (665 rows), not macro.
#   4. IMF WEO GOV_DEBT_GDP via DBnomics        -- fixes 17 missing cells.
