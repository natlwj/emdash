"""
EMDASH :: mrc.py   (Macro Regime Classifier -- v2, RULES-based)

WHAT THIS IS
A transparent, hand-checkable classifier that labels EACH DAY as one of a small
set of macro regimes -- Risk-Off / Risk-On / Goldilocks / Neutral -- from a
handful of global gauges. No ML, no HMM, no black box: every rule is a plain
z-score threshold you can read out loud to a PM.

------------------------------------------------------------------------------
WHAT CHANGED IN v2  (all of it from the CIO review, 30 Jul 2026)
------------------------------------------------------------------------------
1. EM_FX REMOVED.  v1 built an "average EM currency" gauge by rebasing each EM
   currency to 1.0 and taking an unweighted mean.  That was broken two ways:
     (a) EM currencies structurally DEPRECIATE, so the index only ever trends
         up -> its z-score sat persistently positive -> the Risk-Off vote was
         almost permanently switched on.  That is why v1 printed Risk-Off on
         ~50% of all days.
     (b) ARS went from ~4 to >1000 per USD over the window, so the unweighted
         mean was ~90% Argentina.  It was an Argentina gauge, not an EM gauge.
   CIO: "EM-FX rmv; DXY enuf."  Agreed -- DXY already carries the dollar read.

2. MOVE NOW VOTES IN RISK-ON.  v1 only used MOVE for Risk-Off, so a calm
   rates market could not contribute to a Risk-On reading.  CIO: "risk on MOVE
   shd be low".  Added.

3. BRENT NOW VOTES IN RISK-OFF.  v1 only used Brent for Risk-On.  CIO: "oil and
   copper big drivers of economies; the 2 big ones. in theory, oil weak means
   economy doing badly, besides special cases eg supply disruption. same for
   copper."  So weak oil is now a Risk-Off vote, symmetric with copper.

4. NEW OPTIONAL GAUGES (activate automatically once the data is in the
   warehouse -- no code change needed):
     BBB_OAS / IG_OAS  investment-grade credit stress
     HY_OAS            high-yield credit stress
     SWAP_SPREAD_10Y   USD swap spread  (KIV: no clean free source; the user
                       intends to pull this from Bloomberg later)
     BTC               risk appetite / liquidity proxy
   Each is skipped silently if the series is absent, so this file runs today
   and gets better the moment ingest.py starts filling those series.

5. HYSTERESIS (anti-flicker).  v1 labelled every day independently, so the
   regime ribbon flickered colour almost daily -- regimes do not really behave
   like that.  A raw label must now PERSIST for `min_days` consecutive days
   before it is confirmed; until then the previous confirmed regime is carried
   forward.  `min_days` is user-settable (config.MRC_MIN_DAYS, or the
   --days flag, or the argument).  Set it to 1 to get the old behaviour.

6. WHY-TABLE.  contributions() returns the per-gauge vote for any single day,
   so the UI (or you, at the terminal) can answer "why is today Risk-Off?"
   with an actual breakdown instead of a bare label.

------------------------------------------------------------------------------
THE CIO'S MENTAL MODEL  (worth keeping in the file, it is the "why")
------------------------------------------------------------------------------
  VIX   equity vol      -> reads across to INVESTMENT GRADE credit spreads
  MOVE  rates vol       -> reads across to HIGH YIELD credit spreads
        MOVE high is bad in general: uncertainty about the path of interest
        rates means discount rates are unstable, so valuation models fail.
  DXY   the dollar      -> up = global tightening / risk-off
  BRENT oil             -> weak = the economy is doing badly (unless it is a
                           supply story, which this classifier cannot see)
  COPPER                -> same logic; the classic global growth read
------------------------------------------------------------------------------

HOW A DAY IS SCORED
Each gauge becomes a rolling z-score (how unusual is today vs the last ~1yr).
Then each regime is a scorecard of plain threshold votes:

  Risk-Off   += VIX high, MOVE high, DXY high, COPPER weak, BRENT weak,
                (credit spreads wide, BTC weak -- when available)
  Risk-On    += VIX low,  MOVE low,  DXY soft, COPPER strong, BRENT firm,
                (credit spreads tight, BTC strong -- when available)
  Goldilocks += quiet vol AND stable dollar AND firm growth read, no stress

The winning bucket is the label; a weak or tied score falls back to "Neutral".
Then hysteresis smooths the sequence.

PURE-ISH: reads via core.get_global / core.get_commodity (the librarian) and
does maths via signals.py.  Does NOT write to the DB (the empty regime_state
table stays a future hook).

Run:  python mrc.py                # self-test on synthetic data (no DB needed)
      python mrc.py --live         # classify the real warehouse
      python mrc.py --live --days 10   # stronger anti-flicker
      python mrc.py --live --why       # explain the latest day
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

try:
    import config
except Exception:
    config = None

try:
    import signals as sig
except Exception:
    sig = None

try:
    import core
except Exception:
    core = None


REGIMES = ("Risk-Off", "Risk-On", "Goldilocks", "Neutral")


def _cfg(name: str, default):
    """Read a knob from config.py, falling back to the default if config is
    absent (self-test mode) or the knob has not been added yet.

    Everything tunable lives in config.MRC_* so this file has no hidden magic
    numbers -- edit the control panel, not the engine.
    """
    if config is None:
        return default
    return getattr(config, name, default)


# rolling window for the z-scores (~1 trading year)
Z_WINDOW = int(_cfg("MRC_Z_WINDOW", 252))

# how strong a z has to be to "count" as high/low
HI = float(_cfg("MRC_HI", 0.75))
LO = float(_cfg("MRC_LO", -0.75))
STABLE = float(_cfg("MRC_STABLE", 0.5))       # |z| below this = "stable/quiet"
MIN_SCORE = float(_cfg("MRC_MIN_SCORE", 2.0))  # else the day is Neutral

# anti-flicker: a new label must survive this many consecutive days before it
# is confirmed.  Overridable via config.MRC_MIN_DAYS / --days / argument.
DEFAULT_MIN_DAYS = int(_cfg("MRC_MIN_DAYS", 5))

# ---------------------------------------------------------------------------
# GAUGE REGISTRY
# Each entry: key -> (where to read it from, human description)
#   "global"    -> core.get_global(key)      (global_market table)
#   "commodity" -> core.get_commodity(key)   (commodity_data table)
# CORE gauges must be present for the classifier to be meaningful.
# OPTIONAL gauges are used automatically IF the warehouse has them, and are
# skipped in silence if not -- so nothing breaks before ingest catches up.
# ---------------------------------------------------------------------------
CORE_GAUGES = {
    "VIX":    ("global",    "equity vol -- reads across to IG credit spreads"),
    "MOVE":   ("global",    "rates vol -- reads across to HY credit spreads"),
    "DXY":    ("global",    "US dollar -- up = global tightening / risk-off"),
    "COPPER": ("commodity", "global growth read -- weak = economy weak"),
    "BRENT":  ("commodity", "global growth read -- weak = economy weak"),
}

OPTIONAL_GAUGES = {
    "BBB_OAS":         ("global", "IG (BBB) credit spread -- wide = stress"),
    "IG_OAS":          ("global", "IG credit spread -- wide = stress"),
    "HY_OAS":          ("global", "high-yield credit spread -- wide = stress"),
    "SWAP_SPREAD_10Y": ("global", "USD 10y swap spread -- funding/balance-sheet stress"),
    "BTC":             ("global", "risk appetite / liquidity proxy"),
}

ALL_GAUGES = {**CORE_GAUGES, **OPTIONAL_GAUGES}

# Gauges where a HIGH z-score means STRESS (so high -> Risk-Off vote).
STRESS_UP = ("VIX", "MOVE", "DXY", "BBB_OAS", "IG_OAS", "HY_OAS", "SWAP_SPREAD_10Y")

# Gauges where a HIGH z-score means RISK APPETITE (so high -> Risk-On vote).
RISK_UP = ("COPPER", "BRENT", "BTC")


# ===================================================================
# GAUGE ASSEMBLY
# ===================================================================
def _zseries(s: pd.Series, window: int = Z_WINDOW) -> pd.Series:
    """Rolling z-score of a series.

    Uses signals.zscore when available so the whole project shares one
    definition of "z-score".  Falls back to a local implementation (with a
    shorter warm-up) if signals.py cannot be imported.
    """
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return s
    if sig is not None:
        return sig.zscore(s, window=window)
    mu = s.rolling(window, min_periods=max(20, window // 4)).mean()
    sd = s.rolling(window, min_periods=max(20, window // 4)).std()
    return (s - mu) / sd.replace(0, np.nan)


def _read_gauge(key: str, kind: str, get_global=None, get_commodity=None):
    """Fetch one gauge series, or None if the warehouse does not have it."""
    if kind == "global":
        getter = get_global or (core.get_global if core is not None else None)
    else:
        getter = get_commodity or (core.get_commodity if core is not None else None)
    if getter is None:
        return None
    try:
        df = getter(key)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    try:
        return df.set_index("date")["value"].dropna()
    except Exception:
        return None


def assemble_gauges(get_global=None, get_market=None, get_commodity=None) -> pd.DataFrame:
    """Daily wide frame of the raw gauges (aligned, forward-filled).

    Columns present depend on what is actually in the warehouse -- missing
    optional gauges are simply absent, never faked.

    NOTE: `get_market` is accepted but no longer used.  v1 needed it to build
    the EM_FX gauge, which v2 removed.  The parameter is kept so existing
    callers (app.py passes get_market=core.get_market) keep working unchanged.
    """
    out: dict[str, pd.Series] = {}
    for key, (kind, _desc) in ALL_GAUGES.items():
        s = _read_gauge(key, kind, get_global=get_global, get_commodity=get_commodity)
        if s is not None and not s.empty:
            out[key] = s
    if not out:
        return pd.DataFrame()
    wide = pd.DataFrame(out).sort_index().ffill().dropna(how="all")
    return wide


def available_gauges(gauges: pd.DataFrame) -> list[str]:
    """Which gauges actually made it into the frame (for the UI / diagnostics)."""
    if gauges is None or gauges.empty:
        return []
    return [c for c in ALL_GAUGES if c in gauges.columns]


# ===================================================================
# CLASSIFY
# ===================================================================
def _g(z: dict, k: str) -> float | None:
    """One gauge's z for one day, or None when missing/NaN (never guessed)."""
    if k not in z:
        return None
    v = z.get(k)
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return None if np.isnan(f) else f


def _score_row(z: dict) -> dict:
    """Given one day's z-scores per gauge, return a score per regime.

    Every vote is a plain readable condition.  Missing gauges simply do not
    vote -- they are never treated as 0, which would be a silent assumption.
    """
    off = 0.0
    on = 0.0

    # ---- stress gauges: high = risk-off, low = risk-on -------------------
    for k in STRESS_UP:
        v = _g(z, k)
        if v is None:
            continue
        if v > HI:
            off += 1.0
        elif v < LO:
            on += 1.0

    # ---- growth / risk-appetite gauges: high = risk-on, low = risk-off ----
    for k in RISK_UP:
        v = _g(z, k)
        if v is None:
            continue
        if v > HI:
            on += 1.0
        elif v < LO:
            off += 1.0

    # ---- Goldilocks: quiet vol AND stable dollar AND firm growth ---------
    vix, move, dxy = _g(z, "VIX"), _g(z, "MOVE"), _g(z, "DXY")
    copper, brent = _g(z, "COPPER"), _g(z, "BRENT")
    gold = 0.0
    quiet = (vix is not None and vix < LO) and (move is not None and move < 0)
    stable = (dxy is not None and abs(dxy) < STABLE)
    firm = (copper is not None and copper > 0) or (brent is not None and brent > 0)
    if quiet and stable and firm:
        gold = 3.0
        if copper is not None and copper > HI:
            gold += 1.0

    return {"Risk-Off": off, "Risk-On": on, "Goldilocks": gold}


def contributions(z_row: dict) -> pd.DataFrame:
    """WHY is today what it is?  One row per gauge: its z, and how it voted.

    Feed this a single row of the z-score frame (z.loc[date].to_dict()).
    """
    rows = []
    for k, (_kind, desc) in ALL_GAUGES.items():
        v = _g(z_row, k)
        if v is None:
            continue
        if k in STRESS_UP:
            vote = "Risk-Off" if v > HI else ("Risk-On" if v < LO else "-")
        else:
            vote = "Risk-On" if v > HI else ("Risk-Off" if v < LO else "-")
        rows.append({"gauge": k, "z": round(v, 2), "votes": vote, "meaning": desc})
    if not rows:
        return pd.DataFrame(columns=["gauge", "z", "votes", "meaning"])
    return pd.DataFrame(rows).set_index("gauge")


def _raw_labels(gauges_z: pd.DataFrame, min_score: float = MIN_SCORE) -> pd.Series:
    """Per-day label BEFORE hysteresis (this is exactly what v1 returned)."""
    labels = []
    for _, row in gauges_z.iterrows():
        sc = _score_row(row.to_dict())
        best = max(sc, key=sc.get)
        labels.append(best if sc[best] >= min_score else "Neutral")
    return pd.Series(labels, index=gauges_z.index, name="regime")


def smooth(labels: pd.Series, min_days: int = DEFAULT_MIN_DAYS) -> pd.Series:
    """Anti-flicker.  A new label must hold for `min_days` consecutive days
    before it is confirmed; until then the last confirmed regime is carried
    forward.

    min_days <= 1 disables smoothing (returns the input unchanged), which is
    the v1 behaviour if you ever want to compare.
    """
    if labels is None or labels.empty or min_days is None or min_days <= 1:
        return labels
    out = []
    confirmed = labels.iloc[0]
    candidate = confirmed
    run = 0
    for lab in labels:
        if lab == confirmed:
            candidate, run = confirmed, 0
        elif lab == candidate:
            run += 1
            if run >= min_days:
                confirmed, run = candidate, 0
        else:
            candidate, run = lab, 1
            if min_days <= 1:
                confirmed = candidate
        out.append(confirmed)
    return pd.Series(out, index=labels.index, name="regime")


def classify(gauges_z: pd.DataFrame, min_score: float = MIN_SCORE,
             min_days: int | None = None) -> pd.Series:
    """Frame of daily z-scores (cols = gauges) -> daily regime label.

    min_days=None uses DEFAULT_MIN_DAYS (config.MRC_MIN_DAYS, default 5).
    Pass min_days=1 for the unsmoothed v1 behaviour.
    """
    if gauges_z is None or gauges_z.empty:
        return pd.Series(dtype=object)
    raw = _raw_labels(gauges_z, min_score=min_score)
    days = DEFAULT_MIN_DAYS if min_days is None else int(min_days)
    return smooth(raw, min_days=days)


def regime_series(get_global=None, get_market=None, get_commodity=None,
                  min_score: float = MIN_SCORE, min_days: int | None = None) -> pd.Series:
    """Convenience: assemble real gauges -> z-scores -> daily regime labels."""
    raw = assemble_gauges(get_global=get_global, get_market=get_market,
                          get_commodity=get_commodity)
    if raw.empty:
        return pd.Series(dtype=object)
    z = pd.DataFrame({c: _zseries(raw[c]) for c in raw.columns}).reindex(raw.index)
    return classify(z, min_score=min_score, min_days=min_days)


def regime_events(regimes: pd.Series, into: str = "Risk-Off") -> pd.Series:
    """Boolean flags on the days the regime FLIPS INTO `into` (for event_study).

    With v2's hysteresis these flips are far less noisy than in v1, which makes
    them a much better Event Study signal.
    """
    if regimes is None or regimes.empty:
        return pd.Series(dtype=bool)
    prev = regimes.shift(1)
    ev = (regimes == into) & (prev != into)
    return ev.fillna(False).astype(bool)


def regime_summary(regimes: pd.Series) -> pd.DataFrame:
    """Days spent in each regime + share of history -- a quick sanity table."""
    if regimes is None or regimes.empty:
        return pd.DataFrame(columns=["days", "share"])
    vc = regimes.value_counts()
    df = pd.DataFrame({"days": vc, "share": (vc / len(regimes)).round(3)})
    return df.reindex([r for r in REGIMES if r in df.index])


def regime_spells(regimes: pd.Series) -> pd.DataFrame:
    """Contiguous runs: start, end, regime, length.  Useful for eyeballing
    whether the classifier agrees with your memory of 2015 / 2020 / 2022."""
    if regimes is None or regimes.empty:
        return pd.DataFrame(columns=["start", "end", "regime", "days"])
    grp = (regimes != regimes.shift(1)).cumsum()
    rows = []
    for _, g in regimes.groupby(grp):
        rows.append({"start": g.index[0], "end": g.index[-1],
                     "regime": g.iloc[0], "days": len(g)})
    return pd.DataFrame(rows)


# ===================================================================
# SELF-TEST
# ===================================================================
def _demo():
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2016-01-01", periods=1600)
    n = len(days)

    # synthetic gauges with a deliberate stress window in the middle
    vix = pd.Series(18 + 3 * np.sin(np.arange(n) / 40), index=days)
    vix.iloc[700:760] += 25                                    # fear spike
    move = pd.Series(90 + rng.normal(0, 5, n), index=days)
    move.iloc[700:760] += 40
    dxy = pd.Series(95 + np.cumsum(rng.normal(0, 0.05, n)), index=days)
    dxy.iloc[700:760] += 6
    copper = pd.Series(4 + np.cumsum(rng.normal(0, 0.002, n)), index=days)
    copper.iloc[700:760] -= 0.6
    brent = pd.Series(70 + np.cumsum(rng.normal(0, 0.05, n)), index=days)
    brent.iloc[700:760] -= 12                                  # v2: oil weak too

    raw = pd.DataFrame({"VIX": vix, "MOVE": move, "DXY": dxy,
                        "COPPER": copper, "BRENT": brent})

    # keep z on raw's index (no dropna) so positional slices stay aligned
    z = pd.DataFrame({c: _zseries(raw[c], window=252) for c in raw.columns})
    z = z.reindex(raw.index)

    # --- unsmoothed (v1 behaviour) --------------------------------------
    reg_raw = classify(z, min_days=1)
    stress = reg_raw.iloc[700:720]
    assert (stress == "Risk-Off").mean() > 0.5, "stress onset should read Risk-Off"

    # --- smoothed (v2 default) ------------------------------------------
    reg = classify(z, min_days=5)
    assert len(reg) == len(reg_raw)

    # hysteresis must reduce the number of switches
    sw_raw = int((reg_raw != reg_raw.shift(1)).sum())
    sw_sm = int((reg != reg.shift(1)).sum())
    assert sw_sm <= sw_raw, "smoothing should not increase switches"

    ev = regime_events(reg_raw, "Risk-Off")
    assert ev.sum() >= 1

    summ = regime_summary(reg)
    assert summ["days"].sum() == len(reg)

    # EM_FX must be gone
    assert "EM_FX" not in ALL_GAUGES, "EM_FX should be removed in v2"

    # missing gauges must not vote (never silently treated as 0)
    partial = _score_row({"VIX": 2.0})
    assert partial["Risk-Off"] == 1.0 and partial["Risk-On"] == 0.0

    # a wide HY spread should push Risk-Off once that data exists
    withhy = _score_row({"VIX": 2.0, "HY_OAS": 2.0})
    assert withhy["Risk-Off"] == 2.0

    # why-table
    contrib = contributions({"VIX": 2.0, "COPPER": -1.5})
    assert contrib.loc["VIX", "votes"] == "Risk-Off"
    assert contrib.loc["COPPER", "votes"] == "Risk-Off"

    spells = regime_spells(reg)
    assert spells["days"].sum() == len(reg)

    print("mrc v2 self-test PASSED ->")
    print(f"   labelled {len(reg)} days")
    print(f"   regime switches: raw={sw_raw}  smoothed(5d)={sw_sm}  "
          f"({100 * (1 - sw_sm / max(sw_raw, 1)):.0f}% less flicker)")
    print(f"   raw      : {dict(reg_raw.value_counts())}")
    print(f"   smoothed : {dict(reg.value_counts())}")
    print(f"   risk-off flips (raw) = {int(ev.sum())}")


def _live(min_days=None, why=False):
    if core is None:
        print("[mrc] core not importable -- run inside the EMDASH folder.")
        return
    core.init_db()
    raw = assemble_gauges()
    if raw.empty:
        print("[mrc] no gauges in warehouse -- run ingest.py first.")
        return

    have = available_gauges(raw)
    missing = [g for g in ALL_GAUGES if g not in have]
    print(f"[mrc] gauges in use ({len(have)}): {', '.join(have)}")
    if missing:
        print(f"[mrc] not in warehouse  : {', '.join(missing)}")
        print("      (optional gauges activate automatically once ingested)")

    z = pd.DataFrame({c: _zseries(raw[c]) for c in raw.columns}).reindex(raw.index)
    days = DEFAULT_MIN_DAYS if min_days is None else int(min_days)
    reg = classify(z, min_days=days)
    reg_raw = classify(z, min_days=1)

    print(f"\n[mrc] coverage: {reg.index.min().date()} -> {reg.index.max().date()}"
          f"   (hysteresis = {days} day{'s' if days != 1 else ''})")
    print(regime_summary(reg))

    sw_raw = int((reg_raw != reg_raw.shift(1)).sum())
    sw_sm = int((reg != reg.shift(1)).sum())
    print(f"\n[mrc] regime switches: raw={sw_raw}  smoothed={sw_sm}")

    print("\n[mrc] longest spells:")
    sp = regime_spells(reg).sort_values("days", ascending=False).head(8)
    for _, r in sp.iterrows():
        print(f"   {str(r['start'])[:10]} -> {str(r['end'])[:10]}  "
              f"{r['regime']:<11} {int(r['days']):>5}d")

    print("\n[mrc] latest 5 days:")
    print(reg.tail(5).to_string())

    if why:
        last = z.index[-1]
        print(f"\n[mrc] WHY is {str(last)[:10]} = {reg.iloc[-1]}?")
        print(contributions(z.loc[last].to_dict()).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="classify the real warehouse")
    ap.add_argument("--days", type=int, default=None,
                    help="hysteresis: days a new regime must hold (default 5, 1 = off)")
    ap.add_argument("--why", action="store_true",
                    help="with --live: explain the latest day gauge by gauge")
    args = ap.parse_args()
    if args.live:
        _live(min_days=args.days, why=args.why)
    else:
        _demo()
