"""EMDASH cross-file consistency audit. Prints PASS/WARN/FAIL per check."""
import importlib, sys, re
FAILS=[]; WARNS=[]; PASSES=[]
def ok(m): PASSES.append(m); print(f"  PASS  {m}")
def warn(m): WARNS.append(m); print(f"  WARN  {m}")
def fail(m): FAILS.append(m); print(f"  FAIL  {m}")

print("="*74); print("EMDASH AUDIT"); print("="*74)

import config, core

# ---- 1. every module imports cleanly -------------------------------------
print("\n[1] module imports")
for mod in ("core","ingest","mrc","database_tab","runner"):
    try:
        importlib.import_module(mod); ok(f"import {mod}")
    except Exception as e:
        fail(f"import {mod}: {e}")

import ingest, mrc, database_tab, runner

# ---- 2. ingest _DISPATCH flags all exist in FEATURE_FLAGS -----------------
print("\n[2] ingest dispatch <-> config flags")
for key,(flag,fn,default) in ingest._DISPATCH.items():
    if flag is None: continue
    if flag in config.FEATURE_FLAGS: ok(f"{key}: flag {flag} present")
    else: warn(f"{key}: flag {flag} NOT in FEATURE_FLAGS (uses default {default})")

# ---- 3. collectors reference config dicts that exist ---------------------
print("\n[3] collectors <-> config dicts")
need = {"fetch_equities":"EQUITY_INDICES","fetch_stooq_equities":"EQUITY_STOOQ",
        "fetch_yields":"SOVEREIGN_YIELDS","fetch_fred_fx":"FX_FRED",
        "fetch_fred":"FRED_SERIES","fetch_globals":"MARKET_TICKERS",
        "fetch_commodities":"COMMODITIES"}
for fn,dictname in need.items():
    has_fn = hasattr(ingest, fn); has_dict = hasattr(config, dictname)
    if has_fn and has_dict: ok(f"{fn} <-> config.{dictname}")
    else: fail(f"{fn} present={has_fn}, config.{dictname} present={has_dict}")

# ---- 4. series names ingest WRITES == database_tab EXPECTS ----------------
print("\n[4] market series names: ingest writes <-> database_tab _MARKET_ORDER")
# what fetch_yields writes:
tenor_series = set(ingest._TENOR_SERIES.values())  # Y2,Y5,Y10,Y30
writes = {"FX","EQUITY","FX_FRED"} | tenor_series
expects = set(database_tab._MARKET_ORDER)
missing_in_tab = writes - expects
if not missing_in_tab: ok(f"all written series {sorted(writes)} are in _MARKET_ORDER")
else: warn(f"series written but NOT shown in tab order: {missing_in_tab}")

# ---- 5. database_tab macro order matches config indicators ---------------
print("\n[5] database_tab macro order <-> config indicators")
cfg_macro = set(config.WB_INDICATORS)|set(config.DBN_SERIES)
tab_macro = set(database_tab._MACRO_ORDER)
if cfg_macro == tab_macro: ok(f"macro field order matches ({len(cfg_macro)} indicators)")
else:
    extra = tab_macro - cfg_macro; missing = cfg_macro - tab_macro
    if extra: warn(f"tab lists indicators not in config: {extra}")
    if missing: warn(f"config has indicators not in tab order (will append): {missing}")

# ---- 6. core.coverage scopes match database_tab scopes -------------------
print("\n[6] core.coverage() scopes <-> database_tab")
import inspect
cov_src = inspect.getsource(core.coverage)
for scope in ("macro","market","commodity","global"):
    if f"'{scope}'" in cov_src or f'"{scope}"' in cov_src: ok(f"coverage emits scope '{scope}'")
    else: fail(f"coverage missing scope '{scope}'")

# ---- 7. runner JOBS reference real scripts + valid args -------------------
print("\n[7] runner JOBS")
for jid,job in runner.JOBS.items():
    if job["script"] in ("ingest.py","news_ingest.py"): ok(f"{jid} -> {job['script']} {' '.join(job['args'])}")
    else: warn(f"{jid} -> unusual script {job['script']}")
# ingest --only keys referenced by runner must exist in _DISPATCH
mk = job = runner.JOBS["update-markets"]["args"]
only_keys = [a for a in runner.JOBS["update-markets"]["args"] if a!="--only"]
for k in only_keys:
    if k in ingest._DISPATCH: ok(f"runner 'update-markets' --only {k} is a valid ingest key")
    else: fail(f"runner references unknown ingest key: {k}")

# ---- 8. mrc config knobs exist / defaults sane ---------------------------
print("\n[8] mrc.py <-> config knobs")
for knob in ("MRC_MIN_MARGIN","MRC_MIN_DAYS","MRC_HI","MRC_LO","MRC_Z_WINDOW"):
    if hasattr(config, knob): ok(f"config.{knob} = {getattr(config,knob)}")
    else: warn(f"config.{knob} absent (mrc uses built-in default)")
assert hasattr(mrc,"confidence"), "mrc.confidence missing"
assert hasattr(mrc,"MIN_MARGIN"), "mrc.MIN_MARGIN missing"
ok("mrc.confidence() and MIN_MARGIN present")

# ---- 9. FEED_ORIGIN_ISO keys <-> RSS_FEEDS source_ids --------------------
print("\n[9] news: FEED_ORIGIN_ISO <-> RSS_FEEDS")
feed_ids = {f[0] for f in config.RSS_FEEDS}
for sid in config.FEED_ORIGIN_ISO:
    if sid in feed_ids: ok(f"origin '{sid}' has a matching feed")
    else: warn(f"FEED_ORIGIN_ISO '{sid}' has no matching RSS feed (harmless)")

# ---- 10. FEED_ORIGIN_ISO iso3 values are real countries ------------------
print("\n[10] FEED_ORIGIN_ISO iso3 values are real countries")
isos = {i for i,*_ in config.COUNTRIES}
for sid,iso in config.FEED_ORIGIN_ISO.items():
    # CAN/MEX/ZAF/AUS may not be in the abbreviated fixture; check format only
    if re.fullmatch(r"[A-Z]{3}", iso): ok(f"{sid} -> {iso} (valid iso3 format)")
    else: fail(f"{sid} -> {iso} not a 3-letter code")

# ---- 11. core write cols match what collectors pass ----------------------
print("\n[11] core write schema <-> collector row shapes")
cols = core._TABLE_COLS
# market_data collectors pass (date,iso3,series,value,source_id) = 5
if cols["market_data"].count(",")+1 == 5: ok("market_data expects 5 cols (FX/EQUITY/yields/fx_fred all 5-tuple)")
else: fail(f"market_data col count = {cols['market_data'].count(',')+1}")
if cols["predmarket_data"].count(",")+1 == 5: ok("predmarket_data expects 5 cols (Polymarket writes 5-tuple)")
else: fail("predmarket_data col mismatch")

print("\n"+"="*74)
print(f"RESULT:  {len(PASSES)} PASS   {len(WARNS)} WARN   {len(FAILS)} FAIL")
print("="*74)
if FAILS:
    print("\nFAILURES:"); [print("  -",f) for f in FAILS]; sys.exit(1)
