"""
EMDASH :: event_study.py   (v3)

THE "WHAT HAPPENED NEXT?" ENGINE. No AI, no black-box backtester -- just pandas
.shift() and averages you can re-derive by hand and explain to a PM.

v3 adds (v1/v2 all still work unchanged -- fully backward-compatible):
  - empirical_pvalue()      -> honest significance for OVERLAPPING / non-normal
                               returns. Instead of trusting a t-stat (which
                               assumes independent, normal observations -- false
                               for FX and for events whose windows overlap), we
                               RESHUFFLE: draw the same number of random "fake
                               event" dates thousands of times, and ask how often
                               a random draw beat the real event's mean. p = 0.03
                               means "only 3% of random draws did this well" ->
                               the event really is unusual. This is the same idea
                               as a bootstrap / Monte-Carlo permutation test.
  - outcome_distribution()  -> the RAW list of per-event outcomes at one horizon,
                               plus the baseline's raw outcomes, so app.py can
                               draw a histogram (the spread the mean hides).
  - event_study() now also carries n_events, and event_dates() lists the actual
    dates (for the "export the event list" button).

v2 recap (unchanged):
  - event_paths()    -> each event's own cumulative path (for spaghetti + band)
  - path_band()      -> median + 25/75 percentile bands from those paths
  - cross_sectional()-> one signal vs MANY targets, ranked by excess-vs-baseline

PURE functions, NO database, NO plotting (same contract as signals.py).
Run:  python event_study.py     # self-test on synthetic data
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 20, 60)
RULES = ("above", "below", "cross_above", "cross_below", "z_above", "z_below")


# ===================================================================
# EVENTS
# ===================================================================
def make_events(signal, rule="cross_above", threshold=0.0, window=20):
    s = pd.to_numeric(signal, errors="coerce").dropna()
    if s.empty:
        return pd.Series(dtype=bool)
    if rule == "above":
        ev = s > threshold
    elif rule == "below":
        ev = s < threshold
    elif rule == "cross_above":
        ev = (s > threshold) & (s.shift(1) <= threshold)
    elif rule == "cross_below":
        ev = (s < threshold) & (s.shift(1) >= threshold)
    elif rule in ("z_above", "z_below"):
        mu = s.rolling(window, min_periods=max(3, window // 2)).mean()
        sd = s.rolling(window, min_periods=max(3, window // 2)).std(ddof=0)
        z = (s - mu) / sd.replace(0, np.nan)
        ev = z > threshold if rule == "z_above" else z < threshold
    else:
        raise ValueError(f"unknown rule '{rule}'. valid: {RULES}")
    return ev.fillna(False).astype(bool)


def event_dates(signal, rule="cross_above", threshold=0.0, window=20) -> pd.DatetimeIndex:
    "The actual dates the signal fired -- for the 'export event list' button."
    ev = make_events(signal, rule=rule, threshold=threshold, window=window)
    if ev is None or ev.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(ev.index[ev.values])


# ===================================================================
# FORWARD MEASUREMENT (look-ahead-safe)
# ===================================================================
def _forward_value(vals, p, h, kind):
    q = p + h
    if q >= len(vals) or p >= len(vals):
        return np.nan
    base, fwd = vals[p], vals[q]
    if kind == "diff":
        return float(fwd - base)
    if base == 0 or np.isnan(base) or np.isnan(fwd):
        return np.nan
    return float(fwd / base - 1.0)


def _snap_forward(target_index, event_dates):
    return target_index.searchsorted(event_dates, side="left")


def study(target, events, horizons=DEFAULT_HORIZONS, kind="pct"):
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    horizons = tuple(int(h) for h in horizons)
    if tgt.empty or events is None or events.empty:
        return _empty_summary(horizons), pd.DataFrame()
    idx, vals = tgt.index, tgt.values.astype(float)
    ev_dates = pd.DatetimeIndex(events.index[events.fillna(False).astype(bool)])
    if len(ev_dates) == 0:
        return _empty_summary(horizons), pd.DataFrame()
    positions = _snap_forward(idx, ev_dates)
    records = []
    for d, p in zip(ev_dates, positions):
        if p >= len(vals):
            continue
        rec = {"event_date": d, "aligned_date": idx[p]}
        for h in horizons:
            rec[f"h{h}"] = _forward_value(vals, p, h, kind)
        records.append(rec)
    detail = pd.DataFrame(records)
    return _summarise(detail, horizons), detail


def baseline(target, horizons=DEFAULT_HORIZONS, kind="pct"):
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    horizons = tuple(int(h) for h in horizons)
    if tgt.empty:
        return _empty_summary(horizons)
    vals = tgt.values.astype(float)
    records = [{f"h{h}": _forward_value(vals, p, h, kind) for h in horizons}
               for p in range(len(vals))]
    return _summarise(pd.DataFrame(records), horizons)


# ===================================================================
# PATHS (spaghetti + dispersion band)
# ===================================================================
def event_paths(target, events, max_h=60, kind="pct") -> pd.DataFrame:
    "One column per event; each is that event's cumulative move day0..max_h."
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    if tgt.empty or events is None or events.empty:
        return pd.DataFrame()
    idx, vals = tgt.index, tgt.values.astype(float)
    ev_dates = pd.DatetimeIndex(events.index[events.fillna(False).astype(bool)])
    positions = _snap_forward(idx, ev_dates)
    cols = {}
    for d, p in zip(ev_dates, positions):
        if p >= len(vals):
            continue
        base = vals[p]
        seg = vals[p:p + max_h + 1]
        if kind == "diff":
            path = seg - base
        else:
            if base == 0 or np.isnan(base):
                continue
            path = seg / base - 1.0
        cols[str(d.date())] = pd.Series(path, index=range(len(path)))
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols)


def path_band(paths: pd.DataFrame, lo=25, hi=75):
    if paths is None or paths.empty:
        e = pd.Series(dtype=float)
        return e, e, e
    return (paths.median(axis=1), paths.quantile(lo / 100.0, axis=1),
            paths.quantile(hi / 100.0, axis=1))


def average_path(target, events, max_h=60, kind="pct") -> pd.Series:
    paths = event_paths(target, events, max_h, kind)
    return paths.mean(axis=1) if not paths.empty else pd.Series(dtype=float)


def baseline_path(target, max_h=60, kind="pct") -> pd.Series:
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    if tgt.empty:
        return pd.Series(dtype=float)
    vals = tgt.values.astype(float)
    paths = []
    for p in range(len(vals)):
        base = vals[p]
        seg = vals[p:p + max_h + 1]
        if len(seg) < max_h + 1:
            continue
        if kind == "diff":
            paths.append(pd.Series((seg - base), index=range(len(seg))))
        elif base and not np.isnan(base):
            paths.append(pd.Series((seg / base - 1.0), index=range(len(seg))))
    if not paths:
        return pd.Series(dtype=float)
    return pd.concat(paths, axis=1).mean(axis=1)


# ===================================================================
# v3 :: HONEST SIGNIFICANCE + DISTRIBUTION
# ===================================================================
def outcome_distribution(target, events, horizon=20, kind="pct"):
    """Raw per-event outcomes at ONE horizon + the baseline (all-day) outcomes.
    Returns (event_outcomes: np.ndarray, base_outcomes: np.ndarray) so app.py can
    draw two overlaid histograms -- the spread the single mean hides."""
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    if tgt.empty:
        return np.array([]), np.array([])
    idx, vals = tgt.index, tgt.values.astype(float)
    # baseline outcomes: every day
    base = np.array([_forward_value(vals, p, horizon, kind) for p in range(len(vals))],
                    dtype=float)
    base = base[~np.isnan(base)]
    # event outcomes
    ev_out = np.array([])
    if events is not None and not events.empty:
        ev_dates = pd.DatetimeIndex(events.index[events.fillna(False).astype(bool)])
        positions = _snap_forward(idx, ev_dates)
        ev_out = np.array([_forward_value(vals, int(p), horizon, kind)
                           for p in positions if int(p) < len(vals)], dtype=float)
        ev_out = ev_out[~np.isnan(ev_out)]
    return ev_out, base


def empirical_pvalue(target, events, horizon=20, kind="pct", n_draws=2000, seed=7):
    """Permutation / bootstrap significance for the event MEAN.

    Why not a t-stat? A t-stat assumes each observation is independent and roughly
    normal. Event windows OVERLAP (they share future days) and FX returns are fat-
    tailed -- both break that assumption and INFLATE the t-stat. So instead we ask
    empirically: if I picked the SAME NUMBER of dates at random (no signal at all),
    thousands of times, how often would random luck produce a mean this extreme?

    Returns dict:
      n            events actually measured
      event_mean   mean outcome after the real events
      base_mean    mean outcome on any day (baseline)
      excess       event_mean - base_mean  (what we call "Excess vs baseline")
      p_two_sided  fraction of random draws with |mean-base| >= |event-base|
      p_one_sided  fraction of random draws at least as extreme in the SAME direction
      pct_beaten   1 - p_one_sided  (plain English: "beat random X% of the time")
    """
    out = {"n": 0, "event_mean": np.nan, "base_mean": np.nan, "excess": np.nan,
           "p_two_sided": np.nan, "p_one_sided": np.nan, "pct_beaten": np.nan}
    ev_out, base = outcome_distribution(target, events, horizon, kind)
    n = int(len(ev_out))
    if n == 0 or len(base) < n + 5:
        return out
    event_mean = float(np.mean(ev_out))
    base_mean = float(np.mean(base))
    excess = event_mean - base_mean
    rng = np.random.default_rng(seed)
    # each draw: mean of n randomly-chosen baseline outcomes
    draws = np.array([rng.choice(base, size=n, replace=False).mean()
                      for _ in range(int(n_draws))], dtype=float)
    diffs = draws - base_mean
    obs = excess
    p_two = float(np.mean(np.abs(diffs) >= abs(obs)))
    if obs >= 0:
        p_one = float(np.mean(diffs >= obs))
    else:
        p_one = float(np.mean(diffs <= obs))
    out.update({"n": n, "event_mean": event_mean, "base_mean": base_mean,
                "excess": excess, "p_two_sided": p_two, "p_one_sided": p_one,
                "pct_beaten": 1.0 - p_one})
    return out


# ===================================================================
# RESULT OBJECT
# ===================================================================
@dataclass
class EventStudyResult:
    summary: pd.DataFrame
    baseline: pd.DataFrame
    detail: pd.DataFrame
    path: pd.Series
    base_path: pd.Series
    paths: pd.DataFrame = field(default_factory=pd.DataFrame)
    n_events: int = 0
    kind: str = "pct"
    horizons: tuple = field(default_factory=lambda: DEFAULT_HORIZONS)

    def compare(self) -> pd.DataFrame:
        "The money table: per horizon, event mean vs baseline + excess + hit rates."
        rows = []
        for h in self.horizons:
            s = self.summary.loc[h] if h in self.summary.index else None
            b = self.baseline.loc[h] if h in self.baseline.index else None
            mean = float(s["mean"]) if s is not None else np.nan
            bmean = float(b["mean"]) if b is not None else np.nan
            rows.append({
                "n_events": int(s["n"]) if s is not None else 0,
                "mean": mean, "base_mean": bmean, "edge": mean - bmean,
                "hit_rate": float(s["hit_rate"]) if s is not None else np.nan,
                "base_hit_rate": float(b["hit_rate"]) if b is not None else np.nan,
                "median": float(s["median"]) if s is not None else np.nan,
                "t_stat": float(s["t_stat"]) if s is not None else np.nan,
            })
        return pd.DataFrame(rows, index=list(self.horizons))

    def event_list(self) -> pd.DataFrame:
        "Per-event detail for export (dates + each horizon's outcome)."
        return self.detail.copy()


def event_study(target, signal, rule="cross_above", threshold=0.0, window=20,
                horizons=DEFAULT_HORIZONS, kind="pct") -> EventStudyResult:
    horizons = tuple(int(h) for h in horizons)
    events = make_events(signal, rule=rule, threshold=threshold, window=window)
    summary, detail = study(target, events, horizons, kind)
    base = baseline(target, horizons, kind)
    max_h = max(horizons) if horizons else 60
    paths = event_paths(target, events, max_h, kind)
    return EventStudyResult(
        summary=summary, baseline=base, detail=detail,
        path=(paths.mean(axis=1) if not paths.empty else pd.Series(dtype=float)),
        base_path=baseline_path(target, max_h, kind),
        paths=paths, n_events=int(len(detail)), kind=kind, horizons=horizons)


# ===================================================================
# CROSS-SECTION (one signal, many targets)
# ===================================================================
def cross_sectional(signal, targets: dict, rule="cross_above", threshold=0.0,
                    window=20, horizon=20, kind="pct") -> pd.DataFrame:
    "One signal, many targets. One row per target (n/mean/base/excess/hit), "
    "sorted by excess -- a ranked bar of 'who moved most when X fired'."
    events = make_events(signal, rule=rule, threshold=threshold, window=window)
    rows = []
    for label, tgt in targets.items():
        if tgt is None or len(pd.to_numeric(tgt, errors="coerce").dropna()) < horizon + 5:
            continue
        summ, _ = study(tgt, events, (horizon,), kind)
        base = baseline(tgt, (horizon,), kind)
        n = int(summ.loc[horizon, "n"])
        if n == 0:
            continue
        mean = float(summ.loc[horizon, "mean"])
        bmean = float(base.loc[horizon, "mean"])
        rows.append({"target": label, "n": n, "mean": mean, "base_mean": bmean,
                     "edge": mean - bmean, "hit_rate": float(summ.loc[horizon, "hit_rate"]),
                     "base_hit_rate": float(base.loc[horizon, "hit_rate"])})
    if not rows:
        return pd.DataFrame(columns=["target", "n", "mean", "base_mean", "edge",
                                     "hit_rate", "base_hit_rate"]).set_index("target")
    return pd.DataFrame(rows).set_index("target").sort_values("edge", ascending=False)


# ===================================================================
# SUMMARY HELPERS
# ===================================================================
def _summarise(detail, horizons):
    rows = []
    for h in horizons:
        col = f"h{h}"
        vals = detail[col].dropna() if (not detail.empty and col in detail) else pd.Series(dtype=float)
        n = int(len(vals))
        if n == 0:
            rows.append(_blank_row(h)); continue
        mean = float(vals.mean())
        std = float(vals.std(ddof=1)) if n > 1 else 0.0
        t = float(mean / (std / np.sqrt(n))) if (std > 0 and n > 1) else np.nan
        rows.append({"horizon": h, "n": n, "mean": mean, "median": float(vals.median()),
                     "hit_rate": float((vals > 0).mean()), "std": std,
                     "best": float(vals.max()), "worst": float(vals.min()), "t_stat": t})
    return pd.DataFrame(rows).set_index("horizon")


def _blank_row(h):
    return {"horizon": h, "n": 0, "mean": np.nan, "median": np.nan, "hit_rate": np.nan,
            "std": np.nan, "best": np.nan, "worst": np.nan, "t_stat": np.nan}


def _empty_summary(horizons):
    return pd.DataFrame([_blank_row(h) for h in horizons]).set_index("horizon")


# ===================================================================
# SELF-TEST
# ===================================================================
def _demo():
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2015-01-01", periods=2500)
    fx = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.006, len(days)))), index=days)
    months = pd.date_range("2015-01-31", periods=120, freq="ME")
    sig = pd.Series(rng.normal(20, 8, len(months)), index=months)
    ev = make_events(sig, "cross_above", 30)
    for d in months[ev.values]:
        p = days.searchsorted(d)
        if p + 20 < len(fx):
            fx.iloc[p:] *= 1.03
    res = event_study(fx, sig, "cross_above", 30, horizons=(1, 5, 20, 60))
    edge20 = res.summary.loc[20, "mean"] - res.baseline.loc[20, "mean"]
    assert res.n_events > 0 and edge20 > 0.005 and res.paths.shape[0] == 61
    med, lo, hi = path_band(res.paths)
    assert (hi >= lo).all()
    # v3: p-value + distribution
    pv = empirical_pvalue(fx, ev, horizon=20, n_draws=500)
    assert pv["n"] > 0 and 0.0 <= pv["p_one_sided"] <= 1.0
    ev_out, base_out = outcome_distribution(fx, ev, horizon=20)
    assert len(ev_out) > 0 and len(base_out) > 0
    cmp = res.compare()
    assert "edge" in cmp.columns and len(res.event_list()) == res.n_events
    flat = pd.Series(100 + np.zeros(len(days)), index=days)
    xs = cross_sectional(sig, {"REACT": fx, "FLAT": flat}, "cross_above", 30, horizon=20)
    assert "REACT" in xs.index
    print("event_study v3 self-test PASSED ->",
          f"events={res.n_events} edge20={edge20*100:.2f}% "
          f"p1={pv['p_one_sided']:.3f} beat={pv['pct_beaten']*100:.0f}% xs={len(xs)}")


if __name__ == "__main__":
    _demo()
