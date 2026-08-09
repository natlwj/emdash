"""
EMDASH :: runner.py   (v4)
===================================================================
BACKGROUND PULL RUNNER + clearly-named Pull buttons + a live status pill.

Each button launches work as a BACKGROUND SUBPROCESS so the dashboard never
freezes. A concurrency guard stops two jobs at once.

v4 CHANGES
  * NO MORE CONSTANT REFRESH. v3's status poll (dcc.Interval) ran every 2s
    ALWAYS, redrawing the pills and making the page flicker. v4 keeps the
    Interval DISABLED until a job is actually running, and switches it off
    again the moment everything is idle. So when nothing is pulling, there is
    zero polling and zero flicker.
  * NICER BUTTONS. Each button is a small "island" (rounded card, subtle
    shadow, gold left-accent) in the SMU palette, laid out in a neat row.
  * RENAME + SHORTER DEFAULT. "Prune old news" -> "Clear old news (>Nd)", and
    the default window is now 90 days (config.NEWS_PRUNE_DAYS).
  * NEWS "SINCE" WINDOW unchanged: Pull News reads the news-since dropdown and
    passes the chosen GDELT window via env var EMDASH_GDELT_TIMESPAN.

DUPLICATES: news PK is (ts,url) + INSERT OR IGNORE, so re-pulling only adds
genuinely new rows -- pulling often is safe and cheap.

API:
    runner.buttons_bar(which)  -> styled button+status row
    runner.news_since()        -> the "News window" dropdown (News tab)
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

from dash import dcc, html, Input, Output, State

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
        "desc": "World Bank annual + IMF monthly macro.",
        "accent": P["navy3"],
    },
    "pull-all": {
        "label": "Pull Everything",
        "script": "ingest.py", "args": [],
        "desc": "Every collector: macro + markets. Can take minutes.",
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
        txt, col, bg = f"Running...", P["navy1"], "#EAF0F9"
    elif st == "done":
        txt = f"Done {s.get('finished','')} - {s.get('tail','')[:60]}"
        col, bg = P["good"], "#E4F0E6"
    elif st == "failed":
        txt = f"Failed {s.get('finished','')} - {s.get('tail','')[:60]}"
        col, bg = P["bad"], "#F7E4E1"
    else:
        return html.Span()          # idle -> show nothing (clean)
    return html.Span(txt, style={"color": col, "background": bg,
                                 "padding": "3px 9px", "borderRadius": "8px",
                                 "fontSize": "11px", "marginTop": "6px",
                                 "display": "inline-block",
                                 "whiteSpace": "nowrap", "maxWidth": "260px",
                                 "overflow": "hidden",
                                 "textOverflow": "ellipsis"})


def _button_island(jid):
    job = JOBS[jid]
    return html.Div([
        html.Button("\u21bb  " + job["label"], id=f"btn-{jid}", n_clicks=0,
                    title=job["desc"],
                    style={"border": "none", "background": "transparent",
                           "color": job.get("accent", P["navy1"]),
                           "fontWeight": 700, "fontSize": "13px",
                           "cursor": "pointer", "padding": "2px 2px",
                           "fontFamily": config.FONTS["ui"]}),
        html.Div(job["desc"], style={"fontSize": "10.5px",
                                     "color": P["muted"], "marginTop": "2px"}),
        html.Div(id=f"stat-{jid}"),
    ], style={"background": P["card"], "border": f"1px solid {P['border']}",
              "borderLeft": f"4px solid {job.get('accent', P['navy1'])}",
              "borderRadius": "10px", "padding": "10px 14px",
              "boxShadow": "0 1px 2px rgba(31,73,125,.06)",
              "minWidth": "170px", "flex": "0 1 auto"})


def buttons_bar(which=None):
    which = which or list(JOBS)
    islands = [_button_island(jid) for jid in which if jid in JOBS]
    return html.Div(islands, className="emd-runner",
                    style={"display": "flex", "gap": "12px",
                           "flexWrap": "wrap", "alignItems": "stretch",
                           "padding": "4px 0"})


def news_since():
    default = getattr(config, "GDELT_TIMESPAN", "3d")
    if default not in [v for _, v in SINCE_OPTS]:
        default = "3d"
    return html.Div([
        html.Span("News window", className="emd-ctrl-label"),
        dcc.Dropdown(id="news-since", value=default, clearable=False,
                     style={"width": "150px"},
                     options=[{"label": l, "value": v} for l, v in SINCE_OPTS]),
    ], className="emd-ctrl-group",
        title="How far back GDELT reaches when you click Pull News.")


def status_store():
    # Interval starts DISABLED -> no polling / no flicker when idle.
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
                return _status_snapshot()
            with _lock:
                busy = _any_running()
            if busy:
                return _status_snapshot()
            since = extra[0] if (_uses and extra) else None
            _launch(_jid, since=since)
            return _status_snapshot()

    # poll runs ONLY while enabled (see the disable callback below)
    @app.callback(Output("runner-store", "data"),
                  Input("runner-poll", "n_intervals"))
    def _poll(_n):
        return _status_snapshot()

    # enable the Interval while any job runs; disable it (stop polling) when idle
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
#   ... News tab: put these INSIDE the emd-controls row (not below the board):
#         runner.news_since(),
#         runner.buttons_bar(["pull-news", "prune-news"]),
#   SQLite Store buttons render inside database_tab (imports runner itself).
#
# Optional config: NEWS_PRUNE_DAYS = 90.
# ===================================================================
