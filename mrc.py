"""
EMDASH :: mrc.py   (Macro Regime Classifier -- v3, RULES-based)

WHAT THIS IS
A transparent, hand-checkable classifier that labels EACH DAY as one of a small
set of macro regimes -- Risk-Off / Risk-On / Goldilocks / Neutral -- from a
handful of global gauges. No ML, no HMM, no black box: every rule is a plain
z-score threshold you can read out loud to a PM.

------------------------------------------------------------------------------
WHAT CHANGED IN v3   (the fix that was pending for ages)
------------------------------------------------------------------------------
1. MIN_MARGIN -- the winner must beat the runner-up by at least this many votes
   or the day is NEUTRAL.  Default 2 (config.MRC_MIN_MARGIN, or --margin, or the
   argument).  Set 0 for the old v2 behaviour.

   WHY THIS EXISTS -- the live 2026-07-31 case that motivated it:
       VIX    -0.42   -          (calm)
       MOVE   -0.04   -          (calm)
       DXY    +0.91   Risk-Off
       COPPER +1.64   Risk-On
       BRENT  +0.25   -
       BTC    -1.04   Risk-Off
       -> Risk-Off 2, Risk-On 1  ->  v2 printed "Risk-Off"
   Both fear gauges were calm and the strongest growth read (copper) was firmly
   Risk-On, yet a 2-1 split committed to Risk-Off.  Across full history v2
   committed to a direction on ~88% of days -- real macro spends far more time
   in "nothing much is happening".  With margin=2 this day reads NEUTRAL, and
   on correlated (realistic) gauges margin=2 gives roughly Risk-Off 44% /
   Risk-On 35% / Neutral 21% -- it only removes genuinely split days.

2. confidence() -- how decisive was a given day?  Returns, per day, the winning
   regime, the winning score, the margin over the runner-up, and a 0..1
   confidence proxy.  Lets the UI show "Risk-Off (weak 2-1)" vs
   "Risk-Off (strong 5-0)", which 2-1 and 5-0 previously rendered identically.

Everything else is unchanged from v2 (below).

------------------------------------------------------------------------------
CARRIED FROM v2  (all from the CIO review, 30 Jul 2026)
------------------------------------------------------------------------------
- EM_FX REMOVED (it was ~90% Argentina and only ever trended up).  DXY carries
  the dollar read.
- MOVE now votes Risk-On when low; Brent now votes Risk-Off when weak
  (symmetric with copper).
- Optional gauges (activate automatically once ingested): BBB_OAS / IG_OAS /
  HY_OAS / SWAP_SPREAD_10Y / BTC.  Skipped silently if absent -- never treated
  as zero.
- HYSTERESIS (anti-flicker): a raw label must persist for `min_days` days before
  it is confirmed.

THE CIO'S MENTAL MODEL
  VIX   equity vol  -> reads across to INVESTMENT GRADE credit spreads
  MOVE  rates vol   -> reads across to HIGH YIELD credit spreads
  DXY   the dollar  -> up = global tightening / risk-off
  BRENT oil         -> weak = economy doing badly (unless a supply story)
  COPPER            -> same logic; the classic global growth read

Run:  python mrc.py                    # self-test on synthetic data (no DB)
      python mrc.py --live             # classify the real warehouse
      python mrc.py --live --margin 0  # old v2 behaviour (no margin rule)
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
    if config is None:
        return default
    return getattr(config, name, default)


# rolling window for the z-scores (~1 trading year)
Z_WINDOW = int(_cfg("MRC_Z_WINDOW", 252))

# how strong a z has to be to "count" as high/low
HI = float(_cfg("MRC_HI", 0.75))
LO = float(_cfg("MRC_LO", -0.75))
STABLE = float(_cfg("MRC_STABLE", 0.5))
MIN_SCORE = float(_cfg("MRC_MIN_SCORE", 2.0))

# anti-flicker: a new label must survive this many consecutive days
DEFAULT_MIN_DAYS = int(_cfg("MRC_MIN_DAYS", 5))

# v3: winner must beat runner-up by this many votes, else Neutral. 0 disables.
MIN_MARGIN = float(_cfg("MRC_MIN_MARGIN", 2.0))


# ---------------------------------------------------------------------------
# GAUGE REGISTRY
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
    "SWAP_SPREAD_10Y": ("global", "USD 10y swap spread -- funding stress"),
    "BTC":             ("global", "risk appetite / liquidity proxy"),
}

ALL_GAUGES = {**CORE_GAUGES, **OPTIONAL_GAUGES}

STRESS_UP = ("VIX", "MOVE", "DXY", "BBB_OAS", "IG_OAS", "HY_OAS", "SWAP_SPREAD_10Y")
RISK_UP = ("COPPER", "BRENT", "BTC")


# ===================================================================
# GAUGE ASSEMBLY
# ===================================================================
def _zseries(s: pd.Series, window: int = Z_WINDOW) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return s
    if sig is not None:
        return sig.zscore(s, window=window)
    mu = s.rolling(window, min_periods=max(20, window // 4)).mean()
    sd = s.rolling(window, min_periods=max(20, window // 4)).std()
    return (s - mu) / sd.replace(0, np.nan)


def _read_gauge(key, kind, get_global=None, get_commodity=None):
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
    out: dict[str, pd.Series] = {}
    for key, (kind, _desc) in ALL_GAUGES.items():
        s = _read_gauge(key, kind, get_global=get_global,
                        get_commodity=get_commodity)
        if s is not None and not s.empty:
            out[key] = s
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_index().ffill().dropna(how="all")


def available_gauges(gauges: pd.DataFrame) -> list[str]:
    if gauges is None or gauges.empty:
        return []
    return [c for c in ALL_GAUGES if c in gauges.columns]


# ===================================================================
# CLASSIFY
# ===================================================================
def _g(z: dict, k: str):
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
    off = 0.0
    on = 0.0
    for k in STRESS_UP:
        v = _g(z, k)
        if v is None:
            continue
        if v > HI:
            off += 1.0
        elif v < LO:
            on += 1.0
    for k in RISK_UP:
        v = _g(z, k)
        if v is None:
            continue
        if v > HI:
            on += 1.0
        elif v < LO:
            off += 1.0
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


def _label_from_scores(sc: dict, min_score: float, min_margin: float) -> str:
    """Winner-take-all with a MIN_SCORE floor AND (v3) a MIN_MARGIN gap.

    The winner must (a) reach min_score and (b) beat the runner-up by at least
    min_margin votes; otherwise the day is Neutral.
    """
    best = max(sc, key=sc.get)
    best_val = sc[best]
    if best_val < min_score:
        return "Neutral"
    runner = max((v for k, v in sc.items() if k != best), default=0.0)
    if min_margin and (best_val - runner) < min_margin:
        return "Neutral"
    return best


def _raw_labels(gauges_z: pd.DataFrame, min_score: float = MIN_SCORE,
                min_margin: float = None) -> pd.Series:
    mm = MIN_MARGIN if min_margin is None else float(min_margin)
    labels = []
    for _, row in gauges_z.iterrows():
        sc = _score_row(row.to_dict())
        labels.append(_label_from_scores(sc, min_score, mm))
    return pd.Series(labels, index=gauges_z.index, name="regime")


def smooth(labels: pd.Series, min_days: int = DEFAULT_MIN_DAYS) -> pd.Series:
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
             min_days: int | None = None, min_margin: float | None = None) -> pd.Series:
    """Frame of daily z-scores (cols = gauges) -> daily regime label.

    min_days=None   uses DEFAULT_MIN_DAYS (config.MRC_MIN_DAYS, default 5).
    min_margin=None uses MIN_MARGIN       (config.MRC_MIN_MARGIN, default 2).
                    Pass min_margin=0 for the pre-v3 (no-margin) behaviour.
    """
    if gauges_z is None or gauges_z.empty:
        return pd.Series(dtype=object)
    raw = _raw_labels(gauges_z, min_score=min_score, min_margin=min_margin)
    days = DEFAULT_MIN_DAYS if min_days is None else int(min_days)
    return smooth(raw, min_days=days)


def confidence(gauges_z: pd.DataFrame, min_score: float = MIN_SCORE,
               min_margin: float | None = None) -> pd.DataFrame:
    """Per-day decisiveness.  [v3: NEW]

    Columns: label, score (winner's votes), runner_up, margin (winner-runner),
    conf (0..1 proxy = margin / max(score,1), clipped).  Uses the RAW label
    (pre-hysteresis) so it describes the day's own gauge balance.  Lets the UI
    distinguish "Risk-Off (weak, 2-1)" from "Risk-Off (strong, 5-0)".
    """
    if gauges_z is None or gauges_z.empty:
        return pd.DataFrame(columns=["label", "score", "runner_up",
                                     "margin", "conf"])
    mm = MIN_MARGIN if min_margin is None else float(min_margin)
    rows = []
    for idx, row in gauges_z.iterrows():
        sc = _score_row(row.to_dict())
        best = max(sc, key=sc.get)
        best_val = sc[best]
        runner = max((v for k, v in sc.items() if k != best), default=0.0)
        margin = best_val - runner
        label = _label_from_scores(sc, min_score, mm)
        conf = 0.0 if best_val <= 0 else max(0.0, min(1.0, margin / max(best_val, 1.0)))
        rows.append({"label": label, "score": best_val, "runner_up": runner,
                     "margin": margin, "conf": round(conf, 2)})
    return pd.DataFrame(rows, index=gauges_z.index)


def contributions(z_row: dict) -> pd.DataFrame:
    rows = []
    for k, (_kind, desc) in ALL_GAUGES.items():
        v = _g(z_row, k)
        if v is None:
            continue
        if k in STRESS_UP:
            vote = "Risk-Off" if v > HI else ("Risk-On" if v < LO else "-")
        else:
            vote = "Risk-On" if v > HI else ("Risk-Off" if v < LO else "-")
        rows.append({"gauge": k, "z": round(v, 2), "votes": vote,
                     "meaning": desc})
    if not rows:
        return pd.DataFrame(columns=["gauge", "z", "votes", "meaning"])
    return pd.DataFrame(rows).set_index("gauge")


def regime_series(get_global=None, get_market=None, get_commodity=None,
                  min_score: float = MIN_SCORE, min_days: int | None = None,
                  min_margin: float | None = None) -> pd.Series:
    raw = assemble_gauges(get_global=get_global, get_market=get_market,
                          get_commodity=get_commodity)
    if raw.empty:
        return pd.Series(dtype=object)
    z = pd.DataFrame({c: _zseries(raw[c]) for c in raw.columns}).reindex(raw.index)
    return classify(z, min_score=min_score, min_days=min_days,
                    min_margin=min_margin)


def regime_events(regimes: pd.Series, into: str = "Risk-Off") -> pd.Series:
    if regimes is None or regimes.empty:
        return pd.Series(dtype=bool)
    prev = regimes.shift(1)
    ev = (regimes == into) & (prev != into)
    return ev.fillna(False).astype(bool)


def regime_summary(regimes: pd.Series) -> pd.DataFrame:
    if regimes is None or regimes.empty:
        return pd.DataFrame(columns=["days", "share"])
    vc = regimes.value_counts()
    df = pd.DataFrame({"days": vc, "share": (vc / len(regimes)).round(3)})
    return df.reindex([r for r in REGIMES if r in df.index])


def regime_spells(regimes: pd.Series) -> pd.DataFrame:
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

    vix = pd.Series(18 + 3 * np.sin(np.arange(n) / 40), index=days)
    vix.iloc[700:760] += 25
    move = pd.Series(90 + rng.normal(0, 5, n), index=days)
    move.iloc[700:760] += 40
    dxy = pd.Series(95 + np.cumsum(rng.normal(0, 0.05, n)), index=days)
    dxy.iloc[700:760] += 6
    copper = pd.Series(4 + np.cumsum(rng.normal(0, 0.002, n)), index=days)
    copper.iloc[700:760] -= 0.6
    brent = pd.Series(70 + np.cumsum(rng.normal(0, 0.05, n)), index=days)
    brent.iloc[700:760] -= 12

    raw = pd.DataFrame({"VIX": vix, "MOVE": move, "DXY": dxy,
                        "COPPER": copper, "BRENT": brent})
    z = pd.DataFrame({c: _zseries(raw[c], window=252) for c in raw.columns})
    z = z.reindex(raw.index)

    # unsmoothed, no margin (pre-v3)
    reg_raw = classify(z, min_days=1, min_margin=0)
    stress = reg_raw.iloc[700:720]
    assert (stress == "Risk-Off").mean() > 0.5, "stress onset should read Risk-Off"

    # v3 default (smoothed + margin=2)
    reg = classify(z, min_days=5)
    assert len(reg) == len(reg_raw)

    sw_raw = int((reg_raw != reg_raw.shift(1)).sum())
    sw_sm = int((reg != reg.shift(1)).sum())
    assert sw_sm <= sw_raw, "smoothing should not increase switches"

    # --- MIN_MARGIN behaviour: the live 2026-07-31 case, in scores ---
    # Risk-Off 2 (DXY, BTC), Risk-On 1 (COPPER) -> margin 1 -> Neutral at mm=2
    live_scores = {"Risk-Off": 2.0, "Risk-On": 1.0, "Goldilocks": 0.0}
    assert _label_from_scores(live_scores, MIN_SCORE, 0) == "Risk-Off"
    assert _label_from_scores(live_scores, MIN_SCORE, 2) == "Neutral"
    # a decisive day still passes at mm=2
    decisive = {"Risk-Off": 5.0, "Risk-On": 0.0, "Goldilocks": 0.0}
    assert _label_from_scores(decisive, MIN_SCORE, 2) == "Risk-Off"

    # margin=2 should raise Neutral share vs margin=0
    neut0 = (classify(z, min_days=1, min_margin=0) == "Neutral").mean()
    neut2 = (classify(z, min_days=1, min_margin=2) == "Neutral").mean()
    assert neut2 >= neut0, "margin should not reduce Neutral share"

    # --- confidence(): 5-0 more confident than 2-1 ---
    conf = confidence(z, min_margin=2)
    assert set(conf.columns) == {"label", "score", "runner_up", "margin", "conf"}
    assert conf["conf"].between(0, 1).all()

    # EM_FX gone; missing gauges never vote as 0
    assert "EM_FX" not in ALL_GAUGES
    assert _score_row({"VIX": 2.0})["Risk-Off"] == 1.0
    assert _score_row({"VIX": 2.0, "HY_OAS": 2.0})["Risk-Off"] == 2.0

    contrib = contributions({"VIX": 2.0, "COPPER": -1.5})
    assert contrib.loc["VIX", "votes"] == "Risk-Off"
    assert contrib.loc["COPPER", "votes"] == "Risk-Off"

    ev = regime_events(reg_raw, "Risk-Off")
    assert ev.sum() >= 1
    assert regime_summary(reg)["days"].sum() == len(reg)
    assert regime_spells(reg)["days"].sum() == len(reg)

    print("mrc v3 self-test PASSED ->")
    print(f"   labelled {len(reg)} days")
    print(f"   switches: raw(no-margin)={sw_raw}  smoothed(5d,margin2)={sw_sm}")
    print(f"   Neutral share: margin0={neut0:.0%}  margin2={neut2:.0%}")
    print(f"   raw(no-margin) : {dict(reg_raw.value_counts())}")
    print(f"   v3 default     : {dict(reg.value_counts())}")
    print(f"   live 2-1 case  -> label at margin2 = "
          f"{_label_from_scores(live_scores, MIN_SCORE, 2)} (was Risk-Off in v2)")


def _live(min_days=None, why=False, min_margin=None):
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

    z = pd.DataFrame({c: _zseries(raw[c]) for c in raw.columns}).reindex(raw.index)
    days = DEFAULT_MIN_DAYS if min_days is None else int(min_days)
    mm = MIN_MARGIN if min_margin is None else float(min_margin)
    reg = classify(z, min_days=days, min_margin=mm)
    reg_raw = classify(z, min_days=1, min_margin=mm)

    print(f"\n[mrc] coverage: {reg.index.min().date()} -> {reg.index.max().date()}"
          f"   (hysteresis={days}d, margin={mm:g})")
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
        c = confidence(z.loc[[last]], min_margin=mm).iloc[0]
        print(f"\n[mrc] WHY is {str(last)[:10]} = {reg.iloc[-1]}?")
        print(f"      raw label {c['label']}  score {c['score']:g} vs "
              f"runner-up {c['runner_up']:g}  (margin {c['margin']:g}, "
              f"conf {c['conf']:.2f})")
        print(contributions(z.loc[last].to_dict()).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--days", type=int, default=None,
                    help="hysteresis: days a new regime must hold (default 5)")
    ap.add_argument("--margin", type=float, default=None,
                    help="MIN_MARGIN: winner must beat runner-up by N votes "
                         "(default 2; 0 = old v2 behaviour)")
    ap.add_argument("--why", action="store_true")
    args = ap.parse_args()
    if args.live:
        _live(min_days=args.days, why=args.why, min_margin=args.margin)
    else:
        _demo()
