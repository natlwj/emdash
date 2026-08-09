"""
EMDASH :: config.py   (v3.3)

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
WHAT CHANGED IN v3.3   (news COVERAGE + TAGGING pass)
==============================================================================
GOAL: almost every country gets media coverage, and far fewer "(no desk)" /
"General" rows.

1. RSS_FEEDS expanded with PAN-REGIONAL wires (one feed -> a whole region):
     bne IntelliNews (100+ EM countries), allAfrica (all Africa), MercoPress
     (all LatAm), Deutsche Welle + France 24 (global, strong MENA/Africa),
     Channel NewsAsia (SE Asia), Africanews. PLUS single-country locals for
     gaps: Dawn (PAK), Daily Star (BGD), Korea Herald, Taipei Times, VnExpress
     (VNM), Bangkok Post (THA), Arab News (SAU), Gulf News (ARE), Times of
     Israel, Kyiv Independent (UKR), Premium Times (NGA), Nation (KEN), Daily
     Maverick (ZAF), Rio Times (BRA), Notes from Poland. GDELT still does the
     per-country long tail; these give real outlets on top.

2. NEWS_COUNTRY_ALIASES greatly expanded: capitals, demonyms, leaders and key
     institutions for the smaller / WATCH-tier countries that previously had
     only their bare country name. This is what shrinks "(no desk)".

3. NEWS ACRONYMS are now CASE-SENSITIVE (see news_ingest.ACRONYM_ALIASES, which
     this file feeds). "US" -> USA, "UK" -> GBR, "EU" -> EMU, "UAE" -> ARE, but
     the lowercase words "us"/"uk"/"eu" and substrings like "SUS"/"bus" do NOT
     match. This required a matcher change in news_ingest.py (v3): the lowercase
     alias table CANNOT do this, because it lowercases the headline first.

4. NEWS_TOPICS tuned + new "disaster" topic (wildfire/flood/quake/typhoon...),
     more geopolitics keywords (ceasefire/strike/troops/sanction/tariff/nuclear
     /missile/drone/coup/summit/treaty/nato...), so fewer rows fall to General.

5. TAGS expanded (more oil/metals/ag exporters, tourism, remittance economies).

** EVERY new/changed feed URL is # VERIFY **. Run FROM YOUR PC after the
news_ingest.py browser-UA patch (feedparser's default UA gets 403s from
Cloudflare-fronted sites):
    python -c "import feedparser,config; ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'; [print(f'{s:14} HTTP {getattr(feedparser.parse(u,agent=ua),chr(115)+chr(116)+chr(97)+chr(116)+chr(117)+chr(115),chr(63))!s:>4} n={len(feedparser.parse(u,agent=ua).entries):>3} {n}') for s,n,t,u in config.RSS_FEEDS]"
Keep OK (n>0), drop DEAD. Timeout/ConnectionReset = office firewall (retest
from home); HTTP 404 = wrong URL; HTTP 403 = still bot-blocked.

==============================================================================
WHAT CHANGED IN v3.2   (news-sources pass)
==============================================================================
* RSS_FEEDS grew ~24 -> ~43 (World Bank, Economist, BBC, CNBC, IMF Blog, PIIE,
  CFR, Project Syndicate, CEPR VoxEU, local EM outlets, Reddit). Dropped banxico
  (no press RSS). X/Twitter NOT added (killed public RSS in 2023).

==============================================================================
WHAT CHANGED IN v3   (the "big data" pass)
==============================================================================
1. COUNTRY UNIVERSE ~90 (full free-data set). Tuple SHAPE unchanged (5 fields);
   new per-country data in PARALLEL iso3 dicts. WATCH-tier = news + WB annual.
2. TIME WINDOW is a DATE (MARKET_START / MACRO_START_YEAR), not a count.
3. EQUITY_INDICES / SOVEREIGN_YIELDS parallel dicts (sparse, honest blanks).
4. CLASSIFICATION iso3 -> {msci,ftse,sp,imf,tier} (agencies disagree = signal).
5. FX_FRED deep-history FX. 6. More monthly DBN_SERIES. 7. More commodities /
   globals. 8. Bloomberg-ready (same core.write_rows path).

** HALLUCINATION GUARD ** Every ticker/mask added is tagged # VERIFY where not
battle-tested. Confirm with: python ingest.py --list ; --only <x> ; status.py.
0 rows = bad symbol, not missing data.
"""
from pathlib import Path

# -------------------------------------------------------------------
# PATHS
# -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "emdash.sqlite"
SEED_DIR = ROOT / "seed"

# -------------------------------------------------------------------
# TIME WINDOW  ::  how far back to pull.
# A DATE, not a count. The SOURCE caps the real earliest date; this is the floor
# we ask for. Lowering MARKET_START does NOT extend existing series unless you
# run `python ingest.py --refresh`.
# -------------------------------------------------------------------
MARKET_START = "1950-01-01"     # FX / equities / yields / commodities / globals
MACRO_START_YEAR = 1950         # World Bank annual lower bound
HISTORY = {"macro_years": 75, "market_years": 75}   # legacy year-count fallback

# -------------------------------------------------------------------
# FEATURE FLAGS  ::  master on/off switches.
# ingest_* -> read by ingest.py / news_ingest.py.  module_* -> read by app.py.
# -------------------------------------------------------------------
FEATURE_FLAGS = {
    # ---- collectors ----
    "ingest_worldbank":   True,
    "ingest_dbnomics":    True,
    "ingest_yahoo_fx":    True,
    "ingest_yahoo_eq":    True,
    "ingest_yields":      True,
    "ingest_fred_fx":     True,
    "ingest_commodities": True,
    "ingest_globals":     True,
    "ingest_fred":        True,
    "ingest_gdelt":       True,
    "ingest_rss":         True,
    "ingest_predmarkets": True,
    "ingest_trends":      False,
    "ingest_stooq_eq":    True,
    # ---- dashboard tabs ----
    "module_database":    True,
    "module_news":        True,
    "module_country":     True,
    "module_event_study": True,
    "module_regime_mrc":  True,
}

# ===================================================================
# COUNTRIES  ::  (iso3, name, desk, dm_em, fx_ticker)
# fx_ticker = Yahoo symbol vs USD ("IDR=X"); "" = no tradeable FX (USD/EUR user,
# managed, or WATCH-only). dm_em is COARSE; per-agency call in CLASSIFICATION.
# DESKS: SEA | EAS | CSA | LATAM | MEA | EME | G10
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
    ("GBR", "United Kingdom", "G10",   "DM",    "GBP=X"),
    ("CAN", "Canada",         "G10",   "DM",    "CAD=X"),
    ("AUS", "Australia",      "G10",   "DM",    "AUD=X"),
    ("NZL", "New Zealand",    "G10",   "DM",    "NZD=X"),
    ("CHE", "Switzerland",    "G10",   "DM",    "CHF=X"),
    ("NOR", "Norway",         "G10",   "DM",    "NOK=X"),
    ("SWE", "Sweden",         "G10",   "DM",    "SEK=X"),
]

DESK_LABELS = {
    "SEA":   "Southeast Asia",
    "EAS":   "East Asia",
    "CSA":   "Central & South Asia",
    "LATAM": "Latin America",
    "MEA":   "Middle East & Africa",
    "EME":   "Emerging Europe",
    "G10":   "Developed Markets (G10)",
}

DMEM_LABELS = {
    "DM":    "Developed",
    "EM":    "Emerging",
    "FM":    "Frontier",
    "WATCH": "Watch (macro/news only)",
}

# ===================================================================
# CLASSIFICATION  ::  iso3 -> {msci, ftse, sp, imf, tier}
# ** ALL # VERIFY ** against current MSCI / FTSE / S&P reviews. Missing rows fall
# back to the coarse dm_em label (see classification_of).
# ===================================================================
CLASSIFICATION = {  # VERIFY every row against current provider reviews
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
}

# -------------------------------------------------------------------
# TAGS  ::  (iso3, tag)  -- characteristic groupings. v3.3: expanded.
# -------------------------------------------------------------------
TAGS = [
    ("SAU", "oil_exporter"), ("ARE", "oil_exporter"), ("QAT", "oil_exporter"),
    ("KWT", "oil_exporter"), ("OMN", "oil_exporter"), ("BHR", "oil_exporter"),
    ("NGA", "oil_exporter"), ("NOR", "oil_exporter"), ("COL", "oil_exporter"),
    ("KAZ", "oil_exporter"), ("AGO", "oil_exporter"), ("ECU", "oil_exporter"),
    ("MEX", "oil_exporter"), ("BRN", "oil_exporter"),
    ("CHL", "metals_exporter"), ("PER", "metals_exporter"),
    ("ZAF", "metals_exporter"), ("AUS", "metals_exporter"),
    ("BRA", "metals_exporter"), ("ZMB", "metals_exporter"),
    ("MNG", "metals_exporter"), ("BWA", "metals_exporter"),
    ("BRA", "ag_exporter"), ("ARG", "ag_exporter"), ("IDN", "ag_exporter"),
    ("MYS", "ag_exporter"), ("URY", "ag_exporter"), ("CIV", "ag_exporter"),
    ("UKR", "ag_exporter"), ("VNM", "ag_exporter"), ("THA", "ag_exporter"),
    ("KOR", "tech_exporter"), ("TWN", "tech_exporter"), ("SGP", "tech_exporter"),
    ("CHN", "tech_exporter"), ("JPN", "tech_exporter"),
    ("SAU", "usd_peg"), ("ARE", "usd_peg"), ("QAT", "usd_peg"),
    ("BHR", "usd_peg"), ("OMN", "usd_peg"), ("HKG", "usd_peg"),
    ("NAM", "zar_bloc"), ("BTN", "inr_bloc"),
    ("TUR", "high_yield"), ("ARG", "high_yield"), ("EGY", "high_yield"),
    ("NGA", "high_yield"), ("PAK", "high_yield"), ("GHA", "high_yield"),
    ("UKR", "high_yield"), ("ZMB", "high_yield"), ("KEN", "high_yield"),
    ("ECU", "dollarised"), ("PAN", "dollarised"), ("SLV", "dollarised"),
    ("TLS", "dollarised"),
    ("EGY", "tourism"), ("THA", "tourism"), ("TUR", "tourism"),
    ("GRC", "tourism"), ("MAR", "tourism"), ("HRV", "tourism"),
    ("PHL", "remittances"), ("EGY", "remittances"), ("PAK", "remittances"),
    ("BGD", "remittances"), ("NPL", "remittances"), ("SLV", "remittances"),
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
    "GOV_DEBT_GDP": "Govt debt (% of GDP)",
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
    "GDP_PC_USD":   "NY.GDP.PCAP.CD",        # VERIFY
    "IMPORTS_GDP":  "NE.IMP.GNFS.ZS",        # VERIFY
    "GROSS_SAVINGS":"NY.GNS.ICTR.ZS",        # VERIFY
    "BROAD_MONEY":  "FM.LBL.BMNY.GD.ZS",     # VERIFY
    "POP_TOTAL":    "SP.POP.TOTL",           # VERIFY
}

DBN_SERIES = {
    "POLICY_RATE":  ("IMF", "IFS", "M.{iso2}.FPOLM_PA"),
    "CPI_INDEX_M":  ("IMF", "IFS", "M.{iso2}.PCPI_IX"),
    "FX_RATE_M":    ("IMF", "IFS", "M.{iso2}.ENDA_XDC_USD_RATE"),  # VERIFY
    "RESERVES_M":   ("IMF", "IFS", "M.{iso2}.RAFA_USD"),          # VERIFY
    "EXPORTS_M":    ("IMF", "IFS", "M.{iso2}.TXG_FOB_USD"),       # VERIFY
    "IMPORTS_M":    ("IMF", "IFS", "M.{iso2}.TMG_CIF_USD"),       # VERIFY
    "IP_INDEX_M":   ("IMF", "IFS", "M.{iso2}.AIPMA_IX"),          # VERIFY
    "M2_M":         ("IMF", "IFS", "M.{iso2}.FMB_XDC"),           # VERIFY
}

# -------------------------------------------------------------------
# COMMODITIES  ::  friendly name -> Yahoo futures ticker
# -------------------------------------------------------------------
COMMODITIES = {
    "BRENT": "BZ=F", "WTI": "CL=F", "NATGAS": "NG=F", "COAL": "MTF=F",
    "GASOLINE": "RB=F", "HEATOIL": "HO=F",                          # VERIFY
    "GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F", "ALUMIN": "ALI=F",
    "IRON": "TIO=F", "PLATINUM": "PL=F", "PALLADIUM": "PA=F",       # VERIFY
    "WHEAT": "ZW=F", "CORN": "ZC=F", "SOYBEAN": "ZS=F",
    "SUGAR": "SB=F", "COFFEE": "KC=F", "COCOA": "CC=F", "COTTON": "CT=F",  # VERIFY
    "CATTLE": "LE=F", "LEANHOGS": "HE=F",                           # VERIFY
}

# -------------------------------------------------------------------
# MARKET_TICKERS  ::  global risk gauges -> global_market (MRC reads these)
# -------------------------------------------------------------------
MARKET_TICKERS = {
    "DXY": "DX-Y.NYB", "VIX": "^VIX", "MOVE": "^MOVE",
    "SPX": "^GSPC", "EMB": "EMB", "EMHY": "EMHY", "GOLD_ETF": "GLD",
    "BTC": "BTC-USD",
    "US2Y":  "^IRX",   # VERIFY
    "US5Y":  "^FVX",   # VERIFY
    "US10Y": "^TNX",
    "US30Y": "^TYX",   # VERIFY
    "VVIX":  "^VVIX",  # VERIFY
    "EEM":   "EEM",    # VERIFY
    "FXI":   "FXI",    # VERIFY
    # HYG/LQD deliberately OMITTED (price moves opposite OAS).
}

# ===================================================================
# EQUITY_INDICES  ::  iso3 -> Yahoo index ticker
# ===================================================================
EQUITY_INDICES = {  # VERIFY every symbol with `ingest.py --only equities`
    "USA": "^GSPC",   "EMU": "^STOXX50E", "GBR": "^FTSE",  "CAN": "^GSPTSE",
    "AUS": "^AXJO",   "NZL": "^NZ50",     "CHE": "^SSMI",  "NOR": "^OSEAX",
    "SWE": "^OMX",    "JPN": "^N225",     "HKG": "^HSI",   "SGP": "^STI",
    "KOR": "^KS11",   "TWN": "^TWII",     "CHN": "000001.SS",
    "IND": "^NSEI",   "IDN": "^JKSE",     "MYS": "^KLSE",  "THA": "^SET.BK",
    "PHL": "PSEI.PS", "VNM": "^VNINDEX.VN", "PAK": "^KSE",
    "BRA": "^BVSP",   "MEX": "^MXX",      "CHL": "^IPSA",  "COL": "^COLCAP",
    "ARG": "^MERV",   "PER": "^SPBLPGPT",
    "ZAF": "^JN0U.JO","SAU": "^TASI.SR",  "ISR": "^TA125.TA",
    "EGY": "^CASE30", "QAT": "^QSI",
    "POL": "^WIG",    "HUN": "^BUX.BD",   "CZE": "^PX",    "TUR": "^XU100",
    "GRC": "^ATG",    "ROU": "^BETI",
}

# ===================================================================
# EQUITY_STOOQ  ::  iso3 -> Stooq symbol (indices NOT on Yahoo)
# Consolidated to ONE dict (was defined twice in v3.1).
# ===================================================================
EQUITY_STOOQ = {  # VERIFY every symbol
    "POL": "^wig20", "CZE": "^px",  "HUN": "^bux",  "ROU": "^bet",
    "GRC": "^atg",   "QAT": "^qsi", "CHL": "^ipsa", "PER": "^spblg",
    "TUR": "^xu100", "COL": "^colcap", "PAK": "^kse",
    "AUT": "^atx",   "PRT": "^psi20", "ESP": "^ibex", "ITA": "^ftmib",
}

# ===================================================================
# SOVEREIGN_YIELDS  ::  iso3 -> {tenor: (src, id)}
# ===================================================================
SOVEREIGN_YIELDS = {  # VERIFY every id
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
# FX_FRED  ::  iso3 -> FRED daily FX id (deeper than Yahoo)
# ===================================================================
FX_FRED = {  # VERIFY id + quote direction
    "JPN": "DEXJPUS",  "GBR": "DEXUSUK",  "EMU": "DEXUSEU",  "CAN": "DEXCAUS",
    "AUS": "DEXUSAL",  "CHE": "DEXSZUS",  "SWE": "DEXSDUS",  "NOR": "DEXNOUS",
    "CHN": "DEXCHUS",  "KOR": "DEXKOUS",  "IND": "DEXINUS",  "SGP": "DEXSIUS",
    "HKG": "DEXHKUS",  "TWN": "DEXTAUS",  "THA": "DEXTHUS",  "MYS": "DEXMAUS",
    "BRA": "DEXBZUS",  "MEX": "DEXMXUS",  "ZAF": "DEXSFUS",  "NZL": "DEXUSNZ",
}

# -------------------------------------------------------------------
# CREDIT SPREADS  ::  friendly name -> FRED series id (ICE BofA OAS)
# -------------------------------------------------------------------
FRED_SERIES = {
    "IG_OAS":      "BAMLC0A0CM",
    "BBB_OAS":     "BAMLC0A4CBBB",
    "HY_OAS":      "BAMLH0A0HYM2",
    "EM_CORP_OAS": "BAMLEMCBPIOAS",
    "EM_HY_OAS":   "BAMLEMHBHYCRPIOAS",
    "EM_SOV_OAS":  "BAMLEMPBPUBSICRPIOAS",
}

# -------------------------------------------------------------------
# PREDICTION MARKETS (Polymarket)
# -------------------------------------------------------------------
POLYMARKET_API   = "https://gamma-api.polymarket.com/markets"
PREDMARKET_LIMIT = 120
PREDMARKET_MIN_VOL = 10000

# ===================================================================
# MACRO REGIME CLASSIFIER (MRC)
# ===================================================================
MRC_Z_WINDOW = 252
MRC_HI = 0.75
MRC_LO = -0.75
MRC_STABLE = 0.5
MRC_MIN_SCORE = 2.0
MRC_MIN_DAYS = 5
# MRC_MIN_MARGIN = 2.0   # uncomment when mrc.py v3 installed

# ===================================================================
# NEWS LAYER
# ===================================================================
NEWS_TZ_OFFSET_HOURS = 8
NEWS_TZ_LABEL = "SGT"
NEWS_SHOW_TZ_BADGE = True

SHOW_FAVICONS = True
FAVICON_URL = "https://icons.duckduckgo.com/ip3/{domain}.ico"

NEWS_PRUNE_DAYS = 90

# -------------------------------------------------------------------
# RSS_FEEDS  ::  (source_id, name, tier, url).  Validate with the header
# one-liner. v3.3 adds pan-regional wires + single-country locals for coverage.
# ** EVERY # VERIFY url MUST be tested FROM YOUR PC with the browser-UA patch. **
# -------------------------------------------------------------------
RSS_FEEDS = [
    # ==== Tier A : central banks / official ====
    ("fed",        "US Federal Reserve (press)",   "A", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ecb",        "European Central Bank (press)", "A", "https://www.ecb.europa.eu/rss/press.html"),             # VERIFY
    ("boe",        "Bank of England (news)",        "A", "https://www.bankofengland.co.uk/rss/news"),
    ("boj",        "Bank of Japan (what's new)",    "A", "https://www.boj.or.jp/en/rss/whatsnew.xml"),
    ("boc",        "Bank of Canada",                "A", "https://www.bankofcanada.ca/feed/"),
    ("bok",        "Bank of Korea (news)",          "A", "https://www.bok.or.kr/eng/bbs/E0000634/news.rss"),      # VERIFY
    ("rba",        "Reserve Bank of Australia",     "A", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"), # VERIFY
    ("rbi",        "Reserve Bank of India",         "A", "https://www.rbi.org.in/Scripts/Rss.aspx"),              # VERIFY
    ("bcb",        "Banco Central do Brasil",       "A", "https://www.bcb.gov.br/api/feed/sitebcb/en-us/lastnews"),# VERIFY
    ("bis_press",  "BIS (press releases)",          "A", "https://www.bis.org/doclist/all_pressrels.rss"),       # firewall@office
    ("bis_speech", "BIS (central banker speeches)", "A", "https://www.bis.org/doclist/cbspeeches.rss"),          # firewall@office
    # NOTE dropped (dead @office 2026-08-09, no fix): banxico(no RSS), cbrt(404),
    # sarb(404 gated), imf(403), worldbank(200/0). Those come via GDELT + locals.

    # ==== Tier A/B : global press ====
    ("ft_em",      "FT Emerging Markets",           "A", "https://www.ft.com/emerging-markets?format=rss"),
    ("ft_econ",    "FT Global Economy",             "A", "https://www.ft.com/global-economy?format=rss"),
    ("ft_mkts",    "FT Markets",                    "A", "https://www.ft.com/markets?format=rss"),
    ("economist",  "The Economist (Fin & Econ)",    "A", "https://www.economist.com/finance-and-economics/rss.xml"), # VERIFY
    ("bbc_biz",    "BBC Business",                  "B", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("cnbc_econ",  "CNBC Economy",                  "B", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("cnbc_world", "CNBC World",                    "B", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("guardian",   "The Guardian (business)",       "B", "https://www.theguardian.com/business/rss"),
    ("aljazeera",  "Al Jazeera",                    "B", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("dw",         "Deutsche Welle (world)",        "B", "https://rss.dw.com/rdf/rss-en-all"),                    # VERIFY
    ("france24",   "France 24 (world)",             "B", "https://www.france24.com/en/rss"),                     # VERIFY

    # ==== Tier B : PAN-REGIONAL wires (one feed -> a whole region) ====
    ("bne",        "bne IntelliNews (EM wire)",     "B", "https://www.intellinews.com/feed"),                    # VERIFY (100+ EM countries)
    ("allafrica",  "allAfrica (pan-Africa)",        "B", "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf"), # VERIFY
    ("mercopress", "MercoPress (LatAm/Mercosur)",   "B", "https://en.mercopress.com/rss"),                       # VERIFY
    ("africanews", "Africanews",                    "B", "https://www.africanews.com/feed/rss"),                 # VERIFY
    ("cna",        "Channel NewsAsia",              "B", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml"), # VERIFY

    # ==== Tier B : Asia locals ====
    ("nikkei_asia","Nikkei Asia",                   "B", "https://asia.nikkei.com/rss/feed/nar"),
    ("diplomat",   "The Diplomat (Asia)",           "B", "https://thediplomat.com/feed/"),
    ("scmp_econ",  "SCMP Economy",                  "B", "https://www.scmp.com/rss/318198/feed"),
    ("et_markets", "Economic Times Markets (IND)",  "B", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"), # VERIFY
    ("livemint",   "LiveMint Markets (IND)",        "B", "https://www.livemint.com/rss/markets"),                # VERIFY
    ("dawn",       "Dawn (Pakistan)",               "B", "https://www.dawn.com/feeds/home"),                     # VERIFY
    ("bdstar",     "The Daily Star (Bangladesh)",   "B", "https://www.thedailystar.net/rss.xml"),                # VERIFY
    ("koreaherald","Korea Herald",                  "B", "http://www.koreaherald.com/rss/020000000000.xml"),     # VERIFY
    ("taipeitimes","Taipei Times (Taiwan)",         "B", "https://www.taipeitimes.com/xml/index.rss"),           # VERIFY
    ("vnexpress",  "VnExpress International (VNM)",  "B", "https://e.vnexpress.net/rss/news.rss"),                # VERIFY
    ("bangkokpost","Bangkok Post (Thailand)",       "B", "https://www.bangkokpost.com/rss/data/topstories.xml"), # VERIFY
    ("jakartapost","Jakarta Post (IDN)",            "B", "https://rss.thejakartapost.com/home"),                 # VERIFY

    # ==== Tier B : MENA locals ====
    ("arabnews",   "Arab News (Saudi/Gulf)",        "B", "https://www.arabnews.com/rss.xml"),                    # VERIFY
    ("gulfnews",   "Gulf News (UAE)",               "B", "https://gulfnews.com/rss?generatorType=news"),         # VERIFY
    ("timesofisrael","Times of Israel",             "B", "https://www.timesofisrael.com/feed/"),                 # VERIFY
    ("hurriyet",   "Hurriyet Daily News (TUR)",     "B", "https://www.hurriyetdailynews.com/rss"),               # VERIFY

    # ==== Tier B : Africa locals ====
    ("moneyweb",   "Moneyweb (ZAF)",                "B", "https://www.moneyweb.co.za/feed/"),                    # VERIFY
    ("dailymaverick","Daily Maverick (ZAF)",        "B", "https://www.dailymaverick.co.za/rss/"),                # VERIFY
    ("premiumtimes","Premium Times (Nigeria)",      "B", "https://www.premiumtimesng.com/feed"),                 # VERIFY
    ("nationkenya","Nation (Kenya)",                "B", "https://nation.africa/kenya/rss"),                     # VERIFY

    # ==== Tier B : LatAm + EM Europe locals ====
    ("ba_times",   "Buenos Aires Times (ARG)",      "B", "https://www.batimes.com.ar/feed"),                     # VERIFY
    ("riotimes",   "Rio Times (Brazil)",            "B", "https://www.riotimesonline.com/feed/"),                # VERIFY
    ("notesfrompoland","Notes from Poland",         "B", "https://notesfrompoland.com/feed/"),                   # VERIFY
    ("kyivindependent","Kyiv Independent (UKR)",    "B", "https://kyivindependent.com/feed/"),                   # VERIFY

    # ==== Tier B : research / think tanks ====
    ("bruegel",    "Bruegel (think tank)",          "B", "https://www.bruegel.org/rss.xml"),                     # UA patch fixes 403
    ("imf_blog",   "IMF Blog",                      "B", "https://www.imf.org/en/Blogs/rss"),                    # VERIFY
    ("piie",       "PIIE",                          "B", "https://www.piie.com/rss/all"),                        # VERIFY
    ("cfr",        "Council on Foreign Relations",  "B", "https://www.cfr.org/feed"),                            # VERIFY
    ("proj_synd",  "Project Syndicate (economics)", "B", "https://www.project-syndicate.org/rss"),               # VERIFY
    ("voxeu",      "CEPR VoxEU",                    "B", "https://cepr.org/rss/vox-content"),                    # VERIFY

    # ==== Tier C : "social" (Reddit has RSS; needs UA patch + rate-limit) ====
    ("r_economics","Reddit r/economics",            "C", "https://www.reddit.com/r/economics/.rss"),             # VERIFY (UA-gated)
    ("r_em",       "Reddit r/emergingmarkets",      "C", "https://www.reddit.com/r/emergingmarkets/.rss"),       # VERIFY (429-prone)
    ("r_geopol",   "Reddit r/geopolitics",          "C", "https://www.reddit.com/r/geopolitics/.rss"),           # VERIFY (429-prone)
    # X/Twitter deliberately NOT added -- no public RSS since 2023.
]

# -------------------------------------------------------------------
# DOMAIN_TIER  ::  domain -> tier. Promotes GDELT firehose by publisher.
# -------------------------------------------------------------------
DOMAIN_TIER = {
    "reuters.com": "A", "ft.com": "A", "bloomberg.com": "A",
    "wsj.com": "A", "economist.com": "A", "apnews.com": "A",
    "nytimes.com": "A", "cnbc.com": "B", "imf.org": "A",
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
    "piie.com": "B", "cepr.org": "B",
    "economictimes.indiatimes.com": "B", "livemint.com": "B",
    "caixinglobal.com": "B", "thejakartapost.com": "B",
    "hurriyetdailynews.com": "B", "moneyweb.co.za": "B",
    "batimes.com.ar": "B", "reddit.com": "C",
    # ---- v3.3 additions ----
    "dw.com": "B", "france24.com": "A", "intellinews.com": "A",
    "allafrica.com": "B", "mercopress.com": "B", "africanews.com": "B",
    "channelnewsasia.com": "B", "dawn.com": "B", "thedailystar.net": "B",
    "koreaherald.com": "B", "taipeitimes.com": "B", "vnexpress.net": "B",
    "bangkokpost.com": "B", "arabnews.com": "B", "gulfnews.com": "B",
    "timesofisrael.com": "B", "dailymaverick.co.za": "B",
    "premiumtimesng.com": "B", "nation.africa": "B",
    "riotimesonline.com": "B", "notesfrompoland.com": "B",
    "kyivindependent.com": "B",
}

# -------------------------------------------------------------------
# FEED_ORIGIN_ISO  ::  source_id -> iso3 fallback for SINGLE-COUNTRY feeds.
# Used when the headline names no country, so the row still gets a desk.
# Pan-regional wires (bne/allafrica/mercopress/dw/france24/cna/africanews) are
# intentionally UNSET -- they're multi-country and rely on headline tagging.
# -------------------------------------------------------------------
FEED_ORIGIN_ISO = {
    "fed": "USA", "ecb": "EMU", "boe": "GBR", "boj": "JPN", "boc": "CAN",
    "bok": "KOR", "rbi": "IND", "bcb": "BRA", "rba": "AUS",
    # ---- single-country locals ----
    "et_markets": "IND", "livemint": "IND", "dawn": "PAK", "bdstar": "BGD",
    "koreaherald": "KOR", "taipeitimes": "TWN", "vnexpress": "VNM",
    "bangkokpost": "THA", "jakartapost": "IDN", "hurriyet": "TUR",
    "arabnews": "SAU", "gulfnews": "ARE", "timesofisrael": "ISR",
    "moneyweb": "ZAF", "dailymaverick": "ZAF", "premiumtimes": "NGA",
    "nationkenya": "KEN", "ba_times": "ARG", "riotimes": "BRA",
    "notesfrompoland": "POL", "kyivindependent": "UKR",
}

# -------------------------------------------------------------------
# GDELT  ::  search-API call (not RSS).
# -------------------------------------------------------------------
GDELT_ENABLED     = FEATURE_FLAGS["ingest_gdelt"]
GDELT_TIER        = "C"
GDELT_TIMESPAN    = "3d"
GDELT_MAXRECORDS  = 60
GDELT_LANG        = "english"
GDELT_EM_ONLY     = False
GDELT_SLEEP_SEC   = 2.0

# -------------------------------------------------------------------
# NEWS_COUNTRY_ALIASES  ::  keyword -> iso3 (LOWERCASE, word-boundary matched;
# merged on top of news_ingest.BASE_ALIASES). Entries <4 chars or on
# ALIAS_BLOCKLIST are inert. For UPPERCASE acronyms (US/UK/EU/UAE) that must NOT
# match their lowercase words, see news_ingest.ACRONYM_ALIASES (case-sensitive).
#
# RULES when extending: >=4 chars; never a plain English word; prefer capital +
# demonym + institution; avoid ambiguous personal names.
# v3.3: filled in the smaller / WATCH countries that previously had only their
# bare country name -> this is what shrinks the "(no desk)" pile.
# -------------------------------------------------------------------
NEWS_COUNTRY_ALIASES = {
    # ===== G10 / majors (supplement BASE_ALIASES) =====
    "fomc": "USA", "treasury": "USA", "white house": "USA", "congress": "USA",
    "wall street": "USA", "biden": "USA", "powell": "USA", "pentagon": "USA",
    "hawaii": "USA", "manhattan": "USA", "silicon valley": "USA",
    "eurozone": "EMU", "euro area": "EMU", "brussels": "EMU", "lagarde": "EMU",
    "european commission": "EMU", "frankfurt": "EMU",
    "starmer": "GBR", "westminster": "GBR", "whitehall": "GBR", "sterling": "GBR",
    "ottawa": "CAN", "carney": "CAN", "canberra": "AUS", "sydney": "AUS",
    "wellington": "NZL", "zurich": "CHE", "geneva": "CHE",
    "oslo": "NOR", "stockholm": "SWE",
    # ===== EAS / SEA =====
    "beijing": "CHN", "shanghai": "CHN", "xi jinping": "CHN", "renminbi": "CHN",
    "tokyo": "JPN", "seoul": "KOR", "taipei": "TWN", "hong kong": "HKG",
    "jakarta": "IDN", "prabowo": "IDN", "rupiah": "IDN",
    "kuala lumpur": "MYS", "anwar": "MYS", "ringgit": "MYS",
    "bangkok": "THA", "paetongtarn": "THA",
    "manila": "PHL", "marcos": "PHL",
    "hanoi": "VNM", "ho chi minh": "VNM",
    "phnom penh": "KHM", "cambodian": "KHM", "vientiane": "LAO", "laotian": "LAO",
    "naypyidaw": "MMR", "yangon": "MMR", "myanmar junta": "MMR",
    "ulaanbaatar": "MNG", "mongolian": "MNG",
    "pyongyang": "PRK", "kim jong": "PRK",
    "bandar seri begawan": "BRN", "bruneian": "BRN", "dili": "TLS",
    # ===== CSA =====
    "new delhi": "IND", "mumbai": "IND", "modi": "IND",
    "islamabad": "PAK", "karachi": "PAK", "lahore": "PAK",
    "dhaka": "BGD", "bangladeshi": "BGD",
    "colombo": "LKA", "sri lankan": "LKA",
    "astana": "KAZ", "almaty": "KAZ", "kazakh": "KAZ",
    "kabul": "AFG", "taliban": "AFG", "afghan": "AFG",
    "kathmandu": "NPL", "nepali": "NPL", "nepalese": "NPL",
    "thimphu": "BTN", "bhutanese": "BTN",
    "tashkent": "UZB", "uzbek": "UZB", "bishkek": "KGZ", "kyrgyz": "KGZ",
    "dushanbe": "TJK", "tajik": "TJK", "male maldives": "MDV", "maldivian": "MDV",
    # ===== LATAM =====
    "brasilia": "BRA", "sao paulo": "BRA", "lula": "BRA",
    "mexico city": "MEX", "sheinbaum": "MEX",
    "santiago": "CHL", "chilean": "CHL", "bogota": "COL", "colombian": "COL",
    "lima": "PER", "peruvian": "PER",
    "buenos aires": "ARG", "milei": "ARG",
    "montevideo": "URY", "uruguayan": "URY", "quito": "ECU", "ecuadorian": "ECU",
    "la paz": "BOL", "bolivian": "BOL", "asuncion": "PRY", "paraguayan": "PRY",
    "caracas": "VEN", "maduro": "VEN", "venezuelan": "VEN",
    "panama city": "PAN", "panamanian": "PAN",
    "san jose costa rica": "CRI", "costa rican": "CRI",
    "santo domingo": "DOM", "dominican": "DOM", "kingston jamaica": "JAM",
    "jamaican": "JAM", "guatemala city": "GTM", "guatemalan": "GTM",
    "tegucigalpa": "HND", "honduran": "HND",
    "san salvador": "SLV", "bukele": "SLV", "salvadoran": "SLV",
    "managua": "NIC", "ortega": "NIC", "nicaraguan": "NIC",
    # ===== MEA =====
    "pretoria": "ZAF", "johannesburg": "ZAF", "cape town": "ZAF",
    "ramaphosa": "ZAF", "riyadh": "SAU", "jeddah": "SAU", "saudi": "SAU",
    "abu dhabi": "ARE", "dubai": "ARE", "emirati": "ARE",
    "doha": "QAT", "qatari": "QAT", "kuwait city": "KWT", "kuwaiti": "KWT",
    "cairo": "EGY", "egyptian": "EGY", "sisi": "EGY",
    "tel aviv": "ISR", "jerusalem": "ISR", "netanyahu": "ISR", "israeli": "ISR",
    "manama": "BHR", "bahraini": "BHR", "muscat": "OMN", "omani": "OMN",
    "amman": "JOR", "jordanian": "JOR",
    "rabat": "MAR", "casablanca": "MAR", "moroccan": "MAR",
    "tunis": "TUN", "tunisian": "TUN",
    "abuja": "NGA", "lagos": "NGA", "tinubu": "NGA", "naira": "NGA",
    "nairobi": "KEN", "kenyan": "KEN", "accra": "GHA", "ghanaian": "GHA",
    "addis ababa": "ETH", "ethiopian": "ETH", "luanda": "AGO", "angolan": "AGO",
    "dodoma": "TZA", "dar es salaam": "TZA", "tanzanian": "TZA",
    "kampala": "UGA", "ugandan": "UGA", "museveni": "UGA",
    "lusaka": "ZMB", "zambian": "ZMB", "harare": "ZWE", "zimbabwean": "ZWE",
    "maputo": "MOZ", "mozambican": "MOZ", "windhoek": "NAM", "namibian": "NAM",
    "kigali": "RWA", "rwandan": "RWA", "gaborone": "BWA", "botswana pula": "BWA",
    "dakar": "SEN", "senegalese": "SEN", "abidjan": "CIV", "ivorian": "CIV",
    # ===== EME =====
    "warsaw": "POL", "polish": "POL", "zloty": "POL", "tusk": "POL",
    "budapest": "HUN", "orban": "HUN", "forint": "HUN",
    "prague": "CZE", "czech": "CZE", "koruna": "CZE",
    "ankara": "TUR", "istanbul": "TUR", "erdogan": "TUR",
    "athens": "GRC", "greek": "GRC", "bucharest": "ROU", "romanian": "ROU",
    "belgrade": "SRB", "serbian": "SRB", "vucic": "SRB",
    "zagreb": "HRV", "croatian": "HRV", "ljubljana": "SVN", "slovenian": "SVN",
    "tallinn": "EST", "estonian": "EST", "riga": "LVA", "latvian": "LVA",
    "vilnius": "LTU", "lithuanian": "LTU",
    "reykjavik": "ISL", "icelandic": "ISL",
    "kyiv": "UKR", "kiev": "UKR", "zelensky": "UKR", "ukrainian": "UKR",
    "minsk": "BLR", "lukashenko": "BLR", "belarusian": "BLR",
    "tirana": "ALB", "albanian": "ALB", "sarajevo": "BIH", "bosnian": "BIH",
    "chisinau": "MDA", "moldovan": "MDA", "podgorica": "MNE", "montenegrin": "MNE",
    "skopje": "MKD", "macedonian": "MKD",
}

# -------------------------------------------------------------------
# NEWS_TOPICS  ::  topic key -> keyword list (word-boundary matched, "*"=stem).
# v3.3: more geopolitics + new "disaster" topic so fewer rows fall to General.
# -------------------------------------------------------------------
NEWS_TOPICS = {
    "central_bank":  ["rate", "rates", "central bank", "policy rate", "hike",
                      "rate cut", "hawkish", "dovish", "monetary", "tightening",
                      "easing", "fomc", "boj", "ecb", "pboc", "rate decision",
                      "interest rate", "quantitative", "liquidity"],
    "econ_data":     ["gdp", "cpi", "ppi", "inflation", "deflation", "pmi",
                      "payroll", "payrolls", "unemployment", "jobs",
                      "retail sales", "industrial production", "trade balance",
                      "data print", "forecast", "revised", "recession",
                      "growth", "output", "budget", "deficit", "surplus"],
    "trade":         ["trade", "tariff", "tariffs", "export", "import",
                      "customs", "supply chain", "wto", "trade war", "embargo",
                      "quota", "trade deal"],
    "rates_credit":  ["bond", "yield", "debt", "default", "credit", "spread",
                      "downgrade", "upgrade", "rating", "sovereign",
                      "restructuring", "treasury", "curve", "duration",
                      "imf loan", "bailout", "eurobond", "issuance"],
    "fx":            ["currency", "fx", "exchange rate", "devaluation", "peg",
                      "reserves", "capital flows", "depreciat", "appreciat",
                      "intervention", "carry trade"],
    "commodities":   ["oil", "brent", "crude", "opec", "gas", "lng", "copper",
                      "gold", "iron ore", "wheat", "soybean", "commodity",
                      "commodities", "metals", "nickel", "lithium", "cobalt",
                      "palm oil", "grain"],
    "equities":      ["stocks", "equity", "equities", "shares", "ipo", "index",
                      "market rally", "selloff", "bourse", "listing", "buyback"],
    "energy":        ["energy", "power", "electricity", "renewable", "nuclear",
                      "coal", "pipeline", "solar", "hydro", "grid", "refinery",
                      "blackout"],
    "technology":    ["chip", "semiconductor", "ai ", "tech", "data center",
                      "technology", "startup", "artificial intelligence",
                      "rare earth", "rare-earth", "ev ", "battery", "cloud"],
    "geopolitics":   ["election", "government", "president", "coup", "protest",
                      "war", "conflict", "minister", "parliament", "coalition",
                      "referendum", "sanctions", "sanction", "military",
                      "geopolitic", "ceasefire", "truce", "airstrike", "strike",
                      "troops", "border", "occupation", "hostage", "kidnap",
                      "missile", "drone", "militant", "insurgent", "rebels",
                      "junta", "martial law", "impeach", "cabinet", "summit",
                      "treaty", "alliance", "nato", "embassy", "diplomat",
                      "talks", "nuclear weapon", "warhead", "annexation"],
    "disaster":      ["wildfire", "flood", "flooding", "earthquake", "typhoon",
                      "hurricane", "cyclone", "drought", "famine", "volcano",
                      "landslide", "storm", "evacuat", "death toll", "monsoon",
                      "heatwave", "outbreak", "epidemic"],
    "china":         ["china", "beijing", "yuan", "pboc", "xi jinping",
                      "property", "evergrande", "belt and road"],
}

# -------------------------------------------------------------------
# LOOK & FEEL  ::  SMU EM palette + Segoe UI. Mirror colour edits in
# assets/emdash.css (:root).
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
    """3-letter -> 2-letter ISO (IMF/DBnomics masks). Blank = DBnomics skipped."""
    _MAP = {
        "IDN": "ID", "MYS": "MY", "THA": "TH", "PHL": "PH", "VNM": "VN",
        "SGP": "SG", "KHM": "KH", "LAO": "LA", "MMR": "MM", "BRN": "BN",
        "TLS": "TL",
        "CHN": "CN", "KOR": "KR", "TWN": "TW", "JPN": "JP", "HKG": "HK",
        "MNG": "MN", "PRK": "KP",
        "IND": "IN", "PAK": "PK", "BGD": "BD", "LKA": "LK", "KAZ": "KZ",
        "AFG": "AF", "NPL": "NP", "BTN": "BT", "MDV": "MV", "UZB": "UZ",
        "KGZ": "KG", "TJK": "TJ",
        "BRA": "BR", "MEX": "MX", "CHL": "CL", "COL": "CO", "PER": "PE",
        "ARG": "AR", "URY": "UY", "ECU": "EC", "BOL": "BO", "PRY": "PY",
        "VEN": "VE", "PAN": "PA", "CRI": "CR", "DOM": "DO", "JAM": "JM",
        "GTM": "GT", "HND": "HN", "SLV": "SV", "NIC": "NI",
        "ZAF": "ZA", "SAU": "SA", "ARE": "AE", "QAT": "QA", "KWT": "KW",
        "EGY": "EG", "ISR": "IL", "BHR": "BH", "OMN": "OM", "JOR": "JO",
        "MAR": "MA", "TUN": "TN", "NGA": "NG", "KEN": "KE", "GHA": "GH",
        "ETH": "ET", "AGO": "AO", "TZA": "TZ", "UGA": "UG", "ZMB": "ZM",
        "ZWE": "ZW", "MOZ": "MZ", "NAM": "NA", "RWA": "RW", "BWA": "BW",
        "SEN": "SN", "CIV": "CI",
        "POL": "PL", "HUN": "HU", "CZE": "CZ", "TUR": "TR", "GRC": "GR",
        "ROU": "RO", "SRB": "RS", "HRV": "HR", "SVN": "SI", "EST": "EE",
        "LVA": "LV", "LTU": "LT", "ISL": "IS", "UKR": "UA", "BLR": "BY",
        "ALB": "AL", "BIH": "BA", "MDA": "MD", "MNE": "ME", "MKD": "MK",
        "USA": "US", "EMU": "U2", "GBR": "GB", "CAN": "CA", "AUS": "AU",
        "NZL": "NZ", "CHE": "CH", "NOR": "NO", "SWE": "SE",
    }
    return _MAP.get(iso3, "")


def classification_of(iso3: str) -> dict:
    """Full agency classification; falls back to coarse dm_em if not listed."""
    if iso3 in CLASSIFICATION:
        return CLASSIFICATION[iso3]
    dmem = next((dm for i, n, d, dm, fx in COUNTRIES if i == iso3), "-")
    tier = "core" if dmem in ("DM", "EM") else (
        "frontier" if dmem == "FM" else "watch")
    return {"msci": dmem, "ftse": dmem, "sp": dmem, "imf": "-", "tier": tier}


def tier_of(iso3: str) -> str:
    return classification_of(iso3).get("tier", "watch")


# ===================================================================
# DATA GAPS  ::  what is missing and what to do about it (human-readable).
# ===================================================================
# STRUCTURAL (do not chase): TWN macro (not WB/IMF member); WATCH-tier countries
#   (WB annual + news only, no tradeable FX/index/yield -- blank on purpose);
#   dollarised/EUR users have fx_ticker="" by design.
# SPARSE-BY-NATURE: EQUITY_INDICES ~40 markets; SOVEREIGN_YIELDS ~20.
# FIXABLE: any # VERIFY that pulls 0 rows = bad symbol/mask, not missing data.
# NEWS FEEDS (v3.3): every # VERIFY url must be tested from your PC with the
#   browser-UA patch. Dead-at-office (retest home): ecb/rba/bis/some locals.
#   Genuinely no-RSS: banxico, cbrt, sarb, X/Twitter -> covered via GDELT.
# NEWS TAGGING (v3.3): "(no desk)" that remains is mostly countries NOT in the
#   105-country universe (Iran, Iraq, Russia, Syria, Palestine, etc.). Those can
#   only be tagged if added to COUNTRIES -- a deliberate scope decision.
# CREDIT SPREADS / BLOOMBERG: unchanged (see prior notes).
