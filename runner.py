"""
EMDASH :: runner.py   (v8.2)
===================================================================
BACKGROUND PULL RUNNER + Pull panels for the SQLite Store tab.

v8.2
  * Optional "Trim older rows to timeframe" (opt-in checkbox, default OFF).
    When ticked WITH a non-full timeframe, after the pull ingest deletes rows
    older than the timeframe cutoff -- scoped per source, so trimming e.g.
    Risk gauges never touches FRED credit spreads that share global_market.
    Passed to ingest via EMDASH_MARKET_TRIM. Macro/predmarkets never trimmed.
v8.1
  * Timeframe presets 10y/20y/50y; removed "Pull everything"; persistent ticks.
===================================================================
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import datetime as dt

from dash import dcc, html, Input, Output, State, no_update, callback_context

import config

P = config.PALETTE
ROOT = config.ROOT
PRUNE_DAYS = int(getattr(config, "NEWS_PRUNE_DAYS", 90))
BORANGE = getattr(config, "BLOOMBERG_ORANGE", "#FFA028")
_TF_PATH = ROOT / "pull_state.json"

JOBS = {
    "pull-rss": {
        "label": "Pull RSS", "script": "news_ingest.py", "args": ["--only", "rss"],
        "desc": "Fetch the latest RSS/Atom headlines (last day or two).",
        "accent": P["navy2"],
    },
    "pull-gdelt": {
        "label": "Pull GDELT", "script": "news_ingest.py", "args": ["--only", "gdelt"],
        "desc": "Per-country GDELT search; uses the window dropdown.",
        "uses_since": True, "accent": P["navy3"],
    },
    "prune-news": {
        "label": f"Clear old news (>{PRUNE_DAYS}d)",
        "pyc": f"import core; print('cleared', core.prune_news({PRUNE_DAYS}), "
               f"'rows older than {PRUNE_DAYS} days')",
        "desc": f"Delete news older than {PRUNE_DAYS} days.",
        "accent": P["brown"],
    },
    "pull-selected": {
        "label": "Pull selected", "custom": True,
        "desc": "Pull the ticked data sources.", "accent": P["gold"],
    },
}

SINCE_OPTS = [("Last 3 days", "3d"), ("Last week", "1w"),
              ("Last 2 weeks", "2w"), ("Last month", "1m")]

TIMEFRAME_OPTS = [
    ("Full history", ""), ("1 day", "1d"), ("3 days", "3d"), ("7 days", "7d"),
    ("1 month", "1m"), ("3 months", "3m"), ("6 months", "6m"),
    ("1 year", "1y"), ("5 years", "5y"), ("10 years", "10y"),
    ("20 years", "20y"), ("50 years", "50y"),
]
_TF_LABEL = {v: l for l, v in TIMEFRAME_OPTS}

_lock = threading.Lock()
_state: dict[str, dict] = {j: {"status": "idle"} for j in JOBS}
_procs: dict[str, subprocess.Popen] = {}
_last_snap = {"v": None}


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def _any_running() -> bool:
    return any(s.get("status") == "running" for s in _state.values())


def _rel(last_run: str) -> str:
    try:
        d = dt.date.fromisoformat(str(last_run)[:10])
    except Exception:
        return "never"
    n = (dt.date.today() - d).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 30:
        return f"{n}d ago"
    if n < 365:
        return f"{n // 30}mo ago"
    return f"{n // 365}y ago"


def _log_lookup(log) -> dict:
    d = {}
    if log is None:
        return d
    try:
        for _, r in log.iterrows():
            d[str(r["source_id"])] = (str(r["last_run"]), r.get("rows"))
    except Exception:
        pass
    return d


def _since_to_start(since) -> str:
    """'5y' / '3m' / '7d' -> a YYYY-MM-DD start date. '' = full history."""
    s = str(since or "").strip()
    if not s:
        return ""
    try:
        num, unit = int(s[:-1]), s[-1].lower()
    except Exception:
        return ""
    days = {"d": 1, "w": 7, "m": 30, "y": 365}.get(unit)
    if not days:
        return ""
    return (dt.date.today() - dt.timedelta(days=num * days)).isoformat()


def _record_timeframe(keys, since_value) -> None:
    label = _TF_LABEL.get(str(since_value or ""), "Full history")
    try:
        d = {}
        if _TF_PATH.exists():
            d = json.load(open(_TF_PATH, encoding="utf-8")) or {}
        now = dt.datetime.now().isoformat(timespec="seconds")
        for k in keys:
            d[k] = {"since": label, "ts": now}
        json.dump(d, open(_TF_PATH, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


def _timeframes() -> dict:
    try:
        if _TF_PATH.exists():
            return json.load(open(_TF_PATH, encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _argv_for(job):
    if "pyc" in job:
        return [sys.executable, "-c", job["pyc"]]
    script = ROOT / job["script"]
    if not script.exists():
        return None
    return [sys.executable, str(script), *job.get("args", [])]


def _spawn(job_id, argv, env):
    try:
        proc = subprocess.Popen(argv, cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as e:
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1, "tail": str(e)}
        return
    with _lock:
        _procs[job_id] = proc
        _state[job_id] = {"status": "running", "started": _now(),
                          "finished": None, "rc": None, "tail": ""}
    threading.Thread(target=_reap, args=(job_id, proc), daemon=True).start()


def _launch(job_id, since=None) -> None:
    job = JOBS[job_id]
    argv = _argv_for(job)
    if argv is None:
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1,
                              "tail": f"{job.get('script', '?')} not found"}
        return
    env = dict(os.environ)
    if job.get("uses_since") and since:
        env["EMDASH_GDELT_TIMESPAN"] = str(since)
    _spawn(job_id, argv, env)


def _launch_custom(only_keys, since=None, trim=False) -> None:
    job_id = "pull-selected"
    valid = set(getattr(config, "SOURCE_PROVIDER", {}))
    keys = [k for k in (only_keys or []) if k in valid]
    if not keys:
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1,
                              "tail": "no pullable sources ticked"}
        return
    script = ROOT / "ingest.py"
    if not script.exists():
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1,
                              "tail": "ingest.py not found"}
        return
    env = dict(os.environ)
    start = _since_to_start(since)
    if start:
        env["EMDASH_MARKET_START"] = start
        if trim:
            env["EMDASH_MARKET_TRIM"] = start
    _record_timeframe(keys, since)
    _spawn(job_id, [sys.executable, str(script), "--only", *keys], env)


def _reap(job_id, proc) -> None:
    out = ""
    try:
        out, _ = proc.communicate()
    except Exception as e:
        out = f"(could not read output: {e})"
    rc = proc.returncode
    tail = "\n".join((out or "").strip().splitlines()[-4:])
    with _lock:
        prev = _state.get(job_id, {})
        _state[job_id] = {"status": "done" if rc == 0 else "failed",
                          "started": prev.get("started"), "finished": _now(),
                          "rc": rc, "tail": tail or "(no output)"}
        _procs.pop(job_id, None)


def _status_snapshot() -> dict:
    with _lock:
        return {j: dict(s) for j, s in _state.items()}


def _status_pill(job_id, s):
    st = s.get("status", "idle")
    if st == "running":
        txt, col, bg = "Running...", P["navy1"], "#EAF0F9"
    elif st == "done":
        txt = f"Done {s.get('finished', '')} - {s.get('tail', '')[:60]}"
        col, bg = P["good"], "#E4F0E6"
    elif st == "failed":
        txt = f"Failed {s.get('finished', '')} - {s.get('tail', '')[:60]}"
        col, bg = P["bad"], "#F7E4E1"
    else:
        return html.Span()
    return html.Span(txt, style={"color": col, "background": bg,
                                 "padding": "3px 9px", "borderRadius": "8px",
                                 "fontSize": "11px", "marginLeft": "8px",
                                 "whiteSpace": "nowrap", "maxWidth": "340px",
                                 "overflow": "hidden", "textOverflow": "ellipsis",
                                 "verticalAlign": "middle"})


def _button(jid):
    job = JOBS[jid]
    accent = job.get("accent", P["navy2"])
    return html.Div([
        html.Button("\u21bb  " + job["label"], id=f"btn-{jid}", n_clicks=0,
                    title=job.get("desc", ""),
                    style={"background": accent, "color": "#fff", "border": "none",
                           "borderRadius": "8px", "padding": "8px 14px",
                           "fontWeight": 700, "fontSize": "13px", "cursor": "pointer",
                           "fontFamily": config.FONTS["ui"]}),
        html.Span(id=f"stat-{jid}"),
    ], style={"display": "inline-flex", "alignItems": "center", "margin": "2px 4px"})


def buttons_bar(which=None):
    which = which or [j for j in JOBS if not JOBS[j].get("custom")]
    return html.Div([_button(j) for j in which if j in JOBS],
                    style={"display": "flex", "gap": "8px", "flexWrap": "wrap",
                           "alignItems": "center", "padding": "2px 0"})


def news_since():
    default = getattr(config, "GDELT_TIMESPAN", "3d")
    if default not in [v for _, v in SINCE_OPTS]:
        default = "3d"
    return html.Div([
        html.Span("GDELT window", className="emd-ctrl-label"),
        dcc.Dropdown(id="news-since", value=default, clearable=False,
                     style={"width": "150px"},
                     options=[{"label": l, "value": v} for l, v in SINCE_OPTS]),
    ], className="emd-ctrl-group")


_COLW = {"name": "190px", "prov": "128px", "note": "320px",
         "last": "86px", "tf": "96px", "rows": "62px"}


def _type_chip(kind):
    if kind == "bloomberg":
        return html.Span("Bloomberg", style={
            "background": BORANGE, "color": "#3A2A00", "fontWeight": 700,
            "fontSize": "9.5px", "padding": "1px 7px", "borderRadius": "10px"})
    return html.Span("open-source", style={
        "background": "#E4F0E6", "color": P["good"], "fontWeight": 600,
        "fontSize": "9.5px", "padding": "1px 7px", "borderRadius": "10px"})


def _hcell(txt, w, align="left"):
    return html.Span(txt, style={
        "width": w, "minWidth": w, "textAlign": align, "fontSize": "10px",
        "fontWeight": 700, "letterSpacing": ".4px", "textTransform": "uppercase",
        "color": P["navy2"]})


def _cell(child, w, align="left", **extra):
    st = {"width": w, "minWidth": w, "textAlign": align, "overflow": "hidden",
          "textOverflow": "ellipsis", "whiteSpace": "nowrap"}
    st.update(extra)
    return html.Span(child, style=st)


def _table_header(with_check=True, with_tf=True):
    cells = []
    if with_check:
        cells.append(html.Span(style={"width": "26px", "minWidth": "26px"}))
    cells.append(_hcell("Source", _COLW["name"]))
    cells.append(_hcell("Provider", _COLW["prov"]))
    cells.append(_hcell("Notes", _COLW["note"]))
    cells.append(_hcell("Last pull", _COLW["last"], "right"))
    if with_tf:
        cells.append(_hcell("Timeframe", _COLW["tf"], "right"))
    cells.append(_hcell("Rows", _COLW["rows"], "right"))
    return html.Div(cells, style={
        "display": "flex", "alignItems": "center", "gap": "10px",
        "padding": "0 0 6px 0", "borderBottom": f"2px solid {P['gold']}"})


def _info_row(meta, key, lk, tf, with_tf=True):
    last, rows = "never", "\u2014"
    lg = meta.get("log")
    if lg and lg in lk:
        lr, rw = lk[lg]
        last = _rel(lr)
        try:
            rows = f"{int(rw):,}"
        except Exception:
            rows = "\u2014"
    tfv = tf.get(key, {}).get("since", "\u2014") if with_tf else None
    name = html.Span([
        html.Span(meta["label"], style={"fontWeight": 600, "color": P["ink"],
                                        "marginRight": "6px"}),
        _type_chip(meta["kind"]),
    ])
    cells = [
        _cell(name, _COLW["name"], whiteSpace="normal"),
        _cell(meta["provider"], _COLW["prov"], color=P["muted"], fontSize="12px"),
        _cell(f"{meta['freq']} \u00b7 {meta['note']}", _COLW["note"],
              color=P["muted"], fontSize="11px", whiteSpace="normal"),
        _cell(last, _COLW["last"], "right", fontSize="11.5px",
              color=(P["muted"] if last == "never" else P["ink"])),
    ]
    if with_tf:
        cells.append(_cell(tfv, _COLW["tf"], "right", fontSize="11px",
                           color=P["muted"]))
    cells.append(_cell(rows, _COLW["rows"], "right", fontWeight=600,
                       fontSize="12px"))
    return cells


def data_panel(log=None):
    sp = getattr(config, "SOURCE_PROVIDER", {})
    future = getattr(config, "SOURCE_FUTURE", {})
    lk = _log_lookup(log)
    tf = _timeframes()

    def option(key, meta, disabled=False):
        info = _info_row(meta, key, lk, tf, with_tf=True)
        label = html.Span(info, style={"display": "flex", "alignItems": "center",
                                       "gap": "10px", "flex": "1"})
        return {"label": label, "value": key, "disabled": disabled}

    options = [option(k, m) for k, m in sp.items()]
    options += [option(f"future:{k}", m, disabled=True)
                for k, m in future.items()]

    controls = html.Div([
        html.Button("Select all", id="pull-select-all", n_clicks=0,
                    className="emd-btn emd-btn--ghost"),
        html.Button("Clear", id="pull-select-none", n_clicks=0,
                    className="emd-btn emd-btn--ghost"),
        html.Span("Pull timeframe", className="emd-ctrl-label",
                  style={"marginLeft": "16px"}),
        dcc.Dropdown(id="pull-since", clearable=False, value="",
                     persistence=True, persistence_type="local",
                     style={"width": "150px"},
                     options=[{"label": l, "value": v} for l, v in TIMEFRAME_OPTS]),
        dcc.Checklist(
            id="pull-trim",
            options=[{"label": " Trim older rows to timeframe", "value": "on"}],
            value=[], className="emd-check",
            persistence=True, persistence_type="local",
            style={"marginLeft": "8px"}),
        html.Span("market/price sources only \u00b7 macro pulls full history "
                  "\u00b7 trim DELETES rows older than the window",
                  style={"fontSize": "10.5px", "color": P["muted"],
                         "fontStyle": "italic", "marginLeft": "10px"}),
    ], style={"display": "flex", "alignItems": "center", "gap": "8px",
              "flexWrap": "wrap", "marginBottom": "12px"})

    checklist = dcc.Checklist(
        id="pull-sources", options=options, value=list(sp.keys()),
        persistence=True, persistence_type="local",
        inputStyle={"marginRight": "10px", "marginTop": "2px"},
        labelStyle={"display": "flex", "alignItems": "flex-start",
                    "padding": "7px 0", "borderBottom": f"1px solid {P['border']}"},
        style={"display": "block"})

    actions = html.Div([
        html.Button("\u21bb  Pull selected", id="btn-pull-selected", n_clicks=0,
                    style={"background": P["gold"], "color": "#fff", "border": "none",
                           "borderRadius": "8px", "padding": "8px 16px",
                           "fontWeight": 700, "fontSize": "13px", "cursor": "pointer",
                           "fontFamily": config.FONTS["ui"]}),
        html.Span(id="stat-pull-selected"),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px",
              "marginTop": "14px"})

    return html.Div([controls, _table_header(True, True), checklist, actions])


_NEWS_ROWS = {
    "rss": {"label": "RSS / Atom feeds", "provider": "60+ outlets",
            "kind": "open", "freq": "Continuous",
            "note": "Central banks, wires, local EM outlets (last day or two)",
            "log": "rss_all"},
    "gdelt": {"label": "GDELT", "provider": "GDELT Project",
              "kind": "open", "freq": "15 min",
              "note": "Per-country news search across the global press",
              "log": "gdelt"},
}


def news_panel(log=None):
    lk = _log_lookup(log)
    rows = []
    for key, meta in _NEWS_ROWS.items():
        cells = _info_row(meta, key, lk, {}, with_tf=False)
        rows.append(html.Div(cells, style={
            "display": "flex", "alignItems": "center", "gap": "10px",
            "padding": "7px 0", "borderBottom": f"1px solid {P['border']}"}))

    actions = html.Div([
        news_since(),
        _button("pull-rss"), _button("pull-gdelt"), _button("prune-news"),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px",
              "flexWrap": "wrap", "marginTop": "14px"})

    return html.Div([_table_header(False, False),
                     html.Div(rows), actions])


def status_store():
    return html.Div([
        dcc.Store(id="runner-store"),
        dcc.Interval(id="runner-poll", interval=2000, n_intervals=0,
                     disabled=True),
    ])


def register(app):
    for jid in JOBS:
        if JOBS[jid].get("custom"):
            continue
        uses_since = JOBS[jid].get("uses_since", False)
        states = [State("news-since", "value")] if uses_since else []

        @app.callback(Output("runner-store", "data", allow_duplicate=True),
                      Input(f"btn-{jid}", "n_clicks"), *states,
                      prevent_initial_call=True)
        def _go(n_clicks, *extra, _jid=jid, _uses=uses_since):
            if not n_clicks:
                return no_update
            with _lock:
                if _any_running():
                    return no_update
            since = extra[0] if (_uses and extra) else None
            _launch(_jid, since=since)
            snap = _status_snapshot()
            _last_snap["v"] = snap
            return snap

    @app.callback(Output("runner-store", "data"),
                  Input("runner-poll", "n_intervals"))
    def _poll(_n):
        snap = _status_snapshot()
        if snap == _last_snap["v"]:
            return no_update
        _last_snap["v"] = snap
        return snap

    @app.callback(Output("runner-poll", "disabled"),
                  Input("runner-store", "data"))
    def _toggle(_data):
        return not _any_running()

    outputs = [Output(f"stat-{jid}", "children") for jid in JOBS]

    @app.callback(outputs, Input("runner-store", "data"))
    def _render(data):
        data = data or _status_snapshot()
        return [_status_pill(jid, data.get(jid, {"status": "idle"})) for jid in JOBS]

    @app.callback(Output("pull-sources", "value"),
                  Input("pull-select-all", "n_clicks"),
                  Input("pull-select-none", "n_clicks"),
                  prevent_initial_call=True)
    def _select_all(_a, _b):
        trig = (callback_context.triggered[0]["prop_id"].split(".")[0]
                if callback_context.triggered else "")
        if trig == "pull-select-none":
            return []
        return list(getattr(config, "SOURCE_PROVIDER", {}))

    @app.callback(Output("runner-store", "data", allow_duplicate=True),
                  Input("btn-pull-selected", "n_clicks"),
                  State("pull-sources", "value"), State("pull-since", "value"),
                  State("pull-trim", "value"),
                  prevent_initial_call=True)
    def _go_selected(n_clicks, sources, since, trim):
        if not n_clicks:
            return no_update
        with _lock:
            if _any_running():
                return no_update
        _launch_custom(sources or [], since=since, trim=bool(trim))
        snap = _status_snapshot()
        _last_snap["v"] = snap
        return snap
