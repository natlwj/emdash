"""
EMDASH :: config.py   (v3)

THE CONTROL PANEL. This is the only file you edit to change WHAT EMDASH covers
or how it looks. No logic lives here -- pure settings.

Edit here to:
  - add / remove a country            -> COUNTRIES
  - regroup desks or tags             -> COUNTRIES / TAGS / CLASSIFICATION
  - add / change a data source        -> SOURCES + INDICATOR maps
  - add / change a macro indicator    -> WB_INDICATORS / DBN_SERIES
  - add / change a market series      -> FX per-country; MARKET_TICKERS
  - add / change an equity index      -> EQUITY_INDICES
  - add / change a sovereign yield    -> SOVEREIGN_YIELDS
  - add / change a commodity          -> COMMODITIES
  - add / change a credit spread      -> FRED_SERIES
  - deepen FX history (pre-Yahoo)     -> FX_FRED
  - change the pull window            -> MARKET_START / MACRO_START_YEAR
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

==============================================================================
WHAT CHANGED IN v3   (the "big data" pass -- meant to last a long time)
==============================================================================
1. COUNTRY UNIVERSE EXPANDED to the full free-data set (~90). Every country
   from the SMU EM desk map is here. The tuple SHAPE is UNCHANGED (5 fields),
   so nothing in app.py breaks -- new per-country data lives in PARALLEL dicts
   keyed by iso3 (EQUITY_INDICES / SOVEREIGN_YIELDS / CLASSIFICATION), the same
   pattern WB_INDICATORS already uses. Countries with no tradeable FX/market
   carry fx_ticker="" and are WATCH tier: World Bank annual + news tagging
   only, so they enrich coverage without inventing daily data.

2. TIME WINDOW IS NOW A DATE, NOT A COUNT.
   MARKET_START = "1950-01-01", MACRO_START_YEAR = 1950. "Pull as far back as
   the source allows, but no earlier than this." The SOURCE is still the real
   ceiling (Yahoo EM FX ~2003, US equities 1927, WB ~1960, IMF ~1950s) -- the
   Data Availability tab shows where each series actually begins. HISTORY is
   kept as a fallback for any collector still using a year-count.

3. NEW PARALLEL COUNTRY DATA (each needs its collector in ingest.py v3):
     EQUITY_INDICES    iso3 -> Yahoo index ticker      (^GSPC, ^STI, ...)
     SOVEREIGN_YIELDS  iso3 -> {tenor: ticker/FRED id} (2Y/5Y/10Y/30Y)
   Sparse by nature: free daily yields exist for ~20 countries, indices ~40.
   Missing == blank == shown honestly in the availability tab, never faked.

4. CLASSIFICATION -- who calls this country what.
   iso3 -> {msci, ftse, sp, imf, tier}. The agencies DISAGREE (Korea EM on
   MSCI, DM on FTSE; Greece EM->DM under FTSE 2026) and that disagreement is
   itself signal. Replaces the single dm_em flag as the source of truth; the
   tuple keeps a coarse dm_em for back-compat.

5. FX_FRED -- deeper FX history than Yahoo.
   Yahoo EM FX often starts ~2003. FRED's DEX* series reach the 1970s-90s for
   the majors, free. iso3 -> FRED id; ingest uses it to backfill before Yahoo.

6. MORE MONTHLY MACRO. New DBN_SERIES (industrial production, M2, trade) so the
   warehouse is not annual-heavy. You asked to update monthly -- these are the
   series that actually move monthly.

7. MORE COMMODITIES + GLOBALS uncommented (metals/softs/livestock; US 2/5/30y,
   VVIX, EEM, FXI).

8. BLOOMBERG-READY. Nothing here assumes Bloomberg, but every collector in
   ingest v3 writes via the same core.write_rows path, so a future
   source_id="bloomberg" collector drops in with zero schema change. Build free
   now, slot Bloomberg in later.

** HALLUCINATION GUARD ** Every ticker / mask / classification added in v3 is
tagged  # VERIFY  where not battle-tested. Confirm a batch with:
    python ingest.py --list
    python ingest.py --only globals   (etc.)  then  python status.py
Anything that pulls 0 rows is a bad symbol, not missing data -- fix the symbol.
"""
from pathlib import Path

# -------------------------------------------------------------------
# PATHS
# -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "emdash.sqlite"
SEED_DIR = ROOT / "seed"

# -------------------------------------------------------------------
# TIME WINDOW  ::  how far back to pull.                     [v3: NEW]
# A DATE, not a count, so "pull everything since 1950" is one edit and never
# needs revisiting. The SOURCE caps the real earliest date; this is only the
# floor we ask for. ingest.py passes MARKET_START as yfinance start=... and
# MACRO_START_YEAR as the World Bank ?date= lower bound.
#
# NOTE on re-pulling deeper history later: a normal run SKIPS series that
# already have rows (skip_existing), so simply lowering MARKET_START will NOT
# extend existing series on its own -- run `python ingest.py --refresh` (or the
# targeted --only ... --refresh) to overwrite with the longer history. A smart
# "extend-backward only" check is planned for the core.py phase.
# -------------------------------------------------------------------
MARKET_START = "1950-01-01"     # FX / equities / yields / commodities / globals
MACRO_START_YEAR = 1950         # World Bank annual lower bound

# Legacy fallback (year counts) -- still read by any path that hasn't moved to
# the date window. Kept large so nothing silently truncates.
HISTORY = {"macro_years": 75, "market_years": 75}

# -------------------------------------------------------------------
# FEATURE FLAGS  ::  the single master on/off switches.
#
# ingest_*  -> read by ingest.py / news_ingest.py: should this collector run?
# module_*  -> read by app.py: should this TAB be built at all?
# -------------------------------------------------------------------
FEATURE_FLAGS = {
    # ---- collectors ----
    "ingest_worldbank":   True,
    "ingest_dbnomics":    True,
    "ingest_yahoo_fx":    True,
    "ingest_yahoo_eq":    True,     # v3 NEW: per-country equity indices
    "ingest_yields":      True,     # v3 NEW: sovereign bond yields
    "ingest_fred_fx":     True,     # v3 NEW: deep-history FX backfill via FRED
    "ingest_commodities": True,
    "ingest_globals":     True,     # DXY/VIX/MOVE/... + BTC (MARKET_TICKERS)
    "ingest_fred":        True,     # credit spreads (collector exists in v2)
    "ingest_gdelt":       True,
    "ingest_rss":         True,
    "ingest_predmarkets": False,
    "ingest_trends":      False,

    "ingest_stooq_eq":    True,     # v3.1: equity indices Yahoo can't reach
    "ingest_predmarkets": True,     # v3.1: Polymarket (was a stub) -> now real
    # ---- dashboard tabs ----
    "module_database":    True,     # v3 NEW: Data Availability tab (FIRST tab)
    "module_news":        True,
    "module_country":     True,
    "module_event_study": True,
    "module_regime_mrc":  True,
}

# ===================================================================
# COUNTRIES  ::  (iso3, name, desk, dm_em, fx_ticker)
# fx_ticker = Yahoo Finance symbol for that currency vs USD ("IDR=X").
#   ""  = no separate/tradeable FX to pull:
#           - USA: the dollar IS the base (app substitutes DXY)
#           - USD/EUR users (Ecuador, Panama, Greece, Baltics...): no own rate
#           - illiquid/managed currencies with no clean Yahoo series
#         WATCH-tier countries still get World Bank annual macro + news tags.
# dm_em is a COARSE label (DM/EM/FM/WATCH). The authoritative per-agency call
# lives in CLASSIFICATION below.
# DESKS: SEA | EAS | CSA | LATAM | MEA | EME | G10
#
# ** ALL v3 ADDITIONS ARE # VERIFY: currency codes follow Yahoo's rigid
#    "<ISO4217>=X" pattern (mechanically safe), but confirm Yahoo actually
#    HAS a series -- 0 rows on ingest = drop the ticker, not a data gap. **
# ===================================================================
COUNTRIES = [
    # ---------------- SEA : Southeast Asia ----------------
    ("IDN", "Indonesia",      "SEA",   "EM",    "IDR=X"),
    ("MYS", "Malaysia",       "SEA",   "EM",    "MYR=X"),
    ("THA", "Thailand",       "SEA",   "EM",    "THB=X"),
    ("PHL", "Philippines",    "SEA",   "EM",    "PHP=X"),
    ("VNM", "Vietnam",        "SEA",   "FM",    "VND=X"),
    ("SGP", "Singapore",      "SEA",   "DM",    "SGD=X"),
    ("KHM", "Cambodia",       "SEA",   "WATCH", "KHR=X"),   # VERIFY
    ("LAO", "Laos",           "SEA",   "WATCH", "LAK=X"),   # VERIFY
    ("MMR", "Myanmar",        "SEA",   "WATCH", "MMK=X"),   # VERIFY
    ("BRN", "Brunei",         "SEA",   "WATCH", "BND=X"),   # VERIFY (SGD peg)
    ("TLS", "Timor-Leste",    "SEA",   "WATCH", ""),        # uses USD
    # ---------------- EAS : East Asia ----------------
    ("CHN", "China",          "EAS",   "EM",    "CNY=X"),
    ("KOR", "South Korea",    "EAS",   "EM",    "KRW=X"),
    ("TWN", "Taiwan",         "EAS",   "EM",    "TWD=X"),
    ("JPN", "Japan",          "EAS",   "DM",    "JPY=X"),
    ("HKG", "Hong Kong",      "EAS",   "DM",    "HKD=X"),
    ("MNG", "Mongolia",       "EAS",   "WATCH", "MNT=X"),   # VERIFY
    ("PRK", "North Korea",    "EAS",   "WATCH", ""),        # no data
    # ---------------- CSA : Central & South Asia ----------------
    ("IND", "India",          "CSA",   "EM",    "INR=X"),
    ("PAK", "Pakistan",       "CSA",   "FM",    "PKR=X"),
    ("BGD", "Bangladesh",     "CSA",   "FM",    "BDT=X"),
    ("LKA", "Sri Lanka",      "CSA",   "FM",    "LKR=X"),
    ("KAZ", "Kazakhstan",     "CSA",   "FM",    "KZT=X"),
    ("AFG", "Afghanistan",    "CSA",   "WATCH", "AFN=X"),   # VERIFY
    ("NPL", "Nepal",          "CSA",   "WATCH", "NPR=X"),   # VERIFY
    ("BTN", "Bhutan",         "CSA",   "WATCH", "BTN=X"),   # VERIFY (INR peg)
    ("MDV", "Maldives",       "CSA",   "WATCH", "MVR=X"),   # VERIFY
    ("UZB", "Uzbekistan",     "CSA",   "WATCH", "UZS=X"),   # VERIFY
    ("KGZ", "Kyrgyzstan",     "CSA",   "WATCH", "KGS=X"),   # VERIFY
    ("TJK", "Tajikistan",     "CSA",   "WATCH", "TJS=X"),   # VERIFY
    # ---------------- LATAM : Latin America ----------------
    ("BRA", "Brazil",         "LATAM", "EM",    "BRL=X"),
    ("MEX", "Mexico",         "LATAM", "EM",    "MXN=X"),
    ("CHL", "Chile",          "LATAM", "EM",    "CLP=X"),
    ("COL", "Colombia",       "LATAM", "EM",    "COP=X"),
    ("PER", "Peru",           "LATAM", "EM",    "PEN=X"),
    ("ARG", "Argentina",      "LATAM", "FM",    "ARS=X"),
    ("URY", "Uruguay",        "LATAM", "FM",    "UYU=X"),   # VERIFY
    ("ECU", "Ecuador",        "LATAM", "WATCH", ""),        # uses USD
    ("BOL", "Bolivia",        "LATAM", "WATCH", "BOB=X"),   # VERIFY
    ("PRY", "Paraguay",       "LATAM", "WATCH", "PYG=X"),   # VERIFY
    ("VEN", "Venezuela",      "LATAM", "WATCH", ""),        # unusable FX
    ("PAN", "Panama",         "LATAM", "WATCH", ""),        # uses USD
    ("CRI", "Costa Rica",     "LATAM", "WATCH", "CRC=X"),   # VERIFY
    ("DOM", "Dominican Rep.", "LATAM", "WATCH", "DOP=X"),   # VERIFY
    ("JAM", "Jamaica",        "LATAM", "WATCH", "JMD=X"),   # VERIFY
    ("GTM", "Guatemala",      "LATAM", "WATCH", "GTQ=X"),   # VERIFY
    ("HND", "Honduras",       "LATAM", "WATCH", "HNL=X"),   # VERIFY
    ("SLV", "El Salvador",    "LATAM", "WATCH", ""),        # uses USD
    ("NIC", "Nicaragua",      "LATAM", "WATCH", "NIO=X"),   # VERIFY
    # ---------------- MEA : Middle East & Africa ----------------
    ("ZAF", "South Africa",   "MEA",   "EM",    "ZAR=X"),
    ("SAU", "Saudi Arabia",   "MEA",   "EM",    "SAR=X"),
    ("ARE", "UAE",            "MEA",   "EM",    "AED=X"),
    ("QAT", "Qatar",          "MEA",   "EM",    "QAR=X"),   # VERIFY
    ("KWT", "Kuwait",         "MEA",   "EM",    "KWD=X"),   # VERIFY
    ("EGY", "Egypt",          "MEA",   "FM",    "EGP=X"),
    ("ISR", "Israel",         "MEA",   "DM",    "ILS=X"),   # VERIFY
    ("BHR", "Bahrain",        "MEA",   "FM",    "BHD=X"),   # VERIFY
    ("OMN", "Oman",           "MEA",   "FM",    "OMR=X"),   # VERIFY
    ("JOR", "Jordan",         "MEA",   "FM",    "JOD=X"),   # VERIFY
    ("MAR", "Morocco",        "MEA",   "FM",    "MAD=X"),   # VERIFY
    ("TUN", "Tunisia",        "MEA",   "FM",    "TND=X"),   # VERIFY
    ("NGA", "Nigeria",        "MEA",   "FM",    "NGN=X"),
    ("KEN", "Kenya",          "MEA",   "FM",    "KES=X"),
    ("GHA", "Ghana",          "MEA",   "WATCH", "GHS=X"),   # VERIFY
    ("ETH", "Ethiopia",       "MEA",   "WATCH", "ETB=X"),   # VERIFY
    ("AGO", "Angola",         "MEA",   "WATCH", "AOA=X"),   # VERIFY
    ("TZA", "Tanzania",       "MEA",   "WATCH", "TZS=X"),   # VERIFY
    ("UGA", "Uganda",         "MEA",   "WATCH", "UGX=X"),   # VERIFY
    ("ZMB", "Zambia",         "MEA",   "WATCH", "ZMW=X"),   # VERIFY
    ("ZWE", "Zimbabwe",       "MEA",   "WATCH", ""),        # unusable FX
    ("MOZ", "Mozambique",     "MEA",   "WATCH", "MZN=X"),   # VERIFY
    ("NAM", "Namibia",        "MEA",   "WATCH", "NAD=X"),   # VERIFY (ZAR peg)
    ("RWA", "Rwanda",         "MEA",   "WATCH", "RWF=X"),   # VERIFY
    ("BWA", "Botswana",       "MEA",   "WATCH", "BWP=X"),   # VERIFY
    ("SEN", "Senegal",        "MEA",   "WATCH", ""),        # XOF (shared)
    ("CIV", "Cote d'Ivoire",  "MEA",   "WATCH", ""),        # XOF (shared)
    # ---------------- EME : Emerging Europe ----------------
    ("POL", "Poland",         "EME",   "EM",    "PLN=X"),
    ("HUN", "Hungary",        "EME",   "EM",    "HUF=X"),
    ("CZE", "Czechia",        "EME",   "EM",    "CZK=X"),
    ("TUR", "Turkey",         "EME",   "EM",    "TRY=X"),
    ("GRC", "Greece",         "EME",   "EM",    ""),        # uses EUR; EM->DM 2026
    ("ROU", "Romania",        "EME",   "FM",    "RON=X"),
    ("SRB", "Serbia",         "EME",   "FM",    "RSD=X"),   # VERIFY
    ("HRV", "Croatia",        "EME",   "FM",    ""),        # uses EUR (2023)
    ("SVN", "Slovenia",       "EME",   "DM",    ""),        # uses EUR
    ("EST", "Estonia",        "EME",   "DM",    ""),        # uses EUR
    ("LVA", "Latvia",         "EME",   "DM",    ""),        # uses EUR
    ("LTU", "Lithuania",      "EME",   "DM",    ""),        # uses EUR
    ("ISL", "Iceland",        "EME",   "FM",    "ISK=X"),   # VERIFY
    ("UKR", "Ukraine",        "EME",   "WATCH", "UAH=X"),   # VERIFY
    ("BLR", "Belarus",        "EME",   "WATCH", "BYN=X"),   # VERIFY
    ("ALB", "Albania",        "EME",   "WATCH", "ALL=X"),   # VERIFY
    ("BIH", "Bosnia & Herz.", "EME",   "WATCH", "BAM=X"),   # VERIFY
    ("MDA", "Moldova",        "EME",   "WATCH", "MDL=X"),   # VERIFY
    ("MNE", "Montenegro",     "EME",   "WATCH", ""),        # uses EUR
    ("MKD", "North Macedonia","EME",   "WATCH", "MKD=X"),   # VERIFY
    # ---------------- G10 : Developed Markets ----------------
    ("USA", "United States",  "G10",   "DM",    ""),        # DXY substitute
    ("EMU", "Eurozone",       "G10",   "DM",    "EUR=X"),
    ("GBR", "United Kingdom",  "G10",   "DM",    "GBP=X"),
    ("CAN", "Canada",         "G10",   "DM",    "CAD=X"),
    ("AUS", "Australia",      "G10",   "DM",    "AUD=X"),
    ("NZL", "New Zealand",    "G10",   "DM",    "NZD=X"),
    ("CHE", "Switzerland",    "G10",   "DM",    "CHF=X"),
    ("NOR", "Norway",         "G10",   "DM",    "NOK=X"),
    ("SWE", "Sweden",         "G10",   "DM",    "SEK=X"),
]

# Full names (values) shown in the desk dropdown; keys are the codes.
DESK_LABELS = {
    "SEA":   "Southeast Asia",
    "EAS":   "East Asia",
    "CSA":   "Central & South Asia",
    "LATAM": "Latin America",
    "MEA":   "Middle East & Africa",
    "EME":   "Emerging Europe",
    "G10":   "Developed Markets (G10)",
}

# Coarse tier labels (from the dm_em field) -> readable, for the UI.
DMEM_LABELS = {
    "DM":    "Developed",
    "EM":    "Emerging",
    "FM":    "Frontier",
    "WATCH": "Watch (macro/news only)",
}

# ===================================================================
# CLASSIFICATION  ::  iso3 -> {msci, ftse, sp, imf, tier}   [v3: NEW]
# Who calls this country what. The index providers DISAGREE and that is the
# point (Korea EM on MSCI but DM on FTSE; Greece EM->DM on FTSE from 2026).
#   msci/ftse/sp : "DM" | "EM" | "FM" | "-"   (- = not classified / standalone)
#   imf          : "advanced" | "emerging" | "developing"
#   tier         : "core" | "frontier" | "watch"  (EMDASH's own data-depth tier)
#
# ** ALL # VERIFY ** These lists are reviewed annually by each provider. Confirm
# against the current MSCI / FTSE Russell / S&P Dow Jones country classification
# PDFs before quoting. Any country missing here defaults (see classification_of)
# to its coarse dm_em label so nothing breaks.
# ===================================================================
CLASSIFICATION = {  # VERIFY every row against current provider reviews
    # ---- core EM / DM (index members with full data) ----
    "IDN": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "MYS": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "THA": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "PHL": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "VNM": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "SGP": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "CHN": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "KOR": {"msci": "EM", "ftse": "DM", "sp": "EM", "imf": "advanced", "tier": "core"},
    "TWN": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "advanced", "tier": "core"},
    "JPN": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "HKG": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "IND": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "PAK": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "BGD": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "LKA": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "KAZ": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    "BRA": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "MEX": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "CHL": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "COL": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "PER": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "ARG": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    "ZAF": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "SAU": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "ARE": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "QAT": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "KWT": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "EGY": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "developing", "tier": "frontier"},
    "ISR": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "POL": {"msci": "EM", "ftse": "DM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "HUN": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "CZE": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "advanced", "tier": "core"},
    "GRC": {"msci": "EM", "ftse": "DM", "sp": "EM", "imf": "advanced", "tier": "core"},
    "TUR": {"msci": "EM", "ftse": "EM", "sp": "EM", "imf": "emerging", "tier": "core"},
    "ROU": {"msci": "FM", "ftse": "EM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    "NGA": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "KEN": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "USA": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "EMU": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "GBR": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "CAN": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "AUS": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "NZL": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "CHE": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "NOR": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    "SWE": {"msci": "DM", "ftse": "DM", "sp": "DM", "imf": "advanced", "tier": "core"},
    # ---- frontier / watch (index-frontier or IMF-only; sparse market data) ----
    "BHR": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    "OMN": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    "JOR": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "MAR": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "TUN": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "developing", "tier": "frontier"},
    "SRB": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    "HRV": {"msci": "FM", "ftse": "FM", "sp": "FM", "imf": "advanced", "tier": "frontier"},
    "ISL": {"msci": "FM", "ftse": "DM", "sp": "-",  "imf": "advanced", "tier": "frontier"},
    "SVN": {"msci": "FM", "ftse": "DM", "sp": "-",  "imf": "advanced", "tier": "frontier"},
    "EST": {"msci": "FM", "ftse": "DM", "sp": "-",  "imf": "advanced", "tier": "frontier"},
    "LVA": {"msci": "FM", "ftse": "FM", "sp": "-",  "imf": "advanced", "tier": "frontier"},
    "LTU": {"msci": "FM", "ftse": "FM", "sp": "-",  "imf": "advanced", "tier": "frontier"},
    "URY": {"msci": "-",  "ftse": "FM", "sp": "FM", "imf": "emerging", "tier": "frontier"},
    # Everything else defaults to its coarse dm_em label + tier "watch"
    # (see classification_of). Fill rows in above as you verify them.
}

# -------------------------------------------------------------------
# TAGS  ::  (iso3, tag)  -- characteristic groupings (oil exporter, USD peg...)
# Stored in country_tags; hook for cross-cutting views. Not yet used in the UI.
# -------------------------------------------------------------------
TAGS = [
    ("SAU", "oil_exporter"), ("ARE", "oil_exporter"), ("QAT", "oil_exporter"),
    ("KWT", "oil_exporter"), ("OMN", "oil_exporter"), ("BHR", "oil_exporter"),
    ("NGA", "oil_exporter"), ("NOR", "oil_exporter"), ("COL", "oil_exporter"),
    ("KAZ", "oil_exporter"), ("AGO", "oil_exporter"), ("ECU", "oil_exporter"),
    ("CHL", "metals_exporter"), ("PER", "metals_exporter"),
    ("ZAF", "metals_exporter"), ("AUS", "metals_exporter"),
    ("BRA", "metals_exporter"), ("ZMB", "metals_exporter"),
    ("BRA", "ag_exporter"), ("ARG", "ag_exporter"), ("IDN", "ag_exporter"),
    ("MYS", "ag_exporter"), ("URY", "ag_exporter"), ("CIV", "ag_exporter"),
    ("KOR", "tech_exporter"), ("TWN", "tech_exporter"), ("SGP", "tech_exporter"),
    ("SAU", "usd_peg"), ("ARE", "usd_peg"), ("QAT", "usd_peg"),
    ("BHR", "usd_peg"), ("OMN", "usd_peg"), ("HKG", "usd_peg"),
    ("NAM", "zar_bloc"), ("BTN", "inr_bloc"),
    ("TUR", "high_yield"), ("ARG", "high_yield"), ("EGY", "high_yield"),
    ("NGA", "high_yield"), ("PAK", "high_yield"), ("GHA", "high_yield"),
    ("UKR", "high_yield"), ("ZMB", "high_yield"),
    ("ECU", "dollarised"), ("PAN", "dollarised"), ("SLV", "dollarised"),
    ("TLS", "dollarised"),
]

# -------------------------------------------------------------------
# SOURCE REGISTRY
# -------------------------------------------------------------------
SOURCES = [
    ("worldbank",   "World Bank",                       "macro",     "A", "annual"),
    ("dbnomics",    "DBnomics (IMF/OECD/ECB/... agg.)",  "macro",     "A", "monthly"),
    ("yahoo_fx",    "Yahoo Finance (FX)",               "market",    "A", "daily"),
    ("yahoo_eq",    "Yahoo Finance (Equity indices)",   "market",    "A", "daily"),
    ("yahoo_glob",  "Yahoo Finance (Global markets)",   "market",    "A", "daily"),
    ("yahoo_cmdty", "Yahoo Finance (Commodities)",      "commodity", "A", "daily"),
    ("fred",        "FRED / ICE BofA (spreads/yields)",  "market",    "A", "daily"),
    ("fred_fx",     "FRED (deep-history FX)",           "market",    "A", "daily"),
    ("gdelt",       "GDELT",                            "news",      "A", "15min"),
    ("polymarket",  "Polymarket",                       "alt",       "C", "hourly"),
    ("kalshi",      "Kalshi",                           "alt",       "C", "hourly"),
    ("gtrends",     "Google Trends",                    "alt",       "C", "daily"),
    ("bloomberg",   "Bloomberg (terminal, manual)",     "market",    "A", "manual"),
    ("seed",        "Seed (Bloomberg exports)",         "market",    "A", "static"),
]


INDICATOR_LABELS = {
    "GDP_YOY": "GDP growth (% YoY)",
    "CPI_YOY": "Inflation (CPI % YoY)",
    "CURR_ACC_GDP": "Current account (% of GDP)",
    "GOV_DEBT_GDP": "Govt debt (% of GDP)",   # yes — it's the ratio
    "UNEMPLOYMENT": "Unemployment (%)",
    "EXPORTS_GDP": "Exports (% of GDP)",
    "IMPORTS_GDP": "Imports (% of GDP)",
    "FDI_GDP": "FDI (% of GDP)",
    "RESERVES_USD": "FX reserves (USD)",
    "GDP_PC_USD": "GDP per capita (USD)",
    "GROSS_SAVINGS": "Gross savings (% of GDP)",
    "BROAD_MONEY": "Broad money / M2 (% of GDP)",
    "POP_TOTAL": "Population (total)",
    "POLICY_RATE": "Policy rate (%)",
    "CPI_INDEX_M": "CPI index (monthly)",
    "FX_RATE_M": "FX rate (monthly)",
    "RESERVES_M": "FX reserves (monthly)",
    "EXPORTS_M": "Exports (monthly, USD)",
    "IMPORTS_M": "Imports (monthly, USD)",
    "IP_INDEX_M": "Industrial production (monthly)",
    "M2_M": "Broad money M2 (monthly)",
}

# -------------------------------------------------------------------
# WORLD BANK INDICATORS  ::  friendly name -> World Bank API code.
# Annual by nature (most are computed once a year). ingest loops these.
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
    # ---- v3 additions (annual context; all standard WDI codes) ----
    "GDP_PC_USD":   "NY.GDP.PCAP.CD",        # GDP per capita, USD       # VERIFY
    "IMPORTS_GDP":  "NE.IMP.GNFS.ZS",        # imports % of GDP          # VERIFY
    "GROSS_SAVINGS":"NY.GNS.ICTR.ZS",        # gross savings % of GDP    # VERIFY
    "BROAD_MONEY":  "FM.LBL.BMNY.GD.ZS",     # broad money % of GDP      # VERIFY
    "POP_TOTAL":    "SP.POP.TOTL",           # population                # VERIFY
}

# DBnomics series  ::  friendly name -> (provider, dataset, series-mask)
# The MONTHLY macro spine. IMF IFS masks; {iso2} filled per country.
# ** Expansion masks are # VERIFY -- confirm each on db.nomics.world first;
#    a wrong mask returns "no series published" (harmless, logged, not fatal). **
# -------------------------------------------------------------------
DBN_SERIES = {
    "POLICY_RATE":  ("IMF", "IFS", "M.{iso2}.FPOLM_PA"),
    "CPI_INDEX_M":  ("IMF", "IFS", "M.{iso2}.PCPI_IX"),
    # ---- v3 additions: more MONTHLY macro (this is what "update monthly" needs)
    "FX_RATE_M":    ("IMF", "IFS", "M.{iso2}.ENDA_XDC_USD_RATE"),  # VERIFY
    "RESERVES_M":   ("IMF", "IFS", "M.{iso2}.RAFA_USD"),          # VERIFY
    "EXPORTS_M":    ("IMF", "IFS", "M.{iso2}.TXG_FOB_USD"),       # VERIFY
    "IMPORTS_M":    ("IMF", "IFS", "M.{iso2}.TMG_CIF_USD"),       # VERIFY
    "IP_INDEX_M":   ("IMF", "IFS", "M.{iso2}.AIPMA_IX"),          # VERIFY (ind. prod.)
    "M2_M":         ("IMF", "IFS", "M.{iso2}.FMB_XDC"),           # VERIFY (broad money)
}

# -------------------------------------------------------------------
# COMMODITIES  ::  friendly name -> Yahoo futures ticker -> commodity_data
# -------------------------------------------------------------------
COMMODITIES = {
    # ---- energy ----
    "BRENT": "BZ=F", "WTI": "CL=F", "NATGAS": "NG=F", "COAL": "MTF=F",
    "GASOLINE": "RB=F", "HEATOIL": "HO=F",                          # VERIFY (v3)
    # ---- metals ----
    "GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F", "ALUMIN": "ALI=F",
    "IRON": "TIO=F", "PLATINUM": "PL=F", "PALLADIUM": "PA=F",       # VERIFY (v3)
    # ---- ags / softs ----
    "WHEAT": "ZW=F", "CORN": "ZC=F", "SOYBEAN": "ZS=F",
    "SUGAR": "SB=F", "COFFEE": "KC=F", "COCOA": "CC=F", "COTTON": "CT=F",  # VERIFY (v3)
    # ---- livestock ----
    "CATTLE": "LE=F", "LEANHOGS": "HE=F",                           # VERIFY (v3)
    # NOTE on COAL ("MTF=F"): if status.py flags it stale, prove the ticker
    # rather than assume -- python ingest.py --only commodities --refresh.
}

# -------------------------------------------------------------------
# MARKET_TICKERS  ::  global risk gauges -> global_market (MRC reads these)
# -------------------------------------------------------------------
MARKET_TICKERS = {
    "DXY": "DX-Y.NYB", "VIX": "^VIX", "MOVE": "^MOVE",
    "SPX": "^GSPC", "EMB": "EMB", "EMHY": "EMHY", "GOLD_ETF": "GLD",
    "BTC": "BTC-USD",
    # ---- US Treasury curve (global rate reads; feed Event Study rate work) ----
    "US2Y":  "^IRX",   # 13-week bill proxy (^UST2Y not on Yahoo)   # VERIFY
    "US5Y":  "^FVX",   # 5-year yield                               # VERIFY
    "US10Y": "^TNX",   # 10-year yield
    "US30Y": "^TYX",   # 30-year yield                              # VERIFY
    # ---- v3 additions: extra risk/vol/EM gauges ----
    "VVIX":  "^VVIX",  # vol of vol                                 # VERIFY
    "EEM":   "EEM",    # EM equity ETF                              # VERIFY
    "FXI":   "FXI",    # China large-cap ETF                        # VERIFY
    # NOTE: HYG / LQD deliberately OMITTED. ETF PRICE moves OPPOSITE to OAS; if
    # mis-wired into the MRC's STRESS_UP it reads a crisis as calm. If ever
    # added, name them HY_ETF / IG_ETF (never *_OAS) and put in RISK_UP only.
}

# ===================================================================
# EQUITY_INDICES  ::  iso3 -> Yahoo index ticker -> market_data("EQUITY")
# Per-country stock index. Free coverage ~40 markets; the rest simply are not
# in the dict (no blank rows, shown empty in the availability tab).   [v3: NEW]
# ** ALL # VERIFY -- Yahoo index symbols are inconsistent (^ vs .SUFFIX). **
# ===================================================================
EQUITY_INDICES = {  # VERIFY every symbol with `ingest.py --only equities`
    "USA": "^GSPC",   "EMU": "^STOXX50E", "GBR": "^FTSE",  "CAN": "^GSPTSE",
    "AUS": "^AXJO",   "NZL": "^NZ50",     "CHE": "^SSMI",  "NOR": "^OSEAX",
    "SWE": "^OMX",    "JPN": "^N225",     "HKG": "^HSI",   "SGP": "^STI",
    "KOR": "^KS11",   "TWN": "^TWII",     "CHN": "000001.SS",
    "IND": "^NSEI",   "IDN": "^JKSE",     "MYS": "^KLSE",  "THA": "^SET.BK",
    "PHL": "PSEI.PS","VNM": "^VNINDEX.VN",  "PAK": "^KSE",
    "BRA": "^BVSP",   "MEX": "^MXX",      "CHL": "^IPSA",  "COL": "^COLCAP",
    "ARG": "^MERV",   "PER": "^SPBLPGPT",
    "ZAF": "^JN0U.JO","SAU": "^TASI.SR",  "ISR": "^TA125.TA",
    "EGY": "^CASE30", "QAT": "^QSI",
    "POL": "^WIG",    "HUN": "^BUX.BD",   "CZE": "^PX",    "TUR": "^XU100",
    "GRC": "^ATG",    "ROU": "^BETI",
}


# ===================================================================
# EQUITY_STOOQ  ::  iso3 -> Stooq symbol.  For indices NOT on Yahoo.   [v3.1]
# Pulled from Stooq's CSV endpoint (stooq.com/q/d/l/?s=SYM&i=d) by
# ingest.fetch_stooq_equities -> market_data, series="EQUITY", source_id="stooq".
# ** ALL # VERIFY: run `python ingest.py --only stooq_eq` and drop 0-row rows. **
# ===================================================================
EQUITY_STOOQ = {
    "POL": "^wig20", "CZE": "^px",  "HUN": "^bux",  "ROU": "^bet",
    "GRC": "^atg",   "QAT": "^qsi", "CHL": "^ipsa", "PER": "^spblg",
    "TUR": "^xu100", "COL": "^colcap", "PAK": "^kse",
}

EQUITY_STOOQ = {  # VERIFY every symbol
    "POL": "^wig20",   # Poland WIG20
    "CZE": "^px",      # Czech PX (Prague)
    "HUN": "^bux",     # Hungary BUX
    "ROU": "^bet",     # Romania BET
    "GRC": "^atg",     # Greece Athens General (ASE)
    "QAT": "^qsi",     # Qatar QE General            # VERIFY (may be absent)
    "AUT": "^atx",     # Austria ATX  (bonus -- if you add AUT later)
    "PRT": "^psi20",   # Portugal PSI-20 (bonus)
    "ESP": "^ibex",    # Spain IBEX (bonus)
    "ITA": "^ftmib",   # Italy FTSE MIB (bonus)
}


# ===================================================================
# SOVEREIGN_YIELDS  ::  iso3 -> {tenor: source_spec}             [v3: NEW]
# Government bond yields. Free DAILY yields are genuinely sparse; the US full
# curve lives in MARKET_TICKERS (global). Here we hold what free per-country
# yields exist. source_spec forms:
#     ("fred",  "<FRED_ID>")     e.g. Germany 10y  = ("fred", "IRLTLT01DEM156N")
#     ("yahoo", "<TICKER>")      where a Yahoo yield ticker exists
# tenor keys: "2Y" | "5Y" | "10Y" | "30Y". Written to market_data as
# series="Y2"/"Y5"/"Y10"/"Y30".
# ** ALL # VERIFY -- FRED IRLTLT01 monthly long-rate IDs vary by country. **
# ===================================================================
SOVEREIGN_YIELDS = {  # VERIFY every id
    # OECD monthly long-term (10y) rates via FRED "IRLTLT01<CC>M156N" pattern.
    "USA": {"2Y": ("fred", "DGS2"), "5Y": ("fred", "DGS5"),
            "10Y": ("fred", "DGS10"), "30Y": ("fred", "DGS30")},
    "GBR": {"10Y": ("fred", "IRLTLT01GBM156N")},
    "EMU": {"10Y": ("fred", "IRLTLT01EZM156N")},
    "JPN": {"10Y": ("fred", "IRLTLT01JPM156N")},
    "CAN": {"10Y": ("fred", "IRLTLT01CAM156N")},
    "AUS": {"10Y": ("fred", "IRLTLT01AUM156N")},
    "CHE": {"10Y": ("fred", "IRLTLT01CHM156N")},
    "NOR": {"10Y": ("fred", "IRLTLT01NOM156N")},
    "SWE": {"10Y": ("fred", "IRLTLT01SEM156N")},
    "KOR": {"10Y": ("fred", "IRLTLT01KRM156N")},
    "MEX": {"10Y": ("fred", "IRLTLT01MXM156N")},
    "IND": {"10Y": ("fred", "INDIRLTLT01STM")},
    "ZAF": {"10Y": ("fred", "IRLTLT01ZAM156N")},
    "BRA": {"10Y": ("fred", "IRLTLT01BRM156N")},
    "IDN": {"10Y": ("fred", "IRLTLT01IDM156N")},
    "POL": {"10Y": ("fred", "IRLTLT01PLM156N")},
    "CZE": {"10Y": ("fred", "IRLTLT01CZM156N")},
    "HUN": {"10Y": ("fred", "IRLTLT01HUM156N")},
    "TUR": {"10Y": ("fred", "IRLTLT01TRM156N")},
    "CHL": {"10Y": ("fred", "IRLTLT01CLM156N")},
}

# ===================================================================
# FX_FRED  ::  iso3 -> FRED daily FX id (deeper than Yahoo)      [v3: NEW]
# Yahoo EM FX often starts ~2003. FRED DEX* series reach the 1970s-90s for the
# majors, free and daily. ingest backfills FROM here, THEN tops up with Yahoo,
# so the joined series is as long as the source allows. All are USD-quoted;
# some are "LCY per USD", some "USD per LCY" -- ingest normalises by config.
# ** ALL # VERIFY -- and check the quote DIRECTION per series. **
# ===================================================================
FX_FRED = {  # VERIFY id + quote direction
    "JPN": "DEXJPUS",  "GBR": "DEXUSUK",  "EMU": "DEXUSEU",  "CAN": "DEXCAUS",
    "AUS": "DEXUSAL",  "CHE": "DEXSZUS",  "SWE": "DEXSDUS",  "NOR": "DEXNOUS",
    "CHN": "DEXCHUS",  "KOR": "DEXKOUS",  "IND": "DEXINUS",  "SGP": "DEXSIUS",
    "HKG": "DEXHKUS",  "TWN": "DEXTAUS",  "THA": "DEXTHUS",  "MYS": "DEXMAUS",
    "BRA": "DEXBZUS",  "MEX": "DEXMXUS",  "ZAF": "DEXSFUS",  "NZL": "DEXUSNZ",
    # direction note: DEXUSUK/DEXUSEU/DEXUSAL/DEXUSNZ are USD-per-LCY (inverted).
}

# -------------------------------------------------------------------
# CREDIT SPREADS  ::  friendly name -> FRED series id (ICE BofA OAS, daily, %).
# Collector exists (ingest.fetch_fred). Rows land in global_market so mrc.py
# uses them automatically. FIREWALL NOTE: fred.stlouisfed.org may be blocked on
# the office network -- if fetch_fred returns 0 with ConnectionReset, that is a
# firewall, not a bad config. Test api.stlouisfed.org as an alternate host.
# -------------------------------------------------------------------
FRED_SERIES = {
    "IG_OAS":      "BAMLC0A0CM",
    "BBB_OAS":     "BAMLC0A4CBBB",
    "HY_OAS":      "BAMLH0A0HYM2",
    "EM_CORP_OAS": "BAMLEMCBPIOAS",
    "EM_HY_OAS":   "BAMLEMHBHYCRPIOAS",
    "EM_SOV_OAS":  "BAMLEMPBPUBSICRPIOAS",
    # "US_HY_YIELD": "BAMLH0A0HYM2EY",   # optional context
}

# USD SWAP SPREADS -- KIV (Bloomberg-only, no clean free daily source).
# mrc.py already knows key "SWAP_SPREAD_10Y" and starts using it when rows
# appear -- a future Bloomberg collector writes it, no code change here.

# -------------------------------------------------------------------
# PREDICTION MARKETS (Polymarket)  ::  free public Gamma API.       [v3.1]
# fetch_predmarkets pulls the most active/liquid markets -> predmarket_data
# (date, market_id, question, prob, venue). Snapshot per run (today's prob),
# so running weekly builds a probability time-series you can chart later.
# -------------------------------------------------------------------
POLYMARKET_API   = "https://gamma-api.polymarket.com/markets"
PREDMARKET_LIMIT = 120      # how many active markets to snapshot per run
PREDMARKET_MIN_VOL = 10000  # skip illiquid markets below this USD volume


# ===================================================================
# MACRO REGIME CLASSIFIER (MRC)   -- read by mrc.py
# ===================================================================
MRC_Z_WINDOW = 252
MRC_HI = 0.75
MRC_LO = -0.75
MRC_STABLE = 0.5
MRC_MIN_SCORE = 2.0
MRC_MIN_DAYS = 5
# NOTE: mrc.py v3 (pending install) adds MRC_MIN_MARGIN (winner must beat
# runner-up by N votes or the day is Neutral). Uncomment when v3 is installed:
# MRC_MIN_MARGIN = 2.0

# ===================================================================
# NEWS LAYER
# ===================================================================
NEWS_TZ_OFFSET_HOURS = 8
NEWS_TZ_LABEL = "SGT"
NEWS_SHOW_TZ_BADGE = True

SHOW_FAVICONS = False
FAVICON_URL = "https://icons.duckduckgo.com/ip3/{domain}.ico"

# -------------------------------------------------------------------
# RSS_FEEDS  ::  (source_id, name, tier, url).  Validate with:
#   python status.py --feeds
# v3: ECB filled + 6 EM central banks enabled. ** RE-RUN --feeds FROM YOUR PC
# to confirm liveness before trusting -- feeds rot and the office firewall
# blocks some hosts (BIS). Keep OK, drop DEAD. **
# -------------------------------------------------------------------
RSS_FEEDS = [
    # ---- Tier A : central banks / official ----
    ("fed",        "US Federal Reserve (press)",    "A", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ecb",        "European Central Bank (press)",  "A", "https://www.ecb.europa.eu/rss/press.html"),   # VERIFY (v3)
    ("boe",        "Bank of England (news)",         "A", "https://www.bankofengland.co.uk/rss/news"),
    ("boj",        "Bank of Japan (what's new)",     "A", "https://www.boj.or.jp/en/rss/whatsnew.xml"),
    ("boc",        "Bank of Canada",                 "A", "https://www.bankofcanada.ca/feed/"),
    ("bok",        "Bank of Korea (news)",           "A", "https://www.bok.or.kr/eng/bbs/E0000634/news.rss"),
    ("rbi",        "Reserve Bank of India",          "A", "https://www.rbi.org.in/Scripts/Rss.aspx"),               # VERIFY (v3)
    ("bcb",        "Banco Central do Brasil",        "A", "https://www.bcb.gov.br/api/feed/sitebcb/pt-br/ultimas"), # VERIFY (v3)
    ("banxico",    "Banco de Mexico",                "A", "https://www.banxico.org.mx/rss/rss.xml"),                # VERIFY (v3)
    ("sarb",       "South African Reserve Bank",     "A", "https://www.resbank.co.za/en/home/publications/RssFeed"),# VERIFY (v3)
    ("cbrt",       "Central Bank of Turkey",         "A", "https://www.tcmb.gov.tr/rss/announcements_eng.xml"),     # VERIFY (v3)
    ("rba",        "Reserve Bank of Australia",      "A", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"),  # VERIFY (v3)
    ("imf",        "IMF (news)",                     "A", "https://www.imf.org/en/news/rss"),
    ("ft_em",      "FT Emerging Markets",            "A", "https://www.ft.com/emerging-markets?format=rss"),
    ("ft_econ",    "FT Global Economy",              "A", "https://www.ft.com/global-economy?format=rss"),
    ("ft_mkts",    "FT Markets",                     "A", "https://www.ft.com/markets?format=rss"),
    # bis_*: confirmed-correct URLs but DEAD on the office network (firewall/UA).
    # Kept ACTIVE; re-test off-network. Drop only if still dead there.
    ("bis_press",  "BIS (press releases)",           "A", "https://www.bis.org/doclist/all_pressrels.rss"),   # DEAD@office?
    ("bis_speech", "BIS (central banker speeches)",  "A", "https://www.bis.org/doclist/cbspeeches.rss"),      # DEAD@office?
    # ---- Tier B : research / quality press ----
    ("bruegel",    "Bruegel (think tank)",           "B", "https://www.bruegel.org/rss.xml"),
    ("guardian",   "The Guardian (business)",        "B", "https://www.theguardian.com/business/rss"),
    ("nikkei_asia","Nikkei Asia",                    "B", "https://asia.nikkei.com/rss/feed/nar"),
    ("diplomat",   "The Diplomat (Asia)",            "B", "https://thediplomat.com/feed/"),
    ("aljazeera",  "Al Jazeera",                     "B", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("scmp_econ",  "SCMP Economy",                   "B", "https://www.scmp.com/rss/318198/feed"),
    # ---- more candidates (uncomment + --feeds test) ----
    # ("piie",     "PIIE",                           "B", "https://www.piie.com/rss.xml"),
    # ("imf_blog", "IMF Blog",                       "B", "https://www.imf.org/en/Blogs/rss"),
]

# -------------------------------------------------------------------
# DOMAIN_TIER  ::  domain -> tier.  Promotes GDELT firehose by publisher.
# -------------------------------------------------------------------
DOMAIN_TIER = {
    "reuters.com": "A", "ft.com": "A", "bloomberg.com": "A",
    "wsj.com": "A", "economist.com": "A", "apnews.com": "A",
    "nytimes.com": "A", "cnbc.com": "A", "imf.org": "A",
    "worldbank.org": "A", "bis.org": "A", "ecb.europa.eu": "A",
    "federalreserve.gov": "A", "bankofengland.co.uk": "A",
    "bankofcanada.ca": "A", "boj.or.jp": "A", "bok.or.kr": "A",
    "rbi.org.in": "A", "bcb.gov.br": "A", "banxico.org.mx": "A",
    "resbank.co.za": "A", "tcmb.gov.tr": "A", "rba.gov.au": "A",
    "theguardian.com": "B", "bbc.com": "B", "bbc.co.uk": "B",
    "aljazeera.com": "B", "scmp.com": "B", "nikkei.com": "B",
    "asia.nikkei.com": "B", "thediplomat.com": "B",
    "cfr.org": "B", "bruegel.org": "B", "project-syndicate.org": "B",
    "foreignpolicy.com": "B", "politico.com": "B", "cnn.com": "B",
}

# -------------------------------------------------------------------
# FEED_ORIGIN_ISO  ::  source_id -> iso3 fallback for central-bank feeds.
# v3: 6 EM central banks added alongside the enabled feeds above.
# -------------------------------------------------------------------
FEED_ORIGIN_ISO = {
    "fed": "USA", "ecb": "EMU", "boe": "GBR", "boj": "JPN", "boc": "CAN",
    "bok": "KOR",
    "rbi": "IND", "bcb": "BRA", "banxico": "MEX", "sarb": "ZAF",
    "cbrt": "TUR", "rba": "AUS",
}

# -------------------------------------------------------------------
# GDELT  ::  search-API call (not RSS). Fixed columns, no sentiment field.
# -------------------------------------------------------------------
GDELT_ENABLED     = FEATURE_FLAGS["ingest_gdelt"]
GDELT_TIER        = "C"
GDELT_TIMESPAN    = "3d"
GDELT_MAXRECORDS  = 60
GDELT_LANG        = "english"
GDELT_EM_ONLY     = False
GDELT_SLEEP_SEC   = 2.0

# -------------------------------------------------------------------
# NEWS_COUNTRY_ALIASES  ::  keyword -> iso3 (word-boundary matched in app.py;
# entries <4 chars or on app.ALIAS_BLOCKLIST are inert -- use qualified forms).
# -------------------------------------------------------------------
NEWS_COUNTRY_ALIASES = {
    # --- United States ---
    "fed": "USA", "federal reserve": "USA", "fomc": "USA", "treasury": "USA",
    "white house": "USA", "congress": "USA", "wall street": "USA",
    "trump": "USA", "biden": "USA", "powell": "USA", "washington": "USA",
    # --- Eurozone ---
    "ecb": "EMU", "euro area": "EMU", "eurozone": "EMU", "brussels": "EMU",
    "lagarde": "EMU",
    # --- China / Japan / UK / India ---
    "pboc": "CHN", "beijing": "CHN", "xi jinping": "CHN", "renminbi": "CHN",
    "boj": "JPN", "tokyo": "JPN",
    "boe": "GBR", "starmer": "GBR", "sterling": "GBR",
    "rbi": "IND", "new delhi": "IND", "rupee": "IND",
    # --- SEA ---
    "bank indonesia": "IDN", "jakarta": "IDN", "prabowo": "IDN", "rupiah": "IDN",
    "marcos": "PHL", "monetary authority of singapore": "SGP",
    "ringgit": "MYS",
    # --- Korea / LATAM / Turkey / SA / Nigeria ---
    "seoul": "KOR",
    "lula": "BRA", "brasilia": "BRA",
    "sheinbaum": "MEX", "milei": "ARG", "buenos aires": "ARG",
    "erdogan": "TUR", "ankara": "TUR",
    "ramaphosa": "ZAF", "pretoria": "ZAF",
    "naira": "NGA",
    # --- CEE currencies ---
    "zloty": "POL", "forint": "HUN", "koruna": "CZE", "tenge": "KAZ",
    # v3: a few added for new majors (qualified forms only, >=4 chars)
    "riyadh": "SAU", "abu dhabi": "ARE", "doha": "QAT", "kuwait city": "KWT",
    "tel aviv": "ISR", "athens": "GRC", "kyiv": "UKR", "nairobi": "KEN",
    "accra": "GHA", "casablanca": "MAR",
}

# -------------------------------------------------------------------
# NEWS_TOPICS  ::  topic key -> keyword list. Matched in news_ingest.topics_of.
# ** KIV: topics_of still substring-matches, so [SHORT] keywords misfire
# ("gold" in "Goldman"). Fix = word-boundary matching in news_ingest.py. The
# DATA below is fine; the MATCHER needs changing, not these words. **
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
# LOOK & FEEL  ::  SMU Emerging Markets palette + Segoe UI. Mirror colour edits
# in assets/emdash.css (:root).
# -------------------------------------------------------------------
PALETTE = {
    "canvas": "#E9EBEF", "gold": "#948A54", "navy1": "#1F497D",
    "navy2": "#2E5C96", "navy3": "#6593C4", "brown": "#74592D",
    "grey": "#939DAA", "ink": "#1D2733", "muted": "#6B7480",
    "card": "#FFFFFF", "border": "#DFE2E8", "good": "#2E7D46", "bad": "#B4453A",
}
FONTS = {"ui": "'Segoe UI', 'Segoe UI Web', system-ui, sans-serif"}
REGIME_COLORS = {
    "Risk-Off": PALETTE["bad"], "Risk-On": PALETTE["good"],
    "Goldilocks": PALETTE["gold"], "Neutral": PALETTE["grey"],
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def iso3_to_iso2(iso3: str) -> str:
    """3-letter -> 2-letter ISO (used to build IMF/DBnomics masks). Extended in
    v3 to cover every country in COUNTRIES; a blank return means DBnomics is
    skipped for that country (logged loudly by ingest, not silent)."""
    _MAP = {
        # SEA
        "IDN": "ID", "MYS": "MY", "THA": "TH", "PHL": "PH", "VNM": "VN",
        "SGP": "SG", "KHM": "KH", "LAO": "LA", "MMR": "MM", "BRN": "BN",
        "TLS": "TL",
        # EAS
        "CHN": "CN", "KOR": "KR", "TWN": "TW", "JPN": "JP", "HKG": "HK",
        "MNG": "MN", "PRK": "KP",
        # CSA
        "IND": "IN", "PAK": "PK", "BGD": "BD", "LKA": "LK", "KAZ": "KZ",
        "AFG": "AF", "NPL": "NP", "BTN": "BT", "MDV": "MV", "UZB": "UZ",
        "KGZ": "KG", "TJK": "TJ",
        # LATAM
        "BRA": "BR", "MEX": "MX", "CHL": "CL", "COL": "CO", "PER": "PE",
        "ARG": "AR", "URY": "UY", "ECU": "EC", "BOL": "BO", "PRY": "PY",
        "VEN": "VE", "PAN": "PA", "CRI": "CR", "DOM": "DO", "JAM": "JM",
        "GTM": "GT", "HND": "HN", "SLV": "SV", "NIC": "NI",
        # MEA
        "ZAF": "ZA", "SAU": "SA", "ARE": "AE", "QAT": "QA", "KWT": "KW",
        "EGY": "EG", "ISR": "IL", "BHR": "BH", "OMN": "OM", "JOR": "JO",
        "MAR": "MA", "TUN": "TN", "NGA": "NG", "KEN": "KE", "GHA": "GH",
        "ETH": "ET", "AGO": "AO", "TZA": "TZ", "UGA": "UG", "ZMB": "ZM",
        "ZWE": "ZW", "MOZ": "MZ", "NAM": "NA", "RWA": "RW", "BWA": "BW",
        "SEN": "SN", "CIV": "CI",
        # EME
        "POL": "PL", "HUN": "HU", "CZE": "CZ", "TUR": "TR", "GRC": "GR",
        "ROU": "RO", "SRB": "RS", "HRV": "HR", "SVN": "SI", "EST": "EE",
        "LVA": "LV", "LTU": "LT", "ISL": "IS", "UKR": "UA", "BLR": "BY",
        "ALB": "AL", "BIH": "BA", "MDA": "MD", "MNE": "ME", "MKD": "MK",
        # G10
        "USA": "US", "EMU": "U2", "GBR": "GB", "CAN": "CA", "AUS": "AU",
        "NZL": "NZ", "CHE": "CH", "NOR": "NO", "SWE": "SE",
    }
    return _MAP.get(iso3, "")


def classification_of(iso3: str) -> dict:
    """Full agency classification for a country. Falls back to the coarse dm_em
    label from COUNTRIES if the country is not yet in CLASSIFICATION, so the UI
    always has something to show and nothing breaks."""
    if iso3 in CLASSIFICATION:
        return CLASSIFICATION[iso3]
    dmem = next((dm for i, n, d, dm, fx in COUNTRIES if i == iso3), "-")
    tier = "core" if dmem in ("DM", "EM") else (
        "frontier" if dmem == "FM" else "watch")
    return {"msci": dmem, "ftse": dmem, "sp": dmem, "imf": "-", "tier": tier}


def tier_of(iso3: str) -> str:
    """EMDASH data-depth tier: core | frontier | watch."""
    return classification_of(iso3).get("tier", "watch")


# ===================================================================
# DATA GAPS  ::  what is missing and what to do about it.
# The Data Availability tab (module_database) now shows this LIVE per series;
# this block is the human-readable "why", so you don't chase data that does
# not exist.
# ===================================================================
#
# STRUCTURAL (do not chase; free sources genuinely lack these):
#   TWN (Taiwan) macro          Not a WB / IMF reporting member -> no WDI/IFS.
#                               Has market data (FX, ^TWII), lacks WB macro.
#   WATCH-tier countries        Many frontier/IMF-expanded states have WB annual
#                               macro + news only: no tradeable FX, no index, no
#                               free daily yield. Expected -- shown blank in the
#                               availability tab, never faked. That is the point
#                               of adding them: news coverage + macro context.
#   Dollarised (ECU/PAN/SLV/TLS) and EUR users (GRC/Baltics/HRV/SVN/MNE)
#                               have fx_ticker="" by design -- no own currency.
#
# SPARSE-BY-NATURE (only where a free series exists):
#   EQUITY_INDICES ~40 markets  the rest have no free Yahoo index.
#   SOVEREIGN_YIELDS ~20        free daily/monthly yields are rare outside DM +
#                               big EM. US full curve is complete.
#
# FIXABLE (a wrong symbol/mask, not a missing country):
#   Any # VERIFY that pulls 0 rows -> bad ticker/mask. Fix the symbol; don't
#   assume the data is missing. Confirm with:
#       python ingest.py --only globals   (etc.)   then   python status.py
#   POLICY_RATE / CPI_INDEX_M blanks for some countries -> test one IFS mask by
#   hand: https://api.db.nomics.world/v22/series/IMF/IFS/M.TR.FPOLM_PA?observations=1
#   Empty docs = wrong concept code for that country, not your code.
#
# CREDIT SPREADS (FRED): collector exists. If fetch_fred returns 0 with a
#   ConnectionReset, that is the office firewall on fred.stlouisfed.org, not
#   config. Test the alternate host api.stlouisfed.org (needs a free key).
#
# BLOOMBERG (future, part-time): CDS, USD swap spreads, and any series the free
#   stack can't reach slot in as a source_id="bloomberg" collector writing to
#   the SAME tables. Nothing here changes when that lands. Licensing: clear with
#   Johnson/compliance before Bloomberg values sit in the shared SQLite.
