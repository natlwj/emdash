"""
EMDASH :: runner.py   (v5)
===================================================================
BACKGROUND PULL RUNNER + real Pull buttons + a live status pill.

Each button launches work as a BACKGROUND SUBPROCESS so the dashboard never
freezes. A concurrency guard stops two jobs at once.

v5 CHANGES
  * REAL BUTTONS. v4 wrapped each button in a bordered "island" card, which
    looked like an info panel rather than a clickable control. v5 renders each
    as an actual filled button (SMU-palette accent, white text, rounded, subtle
    shadow); the description is a hover tooltip, not visible body text.
  * POLL NO LONGER CHURNS THE PAGE. v4 re-rendered the pills every 2s while a
    job ran (constant _dash-update-component POSTs + visible flicker). v5's
    poll returns no_update UNLESS the status actually changed, so the page is
    static while "Running..." holds and only updates on Running->Done/Failed.
    (The interval is still fully DISABLED when idle -> zero polling at rest.)
  * NAME: the news depth control is "Pull window (GDELT)" -- clearly a PULL
    setting, distinct from the News tab's "Show news from" DISPLAY filter.

DUPLICATES: news PK is (ts,url) + INSERT OR IGNORE, so re-pulling only adds
genuinely new rows -- pulling often is safe and cheap.

BIG/SLOW PULLS: buttons capture subprocess output (no live progress). For a
long macro/everything pull, prefer running it in the terminal directly, e.g.
    python ingest.py --only worldbank dbnomics
so you can watch per-country progress.

API:
    runner.buttons_bar(which)  -> row of real buttons + status pills
    runner.news_since()        -> the "Pull window (GDELT)" dropdown
    runner.status_store()      -> the dcc.Store + (disabled) dcc.Interval
    runner.register(app)       -> wires clicks + poll + auto enable/disable
===================================================================
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import datetime as dt

from dash import dcc, html, Input, Output, State, no_update

import config

P = config.PALETTE
ROOT = config.ROOT
PRUNE_DAYS = int(getattr(config, "NEWS_PRUNE_DAYS", 90))

JOBS = {
    "pull-news": {
        "label": "Pull News",
        "script": "news_ingest.py", "args": [],
        "desc": "Fetch the latest headlines (RSS + GDELT). Safe to run often.",
        "uses_since": True, "accent": P["navy2"],
    },
    "pull-markets": {
        "label": "Pull Markets",
        "script": "ingest.py",
        "args": ["--only", "yahoo_fx", "equities", "globals", "commodities"],
        "desc": "FX, equity indices, global gauges, commodities.",
        "accent": P["navy2"],
    },
    "pull-macro": {
        "label": "Pull Macro",
        "script": "ingest.py", "args": ["--only", "worldbank", "dbnomics"],
        "desc": "World Bank annual + IMF monthly macro. Slow (105 countries) - "
                "consider running in the terminal to see progress.",
        "accent": P["navy3"],
    },
    "pull-all": {
        "label": "Pull Everything",
        "script": "ingest.py", "args": [],
        "desc": "Every collector: macro + markets. Can take many minutes.",
        "accent": P["gold"],
    },
    "prune-news": {
        "label": f"Clear old news (>{PRUNE_DAYS}d)",
        "pyc": f"import core; print('cleared', core.prune_news({PRUNE_DAYS}), "
               f"'rows older than {PRUNE_DAYS} days')",
        "desc": f"Delete news older than {PRUNE_DAYS} days to keep the DB lean.",
        "accent": P["brown"],
    },
}

SINCE_OPTS = [("Last 3 days", "3d"), ("Last week", "1w"),
              ("Last 2 weeks", "2w"), ("Last month", "1m")]

_lock = threading.Lock()
_state: dict[str, dict] = {j: {"status": "idle"} for j in JOBS}
_procs: dict[str, subprocess.Popen] = {}
_last_snap = {"v": None}     # for the change-only poll


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def _any_running() -> bool:
    return any(s.get("status") == "running" for s in _state.values())


def _argv_for(job):
    if "pyc" in job:
        return [sys.executable, "-c", job["pyc"]]
    script = ROOT / job["script"]
    if not script.exists():
        return None
    return [sys.executable, str(script), *job.get("args", [])]


def _launch(job_id, since=None) -> None:
    job = JOBS[job_id]
    argv = _argv_for(job)
    if argv is None:
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1,
                              "tail": f"{job.get('script','?')} not found"}
        return
    env = dict(os.environ)
    if job.get("uses_since") and since:
        env["EMDASH_GDELT_TIMESPAN"] = str(since)
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
        txt = f"Done {s.get('finished','')} - {s.get('tail','')[:60]}"
        col, bg = P["good"], "#E4F0E6"
    elif st == "failed":
        txt = f"Failed {s.get('finished','')} - {s.get('tail','')[:60]}"
        col, bg = P["bad"], "#F7E4E1"
    else:
        return html.Span()      # idle -> blank
    return html.Span(txt, style={"color": col, "background": bg,
                                 "padding": "3px 9px", "borderRadius": "8px",
                                 "fontSize": "11px", "marginLeft": "8px",
                                 "whiteSpace": "nowrap", "maxWidth": "300px",
                                 "overflow": "hidden",
                                 "textOverflow": "ellipsis",
                                 "verticalAlign": "middle"})


def _button(jid):
    """A REAL filled button (not an info card)."""
    job = JOBS[jid]
    accent = job.get("accent", P["navy2"])
    return html.Div([
        html.Button(
            "\u21bb  " + job["label"], id=f"btn-{jid}", n_clicks=0,
            title=job["desc"],
            style={"background": accent, "color": "#fff", "border": "none",
                   "borderRadius": "8px", "padding": "8px 14px",
                   "fontWeight": 700, "fontSize": "13px", "cursor": "pointer",
                   "boxShadow": "0 1px 2px rgba(31,73,125,.18)",
                   "fontFamily": config.FONTS["ui"]}),
        html.Span(id=f"stat-{jid}"),
    ], style={"display": "inline-flex", "alignItems": "center",
              "margin": "2px 4px"})


def buttons_bar(which=None):
    which = which or list(JOBS)
    return html.Div([_button(jid) for jid in which if jid in JOBS],
                    className="emd-runner",
                    style={"display": "flex", "gap": "8px",
                           "flexWrap": "wrap", "alignItems": "center",
                           "padding": "2px 0"})


def news_since():
    default = getattr(config, "GDELT_TIMESPAN", "3d")
    if default not in [v for _, v in SINCE_OPTS]:
        default = "3d"
    return html.Div([
        html.Span("Pull window (GDELT)", className="emd-ctrl-label"),
        dcc.Dropdown(id="news-since", value=default, clearable=False,
                     style={"width": "150px"},
                     options=[{"label": l, "value": v} for l, v in SINCE_OPTS]),
    ], className="emd-ctrl-group",
        title="How far back GDELT reaches WHEN YOU CLICK Pull News. This is a "
              "PULL setting - it does not change what is displayed. Use "
              "'Show news from' for that.")


def status_store():
    # interval starts DISABLED -> zero polling / zero flicker when idle.
    return html.Div([
        dcc.Store(id="runner-store"),
        dcc.Interval(id="runner-poll", interval=2000, n_intervals=0,
                     disabled=True),
    ])


def register(app):
    for jid in JOBS:
        uses_since = JOBS[jid].get("uses_since", False)
        states = [State("news-since", "value")] if uses_since else []

        @app.callback(Output("runner-store", "data", allow_duplicate=True),
                      Input(f"btn-{jid}", "n_clicks"), *states,
                      prevent_initial_call=True)
        def _go(n_clicks, *extra, _jid=jid, _uses=uses_since):
            if not n_clicks:
                return no_update
            with _lock:
                busy = _any_running()
            if busy:
                return no_update
            since = extra[0] if (_uses and extra) else None
            _launch(_jid, since=since)
            snap = _status_snapshot()
            _last_snap["v"] = snap
            return snap

    # poll: only push a new store value when the snapshot actually CHANGED,
    # so a steady "Running..." does not churn the page every 2 seconds.
    @app.callback(Output("runner-store", "data"),
                  Input("runner-poll", "n_intervals"))
    def _poll(_n):
        snap = _status_snapshot()
        if snap == _last_snap["v"]:
            return no_update
        _last_snap["v"] = snap
        return snap

    # enable the interval while a job runs; disable (stop polling) when idle.
    @app.callback(Output("runner-poll", "disabled"),
                  Input("runner-store", "data"))
    def _toggle(_data):
        return not _any_running()

    outputs = [Output(f"stat-{jid}", "children") for jid in JOBS]

    @app.callback(outputs, Input("runner-store", "data"))
    def _render(data):
        data = data or _status_snapshot()
        return [_status_pill(jid, data.get(jid, {"status": "idle"}))
                for jid in JOBS]


# ===================================================================
# WIRE INTO app.py:
#   import runner
#   ... after server = app.server:   runner.register(app)
#   ... in serve_layout() after dcc.Store(id="_persist_sink"):
#         runner.status_store(),
#   ... News tab -- see _tab_news layout in app.py (display row + pull row).
#   SQLite Store buttons render inside database_tab (imports runner).
#
# Optional config: NEWS_PRUNE_DAYS = 90.
# ===================================================================
