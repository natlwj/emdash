"""
EMDASH :: runner.py   (v1)
===================================================================
BACKGROUND PULL RUNNER + the "Update" buttons.

THE PROBLEM this solves:
    Running news_ingest.py / ingest.py can take seconds to minutes. If that ran
    INSIDE a Dash callback, the whole dashboard would FREEZE until it finished
    -- every tab hangs, nothing responds. Unacceptable.

THE SOLUTION:
    Each "Update" button launches the pull as a BACKGROUND SUBPROCESS (a
    separate `python ingest.py ...` process), so the UI never blocks. A small
    dcc.Interval polls every ~2s and shows a live status line
    ("Running..." -> "Done: +37 rows, 21:40"). A concurrency guard stops two
    pulls firing at once.

MODULAR (like database_tab.py):
    runner.buttons_bar()   -> the button+status Div (drop into a tab)
    runner.register(app)   -> wires the click + poll callbacks
    runner.status_store()  -> the dcc.Store + dcc.Interval (add once to layout)

WHY A SUBPROCESS, NOT A THREAD:
    ingest.py is a self-contained CLI. Shelling out to `python ingest.py --only
    ...` reuses it verbatim -- no refactor, no import side-effects, and the pull
    can't crash the Dash process. It also means the SAME code path runs whether
    you click a button or type the command, so behaviour can't diverge.

NOTE on the shared DB: the subprocess writes emdash.sqlite while the app reads
it. SQLite WAL mode (set in core.get_conn) handles concurrent read+write, so
this is safe. After a pull finishes, click the tab's own Refresh to see new
rows (the app caches reads for speed).
===================================================================
"""
from __future__ import annotations

import subprocess
import sys
import threading
import datetime as dt
from pathlib import Path

from dash import dcc, html, Input, Output, State, ctx

import config

P = config.PALETTE
ROOT = config.ROOT

# -------------------------------------------------------------------
# JOB REGISTRY  ::  button-id -> (label, argv tail passed to the script)
# argv tail is appended to  [python, <script>]  so it maps 1:1 to the CLI you
# already use. Keeping it here (not in the callback) means adding a button is a
# one-line edit.
# -------------------------------------------------------------------
JOBS = {
    "update-news": {
        "label": "Update News",
        "script": "news_ingest.py",
        "args": [],                       # full news pull (rss + gdelt)
        "desc": "Fetches the latest headlines (RSS + GDELT).",
    },
    "update-markets": {
        "label": "Update Markets (quick)",
        "script": "ingest.py",
        "args": ["--only", "globals", "equities", "commodities"],
        "desc": "Refreshes daily market data (indices, gauges, commodities).",
    },
    "update-all": {
        "label": "Update Everything (slow)",
        "script": "ingest.py",
        "args": [],                       # every enabled collector
        "desc": "Full pull: macro + markets + news collectors. Can take minutes.",
    },
}

# -------------------------------------------------------------------
# PROCESS STATE  (module-level; one dashboard, one machine)
# _state[job_id] = dict(status, started, finished, rc, tail)
#   status: "idle" | "running" | "done" | "failed"
# A threading.Lock guards it because the poll callback and the launch callback
# can touch it near-simultaneously.
# -------------------------------------------------------------------
_lock = threading.Lock()
_state: dict[str, dict] = {j: {"status": "idle"} for j in JOBS}
_procs: dict[str, subprocess.Popen] = {}


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def _any_running() -> bool:
    return any(s.get("status") == "running" for s in _state.values())


def _launch(job_id: str) -> None:
    """Start a job as a background subprocess (non-blocking)."""
    job = JOBS[job_id]
    script = ROOT / job["script"]
    if not script.exists():
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1,
                              "tail": f"{job['script']} not found in EMDASH folder"}
        return
    argv = [sys.executable, str(script), *job["args"]]
    try:
        proc = subprocess.Popen(
            argv, cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
    except Exception as e:
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1, "tail": str(e)}
        return
    with _lock:
        _procs[job_id] = proc
        _state[job_id] = {"status": "running", "started": _now(),
                          "finished": None, "rc": None, "tail": ""}
    # a daemon thread just waits for completion and records the tail of output;
    # it does NOT block the Dash worker.
    threading.Thread(target=_reap, args=(job_id, proc), daemon=True).start()


def _reap(job_id: str, proc: subprocess.Popen) -> None:
    out = ""
    try:
        out, _ = proc.communicate()          # waits in THIS thread only
    except Exception as e:
        out = f"(could not read output: {e})"
    rc = proc.returncode
    tail = "\n".join((out or "").strip().splitlines()[-4:])   # last 4 lines
    with _lock:
        prev = _state.get(job_id, {})
        _state[job_id] = {"status": "done" if rc == 0 else "failed",
                          "started": prev.get("started"), "finished": _now(),
                          "rc": rc, "tail": tail or "(no output)"}
        _procs.pop(job_id, None)


def _status_snapshot() -> dict:
    with _lock:
        return {j: dict(s) for j, s in _state.items()}


# -------------------------------------------------------------------
# UI PIECES
# -------------------------------------------------------------------
def _status_pill(job_id: str, s: dict):
    st = s.get("status", "idle")
    if st == "running":
        txt, col, bg = f"Running... (started {s.get('started','')})", \
            P["navy1"], "#EAF0F9"
    elif st == "done":
        txt = f"Done {s.get('finished','')}  -  {s.get('tail','')[:80]}"
        col, bg = P["good"], "#E4F0E6"
    elif st == "failed":
        txt = f"Failed {s.get('finished','')}  -  {s.get('tail','')[:80]}"
        col, bg = P["bad"], "#F7E4E1"
    else:
        txt, col, bg = "idle", P["muted"], "#F2F4F8"
    return html.Span(txt, style={"color": col, "background": bg,
                                 "padding": "4px 10px", "borderRadius": "8px",
                                 "fontSize": "11.5px", "marginLeft": "10px",
                                 "whiteSpace": "nowrap"})


def buttons_bar(which=None):
    """The button + status row. `which` = list of job_ids to show (default all).

    Drop this into any tab. Pass which=["update-news"] on the News tab and
    which=["update-markets","update-all"] on the SQLite Store tab, for example.
    """
    which = which or list(JOBS)
    rows = []
    for jid in which:
        if jid not in JOBS:
            continue
        job = JOBS[jid]
        rows.append(html.Div([
            html.Button(job["label"], id=f"btn-{jid}", n_clicks=0,
                        className="emd-btn", title=job["desc"]),
            html.Span(id=f"stat-{jid}"),
        ], style={"display": "flex", "alignItems": "center",
                  "gap": "6px", "margin": "4px 0"}))
    return html.Div(rows, className="emd-runner",
                    style={"padding": "8px 4px"})


def status_store():
    """The shared Store + Interval. Add ONCE to the top-level layout."""
    return html.Div([
        dcc.Store(id="runner-store"),
        # poll every 2s, but only meaningfully updates while something runs
        dcc.Interval(id="runner-poll", interval=2000, n_intervals=0),
    ])


# -------------------------------------------------------------------
# CALLBACKS
# -------------------------------------------------------------------
def register(app):
    """Wire the launch buttons + the status poll. Call once from app.py."""

    # one launch callback per job (simple + explicit; only 3 jobs)
    for jid in JOBS:
        @app.callback(Output("runner-store", "data", allow_duplicate=True),
                      Input(f"btn-{jid}", "n_clicks"),
                      prevent_initial_call=True)
        def _go(n_clicks, _jid=jid):
            if not n_clicks:
                return _no_update_snapshot()
            with _lock:
                busy = _any_running()
            if busy:
                # refuse to start a second pull; the pill will show the running one
                return _status_snapshot()
            _launch(_jid)
            return _status_snapshot()

    # poll -> refresh the store (so pills update as jobs finish)
    @app.callback(Output("runner-store", "data"),
                  Input("runner-poll", "n_intervals"))
    def _poll(_n):
        return _status_snapshot()

    # store -> render every visible status pill
    outputs = [Output(f"stat-{jid}", "children") for jid in JOBS]

    @app.callback(outputs, Input("runner-store", "data"))
    def _render(data):
        data = data or _status_snapshot()
        return [_status_pill(jid, data.get(jid, {"status": "idle"}))
                for jid in JOBS]


def _no_update_snapshot():
    # kept tiny + importable; returns current snapshot rather than dash.no_update
    return _status_snapshot()


# ===================================================================
# HOW TO WIRE INTO app.py  (4 small edits):
#
#   1. near the other imports:              import runner
#   2. right after  server = app.server:    runner.register(app)
#   3. in serve_layout(), inside the top html.Div children list, add ONCE
#      (e.g. right after dcc.Store(id="_persist_sink")):
#          runner.status_store(),
#   4. put the buttons where you want them, e.g.
#        - in _tab_news(), near the "Refresh news" button:
#              runner.buttons_bar(["update-news"]),
#        - in database_tab.tab() controls row:
#              runner.buttons_bar(["update-markets", "update-all"]),
#
# NOTE: allow_duplicate=True (used above) requires Dash >= 2.9. You are on
# 4.2.0, so this is fine. If Dash ever complains about duplicate outputs on
# "runner-store", it means an older Dash -- tell me and I'll switch to a single
# combined launch callback.
# ===================================================================
