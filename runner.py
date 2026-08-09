"""
EMDASH :: runner.py   (v2)
===================================================================
BACKGROUND PULL RUNNER + the "Update" / "Prune" buttons.

Each button launches work as a BACKGROUND SUBPROCESS so the dashboard never
freezes; a dcc.Interval polls every ~2s and shows a live status pill. A
concurrency guard stops two jobs at once.

v2 CHANGES
  * Jobs can now be either a SCRIPT ("script": "ingest.py") or an inline
    PYTHON ONE-LINER ("pyc": "import core; core.prune_news(180)"). The prune
    button uses pyc, so no new file is needed for it.
  * New "Prune old news" button (deletes news older than PRUNE_DAYS).

MODULAR:
    runner.buttons_bar(which) -> button+status Div (which = list of job ids)
    runner.register(app)      -> wires clicks + poll
    runner.status_store()     -> the dcc.Store + dcc.Interval (add once)
===================================================================
"""
from __future__ import annotations

import subprocess
import sys
import threading
import datetime as dt

from dash import dcc, html, Input, Output

import config

P = config.PALETTE
ROOT = config.ROOT
PRUNE_DAYS = int(getattr(config, "NEWS_PRUNE_DAYS", 180))

# JOB REGISTRY. Each job is EITHER script+args OR pyc (python -c code).
JOBS = {
    "update-news": {
        "label": "Update News",
        "script": "news_ingest.py", "args": [],
        "desc": "Fetch the latest headlines (RSS + GDELT).",
    },
    "update-markets": {
        "label": "Update Markets (quick)",
        "script": "ingest.py",
        "args": ["--only", "globals", "equities", "commodities"],
        "desc": "Refresh daily market data (indices, gauges, commodities).",
    },
    "update-all": {
        "label": "Update Everything (slow)",
        "script": "ingest.py", "args": [],
        "desc": "Full pull: macro + markets + news. Can take minutes.",
    },
    "prune-news": {
        "label": f"Prune old news (>{PRUNE_DAYS}d)",
        "pyc": f"import core; print('pruned', core.prune_news({PRUNE_DAYS}), "
               f"'rows older than {PRUNE_DAYS} days')",
        "desc": f"Delete news older than {PRUNE_DAYS} days to keep the DB lean.",
    },
}

_lock = threading.Lock()
_state: dict[str, dict] = {j: {"status": "idle"} for j in JOBS}
_procs: dict[str, subprocess.Popen] = {}


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def _any_running() -> bool:
    return any(s.get("status") == "running" for s in _state.values())


def _argv_for(job) -> list[str] | None:
    """Build the subprocess argv from a job (script OR pyc)."""
    if "pyc" in job:
        return [sys.executable, "-c", job["pyc"]]
    script = ROOT / job["script"]
    if not script.exists():
        return None
    return [sys.executable, str(script), *job.get("args", [])]


def _launch(job_id: str) -> None:
    job = JOBS[job_id]
    argv = _argv_for(job)
    if argv is None:
        with _lock:
            _state[job_id] = {"status": "failed", "started": _now(),
                              "finished": _now(), "rc": -1,
                              "tail": f"{job.get('script','?')} not found"}
        return
    try:
        proc = subprocess.Popen(argv, cwd=str(ROOT),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
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
    threading.Thread(target=_reap, args=(job_id, proc), daemon=True).start()


def _reap(job_id: str, proc: subprocess.Popen) -> None:
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
    return html.Div([
        dcc.Store(id="runner-store"),
        dcc.Interval(id="runner-poll", interval=2000, n_intervals=0),
    ])


def register(app):
    for jid in JOBS:
        @app.callback(Output("runner-store", "data", allow_duplicate=True),
                      Input(f"btn-{jid}", "n_clicks"),
                      prevent_initial_call=True)
        def _go(n_clicks, _jid=jid):
            if not n_clicks:
                return _status_snapshot()
            with _lock:
                busy = _any_running()
            if busy:
                return _status_snapshot()
            _launch(_jid)
            return _status_snapshot()

    @app.callback(Output("runner-store", "data"),
                  Input("runner-poll", "n_intervals"))
    def _poll(_n):
        return _status_snapshot()

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
#   ... buttons where wanted:
#         News tab:   runner.buttons_bar(["update-news", "prune-news"]),
#         SQLite tab: runner.buttons_bar(["update-markets", "update-all"]),
#
# Optional config knob:  NEWS_PRUNE_DAYS = 180  (default if absent).
# ===================================================================
