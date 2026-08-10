"""
SPX Daily Data Dashboard - Morning Data Aggregator   (Phase 0, hardened)
========================================================================

Purpose:
    Pull all key data needed for SPX credit spread daily analysis.
    Output a clean text block you can paste into Perplexity Free
    along with your compressed prompt.

    This is a DECISION-SUPPORT tool, not automation. It never places trades.
    Its first job is to surface your own risk rules (drawdown state, weekly
    loss limit, position caps, the 0-3 DTE ban) BEFORE any "go" signal,
    because the losses were behavioural, not analytical.

Author: Intern.2 (Gembridge)
Date:   Aug 2026  (Phase 0 hardening)

USAGE:
    python spx_daily_dashboard.py

OUTPUT:
    Prints a formatted text block to stdout.
    Also saves to spx_dashboard_YYYYMMDD.txt

DEPENDENCIES:
    pip install yfinance pandas numpy requests

WHAT CHANGED IN THIS PHASE-0 PASS (vs the original standalone script)
---------------------------------------------------------------------
1. VIX DIRECTION FIX. The old code called classify_direction(vix, 3, 3) and
   then the stress score tested vix_direction == "rising sharply" -- a string
   the classifier NEVER returned, so the VIX stress flag could never fire.
   New classify_vix_direction() uses a 1-day rule with VIX-appropriate
   thresholds and the stress test now matches the strings it returns.
2. ACCOUNT-STATE BLOCK AT THE TOP. Reads spx_account.json (falls back to
   ACCOUNT_DEFAULTS), computes drawdown state GREEN/YELLOW/ORANGE/RED, weekly
   loss vs the -$600 stop, open positions vs the caps, and the 0-3 DTE ban
   status. Printed FIRST, before any market read.
3. HARD-CODED EVENT CALENDAR. FOMC / CPI / NFP / PCE / GDP dates for the rest
   of 2026 (verified against BLS/BEA/Fed official schedules -- see EVENTS),
   plus monthly OpEx (third Friday) computed on the fly. Filtered to the next
   28 days and mapped to the DTE buckets each event sits inside.
4. SECTOR BREADTH (real). Counts how many of the 11 SPDR sector ETFs are above
   their 50-day MA. This finally lets the "breadth < 50%" stress flag fire.
5. VIX TERM STRUCTURE. ^VIX9D vs ^VIX: backwardation (9D > 30D) = stress and is
   bad for selling premium; contango = calmer. Feeds the stress score.
6. HONEST STRESS SCORE. The denominator is now the number of checks that
   actually had data today (so it reads "3 / 6 active signals", not "3 / 7"
   when breadth/HY were never computable).

NOTES
- Free data only (yfinance). MOVE (^MOVE) is often missing on Yahoo -> N/A.
- HY spreads (FRED BAMLH0A0HYM2) are deferred to the EMDASH-integrated Phase 1
  because FRED is firewall-blocked on the office network; kept as a manual
  placeholder here.
- Tickers marked # VERIFY (^VIX9D, ^MOVE, the sector ETFs) should be confirmed
  with one real run from home; the sandbox has no internet.
"""

import json
import warnings
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================
# CONFIG
# ============================================================

TICKERS = {
    "SPX": "^GSPC",       # S&P 500 Index
    "VIX": "^VIX",        # CBOE Volatility Index (30-day)
    "VIX9D": "^VIX9D",    # CBOE 9-day VIX (term-structure short end)   # VERIFY
    "MOVE": "^MOVE",      # ICE BofA MOVE Index, may not populate on Yahoo
    "DXY": "DX-Y.NYB",    # US Dollar Index
    "10Y": "^TNX",        # US 10Y Treasury Yield, Yahoo formatting can vary
    "WTI": "CL=F",        # WTI Crude Oil Futures
    "SPY": "SPY",         # SPY ETF, optional proxy for breadth later
}

# 11 SPDR sector ETFs -> breadth proxy (count above 50d MA).            # VERIFY
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI",
               "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]

OUTPUT_PREFIX = "spx_dashboard"

# ---- Strike distance calibration (ATR x VIX bucket). Non-negotiable table. ----
ATR_VIX_TABLE = {
    "0-3":   {"VIX<15": None, "VIX 15-20": None, "VIX 20-30": 2.0, "VIX>30": 2.5},
    "7":     {"VIX<15": 2.5,  "VIX 15-20": 2.0,  "VIX 20-30": 1.8, "VIX>30": 1.5},
    "10-14": {"VIX<15": 3.0,  "VIX 15-20": 2.5,  "VIX 20-30": 2.0, "VIX>30": 1.8},
    "15-21": {"VIX<15": 3.5,  "VIX 15-20": 3.0,  "VIX 20-30": 2.5, "VIX>30": 2.0},
}
# DTE bucket -> representative calendar days (used to map events to buckets).
DTE_BUCKET_DAYS = {"0-3": 3, "7": 7, "10-14": 14, "15-21": 21}

# ---- Risk rules (mandate) ----
DRAWDOWN_BANDS = [("GREEN", 0, 10), ("YELLOW", 10, 20),
                  ("ORANGE", 20, 30), ("RED", 30, 999)]
WEEKLY_LOSS_LIMIT = -600          # USD; hit this -> stop for the week
MAX_TOTAL_POSITIONS = 5
MAX_PER_DIRECTION = 2             # 3 only on very high conviction
ZERO_DTE_MIN_VIX = 20             # 0-3 DTE requires VIX > 20 (plus GREEN + 4 green wks)
ZERO_DTE_MIN_GREEN_WEEKS = 4

ACCOUNT_FILE = Path(__file__).with_name("spx_account.json")
ACCOUNT_DEFAULTS = {
    "account_value": 9000,
    "peak_value": 23000,
    "weekly_pnl": 0,
    "open_positions": {"CCS": 0, "PCS": 0},
    "consecutive_green_weeks": 0,
}

# ---- Hard-coded event calendar (rest of 2026). Dates VERIFIED against: ----
#   FOMC:  federalreserve.gov / financecalendar (Sep 15-16, Oct 27-28, Dec 8-9;
#          decision announced on the SECOND day at 2:00pm ET).
#   CPI:   BLS Schedule of Releases for the CPI (bls.gov).
#   NFP:   BLS Schedule of Releases for the Employment Situation (bls.gov).
#   PCE:   BEA Personal Income & Outlays release schedule (bea.gov).
#   GDP:   BEA (Q3 advance = the market-moving one).
# Severity: HIGH = binary, gap-risk; MED = matters but usually smaller.
# (date_iso, label, severity)
EVENTS = [
    # ---- FOMC decision days ----
    ("2026-09-16", "FOMC decision + SEP/dot plot + Powell presser", "HIGH"),
    ("2026-10-28", "FOMC decision", "HIGH"),
    ("2026-12-09", "FOMC decision + SEP/dot plot + Powell presser", "HIGH"),
    # ---- CPI (BLS) ----
    ("2026-08-12", "CPI (July)", "HIGH"),
    ("2026-09-11", "CPI (Aug)", "HIGH"),
    ("2026-10-14", "CPI (Sep)", "HIGH"),
    ("2026-11-10", "CPI (Oct)", "HIGH"),
    ("2026-12-10", "CPI (Nov)", "HIGH"),
    # ---- Jobs report / NFP (BLS) ----
    ("2026-09-04", "Jobs report / NFP (Aug)", "HIGH"),
    ("2026-10-02", "Jobs report / NFP (Sep)", "HIGH"),
    ("2026-11-06", "Jobs report / NFP (Oct)", "HIGH"),
    ("2026-12-04", "Jobs report / NFP (Nov)", "HIGH"),
    # ---- PCE (BEA, Fed's preferred gauge) ----
    ("2026-08-26", "Core PCE (July)", "MED"),
    ("2026-09-30", "Core PCE (Aug)", "MED"),
    ("2026-10-29", "Core PCE (Sep)", "MED"),
    ("2026-11-25", "Core PCE (Oct)", "MED"),
    ("2026-12-23", "Core PCE (Nov)", "MED"),
    # ---- GDP (BEA) advance estimate ----
    ("2026-10-29", "GDP Q3 advance estimate", "MED"),
]
EVENT_WINDOW_DAYS = 28


# ============================================================
# HELPERS  (unchanged compute core)
# ============================================================

def fetch_history(ticker, period="1y"):
    """Fetch historical price data from Yahoo Finance."""
    try:
        data = yf.Ticker(ticker).history(period=period, auto_adjust=False)

        if data is None or data.empty:
            print(f"[warn] no data returned for {ticker}")
            return None

        data = data.dropna(subset=["Close"])

        if data.empty:
            print(f"[warn] no valid close prices for {ticker}")
            return None

        return data

    except Exception as e:
        print(f"[warn] failed to fetch {ticker}: {e}")
        return None


def last_valid(series):
    """Return the latest valid value from a pandas Series."""
    clean = series.dropna()
    if clean.empty:
        return np.nan
    return clean.iloc[-1]


def pct_change_over(series, periods):
    """Compute percentage change over n periods safely."""
    clean = series.dropna()
    if len(clean) <= periods:
        return np.nan
    return (clean.iloc[-1] / clean.iloc[-periods - 1] - 1) * 100


def compute_atr(df, window=14):
    """Compute Average True Range."""
    if df is None or len(df) < window + 1:
        return np.nan

    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    return last_valid(tr.rolling(window).mean())


def compute_rsi(series, window=14):
    """Compute RSI."""
    clean = series.dropna()
    if len(clean) < window + 1:
        return np.nan

    delta = clean.diff()
    gain = delta.where(delta > 0, 0).rolling(window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window).mean()

    latest_loss = last_valid(loss)
    if pd.isna(latest_loss):
        return np.nan
    if latest_loss == 0:
        return 100.0

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return last_valid(rsi)


def compute_realized_vol(series, window=20):
    """Compute annualized realized volatility in percentage terms."""
    clean = series.dropna()
    if len(clean) < window + 1:
        return np.nan

    returns = clean.pct_change().dropna()
    realized_vol = returns.rolling(window).std() * np.sqrt(252) * 100
    return last_valid(realized_vol)


def compute_percentile(series, current_value):
    """Return the percentile of the current value within the provided series."""
    clean = series.dropna()
    if clean.empty or pd.isna(current_value):
        return np.nan
    return (clean < current_value).mean() * 100


def classify_direction(series, lookback=5, threshold=2):
    """Classify recent direction using % change over a lookback window.

    threshold is in percentage points. General-purpose (DXY, 10Y, MOVE, oil).
    NOT used for VIX any more -- see classify_vix_direction.
    """
    clean = series.dropna()
    if len(clean) < lookback + 1:
        return "unknown"

    pct = (clean.iloc[-1] / clean.iloc[-lookback - 1] - 1) * 100

    if abs(pct) < threshold:
        return "flat"
    elif pct > 2 * threshold:
        return "spiking"
    elif pct < -2 * threshold:
        return "crashing"
    elif pct > 0:
        return "up"
    else:
        return "down"


def classify_vix_direction(vix_close):
    """VIX-specific direction on a 1-DAY change (VIX moves are large and fast,
    so a 3-day window washed out single-day spikes -- the original bug).

    Returns one of: spiking / rising / flat / falling / collapsing / unknown.
    The stress score tests for 'spiking'/'rising', so the strings MATCH now.
    """
    clean = vix_close.dropna()
    if len(clean) < 2:
        return "unknown", np.nan

    chg = (clean.iloc[-1] / clean.iloc[-2] - 1) * 100
    if chg >= 10:
        d = "spiking"
    elif chg >= 5:
        d = "rising"
    elif chg <= -10:
        d = "collapsing"
    elif chg <= -5:
        d = "falling"
    else:
        d = "flat"
    return d, chg


def normalize_yahoo_tnx(raw_value):
    """Normalize Yahoo Finance ^TNX value into actual yield percentage.

    raw > 20  -> divide by 10   (47.00 means 4.70%)
    raw <= 20 -> use as-is       (4.70 already means 4.70%)
    """
    if pd.isna(raw_value):
        return np.nan
    if raw_value > 20:
        return raw_value / 10
    return raw_value


def compute_sector_breadth(period="6mo", window=50):
    """% of the 11 SPDR sector ETFs trading above their `window`-day MA.

    Returns (breadth_pct, n_above, n_valid, detail_dict). Missing/failed ETFs
    are skipped and the denominator shrinks, so one dead ticker doesn't lie.
    """
    n_above = 0
    n_valid = 0
    detail = {}
    for etf in SECTOR_ETFS:
        df = fetch_history(etf, period)
        if df is None or len(df) < window + 1:
            detail[etf] = None
            continue
        close = df["Close"].dropna()
        ma = last_valid(close.rolling(window).mean())
        px = last_valid(close)
        if pd.isna(ma) or pd.isna(px):
            detail[etf] = None
            continue
        above = bool(px > ma)
        detail[etf] = above
        n_valid += 1
        n_above += int(above)

    breadth_pct = (n_above / n_valid * 100) if n_valid else np.nan
    return breadth_pct, n_above, n_valid, detail


def compute_vix_term_structure(vix_spot):
    """^VIX9D vs ^VIX. ratio = VIX9D / VIX.

    ratio > 1  -> backwardation (short-end fear > 30d): STRESS, bad for premium.
    ratio < 1  -> contango: calmer, more favourable for selling premium.
    Returns (vix9d, ratio, verdict).
    """
    df = fetch_history(TICKERS["VIX9D"], "3mo")
    if df is None or df.empty or pd.isna(vix_spot) or vix_spot == 0:
        return np.nan, np.nan, "N/A"
    vix9d = last_valid(df["Close"].dropna())
    if pd.isna(vix9d):
        return np.nan, np.nan, "N/A"
    ratio = vix9d / vix_spot
    if ratio >= 1.0:
        verdict = "backwardation (stress; unfavourable for short premium)"
    elif ratio <= 0.9:
        verdict = "steep contango (calm; favourable)"
    else:
        verdict = "mild contango (normal)"
    return vix9d, ratio, verdict


def compute_stress_score(data):
    """Cross-asset stress score. Denominator = checks that HAD data today, so
    the score is honest (was hard-wired to /7 even when breadth/HY were never
    computed and could never fire).

    Returns (score, reasons, max_possible).
    """
    score = 0
    reasons = []
    max_possible = 0

    # 1) VIX rising fast (FIXED: strings now match classify_vix_direction)
    if data.get("vix_direction") not in (None, "unknown"):
        max_possible += 1
        if data.get("vix_direction") in ("spiking", "rising"):
            score += 1
            reasons.append(f"VIX {data['vix_direction']} "
                           f"({data.get('vix_1d_pct', float('nan')):+.1f}% 1d)")

    # 2) MOVE elevated
    if data.get("move_status") is not None:
        max_possible += 1
        if data.get("move_status") == "elevated":
            score += 1
            reasons.append("MOVE elevated vs 60d avg")

    # 3) DXY spiking
    if data.get("dxy_direction") not in (None, "unknown"):
        max_possible += 1
        if data.get("dxy_direction") == "spiking":
            score += 1
            reasons.append("DXY spiking")

    # 4) 10Y yield spiking
    if data.get("y10_direction") not in (None, "unknown"):
        max_possible += 1
        if data.get("y10_direction") == "spiking":
            score += 1
            reasons.append("10Y yield spiking")

    # 5) Sector breadth < 50% (NOW computable -> can actually fire)
    if not pd.isna(data.get("breadth", np.nan)):
        max_possible += 1
        if data["breadth"] < 50:
            score += 1
            reasons.append(f"Breadth below 50% ({data['breadth']:.0f}% of sectors > 50d MA)")

    # 6) VIX term structure in backwardation (NEW)
    if not pd.isna(data.get("vix_term_ratio", np.nan)):
        max_possible += 1
        if data["vix_term_ratio"] >= 1.0:
            score += 1
            reasons.append(f"VIX term structure in backwardation "
                           f"(9D/30D = {data['vix_term_ratio']:.2f})")

    # 7) Oil +5% in 5d
    if not pd.isna(data.get("oil_pct_5d", np.nan)):
        max_possible += 1
        if data["oil_pct_5d"] > 5:
            score += 1
            reasons.append(f"Oil +{data['oil_pct_5d']:.1f}% in 5d")

    # 8) HY spreads widening -- DEFERRED (FRED blocked at office). Only counts
    #    if something upstream actually set hy_status (Phase 1 / from home).
    if data.get("hy_status") is not None:
        max_possible += 1
        if data.get("hy_status") == "widening":
            score += 1
            reasons.append("HY spreads widening")

    return score, reasons, max_possible


def fmt_num(value, decimals=2, comma=False):
    """Format numbers safely."""
    if pd.isna(value):
        return "N/A"
    if comma:
        return f"{value:,.{decimals}f}"
    return f"{value:.{decimals}f}"


def fmt_pct(value, decimals=2, signed=True):
    """Format percentages safely."""
    if pd.isna(value):
        return "N/A"
    if signed:
        return f"{value:+.{decimals}f}%"
    return f"{value:.{decimals}f}%"


# ============================================================
# ACCOUNT STATE  (discipline layer -- printed FIRST)
# ============================================================

def load_account_state():
    """Read spx_account.json; fall back to ACCOUNT_DEFAULTS with a warning."""
    if ACCOUNT_FILE.exists():
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            merged = dict(ACCOUNT_DEFAULTS)
            merged.update(state or {})
            merged["_source"] = ACCOUNT_FILE.name
            return merged
        except Exception as e:
            print(f"[warn] could not read {ACCOUNT_FILE.name}: {e} -> using defaults")
    else:
        print(f"[warn] {ACCOUNT_FILE.name} not found -> using defaults. "
              f"Edit that file with your real numbers.")
    merged = dict(ACCOUNT_DEFAULTS)
    merged["_source"] = "DEFAULTS (edit spx_account.json)"
    return merged


def drawdown_state(value, peak):
    """Return (band, dd_pct). Bands from peak: GREEN<10 YELLOW10-20 ORANGE20-30 RED>30."""
    if not peak or peak <= 0:
        return "UNKNOWN", np.nan
    dd = (peak - value) / peak * 100
    dd = max(dd, 0.0)
    for band, lo, hi in DRAWDOWN_BANDS:
        if lo <= dd < hi:
            return band, dd
    return "RED", dd


def zero_dte_status(band, green_weeks, vix):
    """The 0-3 DTE ban. Allowed ONLY if GREEN + >=4 green weeks + VIX>20
    (AND the downstream analysis explicitly says 'Acceptable' -- external)."""
    reasons = []
    ok = True
    if band != "GREEN":
        ok = False
        reasons.append(f"drawdown state is {band}, not GREEN")
    if (green_weeks or 0) < ZERO_DTE_MIN_GREEN_WEEKS:
        ok = False
        reasons.append(f"only {green_weeks or 0} consecutive green weeks "
                       f"(need {ZERO_DTE_MIN_GREEN_WEEKS})")
    if pd.isna(vix) or vix <= ZERO_DTE_MIN_VIX:
        ok = False
        reasons.append(f"VIX {fmt_num(vix, 1)} not > {ZERO_DTE_MIN_VIX}")
    if ok:
        return "ELIGIBLE (pending the analysis explicitly saying '0-3 DTE: Acceptable')", reasons
    return "BANNED", reasons


def format_account_block(acct, vix):
    """The discipline banner. Everything the behavioural failures needed to see."""
    lines = []
    value = acct.get("account_value", np.nan)
    peak = acct.get("peak_value", np.nan)
    wpnl = acct.get("weekly_pnl", 0) or 0
    pos = acct.get("open_positions", {}) or {}
    ccs = int(pos.get("CCS", 0) or 0)
    pcs = int(pos.get("PCS", 0) or 0)
    total = ccs + pcs
    green_weeks = acct.get("consecutive_green_weeks", 0) or 0

    band, dd = drawdown_state(value, peak)
    z_status, z_reasons = zero_dte_status(band, green_weeks, vix)

    lines.append("#" * 60)
    lines.append("ACCOUNT & DISCIPLINE  -- READ BEFORE ANYTHING ELSE")
    lines.append("#" * 60)
    lines.append(f"- Source: {acct.get('_source', '?')}")
    lines.append(f"- Account value: ${value:,.0f}   (peak ${peak:,.0f})")
    lines.append(f"- Drawdown from peak: {fmt_num(dd, 1)}%  ->  STATE: {band}")
    if band in ("ORANGE", "RED"):
        lines.append(f"  * {band}: size down / stop. RED (>30%) = NO trading for 7 days.")

    # weekly loss limit
    lines.append(f"- Weekly P&L: ${wpnl:,.0f}   (weekly stop at ${WEEKLY_LOSS_LIMIT})")
    if wpnl <= WEEKLY_LOSS_LIMIT:
        lines.append("  * WEEKLY STOP HIT -> no new positions for the rest of the week.")
    else:
        room = wpnl - WEEKLY_LOSS_LIMIT
        lines.append(f"  * ${room:,.0f} of weekly loss budget left before the stop.")

    # position caps
    lines.append(f"- Open positions: {total}/{MAX_TOTAL_POSITIONS} total  "
                 f"(CCS {ccs}/{MAX_PER_DIRECTION}, PCS {pcs}/{MAX_PER_DIRECTION})")
    if total >= MAX_TOTAL_POSITIONS:
        lines.append("  * At the 5-position cap -> no new positions.")
    if ccs >= MAX_PER_DIRECTION:
        lines.append("  * CCS at the per-direction cap -> do NOT stack more calls.")
    if pcs >= MAX_PER_DIRECTION:
        lines.append("  * PCS at the per-direction cap -> do NOT stack more puts.")

    # 0-3 DTE ban
    lines.append(f"- 0-3 DTE: {z_status}")
    if z_reasons:
        for r in z_reasons:
            lines.append(f"    - {r}")

    # behavioural checklist -- the actual failure modes
    lines.append("- Behavioural check (answer honestly before trading):")
    lines.append("    [ ] Am I tired / trading late at night? (every blowup was a late 0-DTE)")
    lines.append("    [ ] Am I revenge-trading a loss / chasing the old watermark?")
    lines.append("    [ ] Have I already hit today's / this week's limit?")
    lines.append("    [ ] Is there an event in the next 28d I'm ignoring? (see EVENTS)")
    lines.append("- Priority order: survivability > tail risk > don't fight trends > "
                 "consistency > return.")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# EVENT CALENDAR
# ============================================================

def _third_friday(year, month):
    """Third Friday of a month = monthly SPX/OpEx expiry."""
    d = date(year, month, 1)
    # weekday(): Mon=0 ... Fri=4
    first_friday = 1 + (4 - d.weekday()) % 7
    return date(year, month, first_friday + 14)


def upcoming_opex(today, months_ahead=2):
    """Monthly OpEx (third Friday) for this and the next `months_ahead` months."""
    out = []
    y, m = today.year, today.month
    for i in range(months_ahead + 1):
        mm = m + i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        fri = _third_friday(yy, mm)
        if fri >= today:
            quarterly = mm in (3, 6, 9, 12)
            label = "Triple witching / quarterly OpEx" if quarterly else "Monthly OpEx"
            out.append((fri.isoformat(), label, "MED"))
    return out


def upcoming_events(today, window_days=EVENT_WINDOW_DAYS):
    """All hard-coded events + OpEx within `window_days`, sorted, with days-away
    and the DTE buckets each event sits inside."""
    horizon = today + timedelta(days=window_days)
    allev = list(EVENTS) + upcoming_opex(today)
    rows = []
    for iso, label, sev in allev:
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        if today <= d <= horizon:
            days_away = (d - today).days
            buckets = [b for b, bd in DTE_BUCKET_DAYS.items() if bd >= days_away]
            rows.append((d, iso, label, sev, days_away, buckets))
    rows.sort(key=lambda r: r[0])
    return rows


def format_events_block(today):
    rows = upcoming_events(today)
    lines = ["EVENTS (next %dd) -- auto-filled, verify big ones:" % EVENT_WINDOW_DAYS]
    if not rows:
        lines.append("- none in the window (still sanity-check an econ calendar).")
        lines.append("")
        return "\n".join(lines)
    for _d, _iso, label, sev, days_away, buckets in rows:
        when = "TODAY" if days_away == 0 else f"in {days_away}d"
        b = ("affects DTE " + "/".join(buckets)) if buckets else "beyond 21 DTE"
        flag = "!! " if sev == "HIGH" else "   "
        lines.append(f"- {flag}{_iso} ({when}) {label} [{sev}] -> {b}")
    lines.append("  Rule: a spread that expires ON/AFTER a HIGH event carries that "
                 "event's gap risk. Prefer DTE that expires BEFORE it, or widen strikes.")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# MAIN PIPELINE
# ============================================================

def build_dashboard():
    now = datetime.now()
    date_str = now.strftime("%d %b %Y")

    out = {}
    warnings_list = []

    # ---- SPX ----
    spx = fetch_history(TICKERS["SPX"], "1y")
    if spx is not None and len(spx) > 200:
        spx_close = spx["Close"].dropna()

        out["spx"] = last_valid(spx_close)
        out["spx_1d_pct"] = pct_change_over(spx_close, 1)
        out["spx_5d_pct"] = pct_change_over(spx_close, 5)
        out["spx_ath"] = spx_close.max()
        out["spx_from_ath_pct"] = (out["spx"] / out["spx_ath"] - 1) * 100

        out["ma20"] = last_valid(spx_close.rolling(20).mean())
        out["ma50"] = last_valid(spx_close.rolling(50).mean())
        out["ma200"] = last_valid(spx_close.rolling(200).mean())

        out["atr14"] = compute_atr(spx, 14)
        out["rsi14"] = compute_rsi(spx_close, 14)
        out["realized_vol_20d"] = compute_realized_vol(spx_close, 20)

        above = sum([out["spx"] > out["ma20"],
                     out["spx"] > out["ma50"],
                     out["spx"] > out["ma200"]])
        out["ma_position"] = {
            3: "above all MAs -> strong uptrend",
            2: "above 2 of 3 key MAs -> constructive but watch pullbacks",
            1: "above only 1 of 3 key MAs -> caution",
            0: "below all MAs -> defensive",
        }[above]

        recent = spx_close.tail(60)
        out["swing_high_60d"] = recent.max()
        out["swing_low_60d"] = recent.min()
    else:
        warnings_list.append("SPX data missing or insufficient for 200d MA.")

    # ---- VIX ----
    vix = fetch_history(TICKERS["VIX"], "1y")
    if vix is not None and len(vix) > 20:
        vix_close = vix["Close"].dropna()

        out["vix"] = last_valid(vix_close)
        out["vix_1d_pct"] = pct_change_over(vix_close, 1)
        # FIX: VIX-specific 1-day classifier (strings match the stress test)
        out["vix_direction"], _vchg = classify_vix_direction(vix_close)
        out["vix_percentile_1y"] = compute_percentile(vix_close, out["vix"])

        v = out["vix"]
        if v < 15:
            out["vix_bucket"] = "VIX<15"
        elif v < 20:
            out["vix_bucket"] = "VIX 15-20"
        elif v < 30:
            out["vix_bucket"] = "VIX 20-30"
        else:
            out["vix_bucket"] = "VIX>30"
    else:
        warnings_list.append("VIX data missing or insufficient.")

    # ---- VIX term structure (9D vs 30D) ----
    if "vix" in out:
        vix9d, ratio, verdict = compute_vix_term_structure(out["vix"])
        out["vix9d"] = vix9d
        out["vix_term_ratio"] = ratio
        out["vix_term_verdict"] = verdict
        if pd.isna(ratio):
            warnings_list.append("VIX9D (^VIX9D) missing on Yahoo -> term structure N/A.")

    # ---- IV / RV ratio ----
    if "vix" in out and not pd.isna(out.get("realized_vol_20d", np.nan)):
        out["iv_rv_ratio"] = out["vix"] / out["realized_vol_20d"]
        if out["iv_rv_ratio"] > 1.3:
            out["iv_rv_verdict"] = "IV overpricing risk (good for selling premium)"
        elif out["iv_rv_ratio"] < 0.9:
            out["iv_rv_verdict"] = "IV underpricing risk (poor comp for premium)"
        else:
            out["iv_rv_verdict"] = "IV roughly fair"

    # ---- MOVE ----
    move = fetch_history(TICKERS["MOVE"], "1y")
    if move is not None and len(move) > 60:
        m = move["Close"].dropna()
        out["move"] = last_valid(m)
        out["move_direction"] = classify_direction(m, 5, 3)
        move_60d_avg = last_valid(m.rolling(60).mean())
        out["move_status"] = "elevated" if out["move"] > move_60d_avg * 1.1 else "normal"
    else:
        warnings_list.append("MOVE data missing or insufficient (common on Yahoo).")

    # ---- DXY ----
    dxy = fetch_history(TICKERS["DXY"], "6mo")
    if dxy is not None and len(dxy) > 10:
        d = dxy["Close"].dropna()
        out["dxy"] = last_valid(d)
        out["dxy_direction"] = classify_direction(d, 5, 1)
    else:
        warnings_list.append("DXY data missing or insufficient.")

    # ---- 10Y ----
    y10 = fetch_history(TICKERS["10Y"], "6mo")
    if y10 is not None and len(y10) > 10:
        y = y10["Close"].dropna()
        raw_y10 = last_valid(y)
        out["y10_raw"] = raw_y10
        out["y10"] = normalize_yahoo_tnx(raw_y10)
        out["y10_direction"] = classify_direction(y, 5, 3)
        if out["y10"] < 1 or out["y10"] > 8:
            warnings_list.append(
                f"US 10Y looks unusual after normalization: {out['y10']:.2f}%. "
                f"Check Yahoo ^TNX feed.")
    else:
        warnings_list.append("US 10Y data missing or insufficient.")

    # ---- Oil ----
    oil = fetch_history(TICKERS["WTI"], "3mo")
    if oil is not None and len(oil) > 10:
        o = oil["Close"].dropna()
        out["oil"] = last_valid(o)
        out["oil_1d_pct"] = pct_change_over(o, 1)
        out["oil_pct_5d"] = pct_change_over(o, 5)
        out["oil_direction"] = classify_direction(o, 5, 2)
    else:
        warnings_list.append("WTI oil data missing or insufficient.")

    # ---- Sector breadth (feeds stress) ----
    breadth_pct, n_above, n_valid, detail = compute_sector_breadth()
    out["breadth"] = breadth_pct
    out["breadth_n_above"] = n_above
    out["breadth_n_valid"] = n_valid
    out["breadth_detail"] = detail
    if n_valid == 0:
        warnings_list.append("Sector breadth unavailable (all sector ETFs failed).")

    # ---- Stress Score (now honest denominator) ----
    out["stress_score"], out["stress_reasons"], out["stress_max"] = \
        compute_stress_score(out)
    out["warnings"] = warnings_list

    return out, date_str


# ============================================================
# OUTPUT FORMATTING
# ============================================================

def format_output(d, date_str, acct):
    """Format the dashboard data into a clean text block for the AI prompt."""
    lines = []

    # ---- ACCOUNT / DISCIPLINE FIRST ----
    lines.append(format_account_block(acct, d.get("vix", np.nan)))

    lines.append("=" * 60)
    lines.append(f"SPX DAILY DATA - {date_str} (SGT)")
    lines.append("=" * 60)
    lines.append("")

    # ---- EVENTS (auto-filled) ----
    lines.append(format_events_block(date.today()))

    # PRICE
    lines.append("PRICE:")
    if "spx" in d:
        lines.append(f"- SPX: {d['spx']:,.0f} "
                     f"({fmt_pct(d['spx_1d_pct'])} 1d, {fmt_pct(d['spx_5d_pct'])} 5d)")
        lines.append(f"- Distance from ATH: {fmt_pct(d['spx_from_ath_pct'])}")
        lines.append(f"- 20d MA: {d['ma20']:,.0f}")
        lines.append(f"- 50d MA: {d['ma50']:,.0f}")
        lines.append(f"- 200d MA: {d['ma200']:,.0f}")
        lines.append(f"- Position: {d['ma_position']}")
        lines.append(f"- 14d ATR: {fmt_num(d['atr14'], 1)} pts")
        lines.append(f"- RSI(14): {fmt_num(d['rsi14'], 1)}")
        lines.append(f"- 60d swing high: {d['swing_high_60d']:,.0f}")
        lines.append(f"- 60d swing low: {d['swing_low_60d']:,.0f}")
    else:
        lines.append("- SPX: N/A")
    lines.append("")

    # VOLATILITY
    lines.append("VOLATILITY:")
    if "vix" in d:
        lines.append(f"- VIX: {fmt_num(d['vix'], 2)} "
                     f"({fmt_pct(d['vix_1d_pct'])}, direction: {d['vix_direction']})")
        lines.append(f"- VIX 1y percentile: {fmt_num(d['vix_percentile_1y'], 0)}%")
        lines.append(f"- VIX bucket: {d['vix_bucket']}")
    else:
        lines.append("- VIX: N/A")

    if not pd.isna(d.get("vix_term_ratio", np.nan)):
        lines.append(f"- VIX term structure: 9D {fmt_num(d.get('vix9d'), 2)} vs "
                     f"30D {fmt_num(d.get('vix'), 2)} -> ratio {fmt_num(d['vix_term_ratio'], 2)} "
                     f"({d.get('vix_term_verdict', '')})")
    else:
        lines.append("- VIX term structure: N/A")

    if "move" in d:
        lines.append(f"- MOVE: {fmt_num(d['move'], 2)} "
                     f"(direction: {d['move_direction']}, status: {d['move_status']})")
    else:
        lines.append("- MOVE: N/A")

    if "realized_vol_20d" in d:
        lines.append(f"- Realized vol (20d): {fmt_num(d['realized_vol_20d'], 2)}%")
    if "iv_rv_ratio" in d:
        lines.append(f"- IV/RV ratio: {fmt_num(d['iv_rv_ratio'], 2)} -> {d['iv_rv_verdict']}")
    lines.append("")

    # CROSS-ASSET
    lines.append("CROSS-ASSET:")
    if "dxy" in d:
        lines.append(f"- DXY: {fmt_num(d['dxy'], 2)} ({d['dxy_direction']})")
    else:
        lines.append("- DXY: N/A")

    if "y10" in d:
        lines.append(f"- US 10Y: {fmt_num(d['y10'], 2)}% ({d['y10_direction']})")
        lines.append(f"  * Yahoo ^TNX raw value: {fmt_num(d['y10_raw'], 2)}")
    else:
        lines.append("- US 10Y: N/A")

    if "oil" in d:
        lines.append(f"- WTI Oil: ${fmt_num(d['oil'], 2)} "
                     f"({fmt_pct(d['oil_1d_pct'])} 1d, {fmt_pct(d['oil_pct_5d'])} 5d)")
    else:
        lines.append("- WTI Oil: N/A")

    # breadth
    if not pd.isna(d.get("breadth", np.nan)):
        lines.append(f"- Sector breadth: {d['breadth']:.0f}% of sectors above 50d MA "
                     f"({d['breadth_n_above']}/{d['breadth_n_valid']})")
    else:
        lines.append("- Sector breadth: N/A")

    # stress score (honest denominator)
    smax = d.get("stress_max", 0)
    lines.append(f"- Cross-asset stress score: {d.get('stress_score', 'N/A')}/{smax} "
                 f"active signals")
    if d.get("stress_reasons"):
        for reason in d["stress_reasons"]:
            lines.append(f"  * {reason}")
    else:
        lines.append("  * No major cross-asset stress flags triggered")
    lines.append("")

    # STRIKE DISTANCE
    if "atr14" in d and "vix_bucket" in d and not pd.isna(d["atr14"]):
        lines.append("STRIKE DISTANCE (ATR x VIX bucket -- short strike >= this far from spot):")
        atr = d["atr14"]
        bucket = d["vix_bucket"]
        for dte, m_dict in ATR_VIX_TABLE.items():
            mult = m_dict[bucket]
            if mult is None:
                lines.append(f"- {dte} DTE: BANNED (VIX too low for 0-3 DTE)")
            else:
                dist = mult * atr
                zone = d["spx"] - dist if "spx" in d else np.nan
                lines.append(f"- {dte} DTE: {mult}x ATR = {dist:.0f} pts from spot "
                             f"(downside short-strike ~ {zone:,.0f})")
        lines.append(f"  (VIX bucket today: {bucket})")
    else:
        lines.append("STRIKE DISTANCE:")
        lines.append("- N/A due to missing ATR or VIX bucket")
    lines.append("")

    # SENTIMENT PLACEHOLDER (still manual / deferred)
    lines.append("SENTIMENT (fill in / Phase 1):")
    lines.append("- P/C ratio (Cboe): [ ]")
    lines.append("- CNN Fear & Greed: [ ]")
    lines.append("- Polymarket / Kalshi (relevant): [ ]")
    lines.append("- HY credit spreads (FRED BAMLH0A0HYM2): [ ]  (blocked at office; run from home)")
    lines.append("")

    # WARNINGS
    if d.get("warnings"):
        lines.append("DATA WARNINGS / CHECKS:")
        for warning in d["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("END OF DATA - paste into AI prompt")
    lines.append("=" * 60)

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    warnings.filterwarnings("default")

    print("Building SPX daily dashboard...\n")

    acct = load_account_state()
    data, date_str = build_dashboard()
    output = format_output(data, date_str, acct)

    print(output)

    fname = f"{OUTPUT_PREFIX}_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"\n\n[saved to {fname}]")
