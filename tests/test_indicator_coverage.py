from __future__ import annotations

import ast
import datetime as dt
import sys
import types
from pathlib import Path


def install_dash_stub():
    try:
        import dash  # noqa
        return
    except ImportError:
        pass
    class Component:
        def __init__(self, name, *children, **props):
            self.name=name; self.children=children if children else props.get("children"); self.props=props
            for key,value in props.items(): setattr(self,key,value)
    class Namespace:
        def __getattr__(self,name): return lambda *args,**kwargs: Component(name,*args,**kwargs)
    dash=types.ModuleType("dash"); dash.dcc=Namespace(); dash.html=Namespace(); dash.dash_table=Namespace()
    dash.Input=lambda *a,**k:("Input",a,k); dash.Output=lambda *a,**k:("Output",a,k); dash.State=lambda *a,**k:("State",a,k)
    dash.ALL="ALL"; dash.MATCH="MATCH"; dash.no_update=object(); dash.callback_context=types.SimpleNamespace(triggered=[]); dash.ctx=types.SimpleNamespace(triggered_id=None); dash.Component=Component
    sys.modules["dash"]=dash

install_dash_stub()
import indicator_coverage as ic


def provider(snapshot, key):
    return next(row for row in snapshot["providers"] if row["key"] == key)


def walk_text(component):
    texts=[]; component_cls=getattr(sys.modules["dash"],"Component",None)
    def walk(value):
        if component_cls and isinstance(value,component_cls): walk(value.children); walk(value.props)
        elif isinstance(value,dict):
            for item in value.values(): walk(item)
        elif isinstance(value,(list,tuple)):
            for item in value: walk(item)
        elif isinstance(value,str): texts.append(value)
    walk(component)
    return " ".join(texts)


def test_all_provider_catalogue_counts_and_descriptions():
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    assert len(snapshot["providers"])==6
    assert len(provider(snapshot,"world_bank")["catalogue"])==13
    assert len(provider(snapshot,"imf_datamapper")["catalogue"])==7
    assert len(provider(snapshot,"imf_sdmx")["catalogue"])==1
    assert len(provider(snapshot,"fred")["catalogue"])==19
    assert len(provider(snapshot,"yahoo_market")["catalogue"])==15
    assert len(provider(snapshot,"gembridge_excel")["catalogue"])==0
    assert all(row["description"] and row["universe"] and row["emdash_scope"] for row in snapshot["providers"])


def test_catalogue_rows_have_required_fields_and_unknown_coverage():
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    required={"label","code","category","unit","frequency","geography","first","last","last_updated","note"}
    for item in snapshot["providers"]:
        for row in item["catalogue"]:
            assert required<=set(row)
            assert row["first"]=="Not yet queried" and row["last"]=="Not yet queried"


def test_world_bank_and_imf_full_exposed_codes():
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    wb={row["code"] for row in provider(snapshot,"world_bank")["catalogue"]}
    dm={row["code"] for row in provider(snapshot,"imf_datamapper")["catalogue"]}
    assert wb=={"NY.GDP.MKTP.KD.ZG","FP.CPI.TOTL.ZG","BN.CAB.XOKA.GD.ZS","GC.DOD.TOTL.GD.ZS","SL.UEM.TOTL.ZS","NE.EXP.GNFS.ZS","NE.IMP.GNFS.ZS","BX.KLT.DINV.WD.GD.ZS","FI.RES.TOTL.CD","NY.GDP.PCAP.CD","NY.GNS.ICTR.ZS","FM.LBL.BMNY.GD.ZS","SP.POP.TOTL"}
    assert dm=={"NGDP_RPCH","PCPIPCH","BCA","BCA_NGDPD","LUR","GGXCNL_NGDP","GGXWDG_NGDP"}


def test_fred_all_19_rows_and_missing_key_metadata_is_truthful():
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    item=provider(snapshot,"fred")
    assert item["status"]=="API key required / not configured"
    assert len(item["catalogue"])==19
    assert all(row["first"]=="Not yet queried" and row["last"]=="Not yet queried" for row in item["catalogue"])
    assert "additional-series search" in item["emdash_scope"]


def test_dynamic_observation_dates_and_geographies_are_applied_per_series():
    observed={
        ("world_bank","NY.GDP.MKTP.KD.ZG"):{"first":"2006-12-31","last":"2025-12-31","geographies":["China","United States"],"last_updated":"2026-10-24T09:00:00Z"},
        ("yahoo_market","BRENT"):{"first":"2006-01-03","last":"2026-10-23","geographies":["Commodity"],"last_updated":"2026-10-24T09:00:00Z"},
    }
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata=observed)
    wb=next(row for row in provider(snapshot,"world_bank")["catalogue"] if row["code"]=="NY.GDP.MKTP.KD.ZG")
    brent=next(row for row in provider(snapshot,"yahoo_market")["catalogue"] if row["code"]=="BRENT")
    assert (wb["first"],wb["last"])==("2006-12-31","2025-12-31")
    assert "China" in wb["geography"]
    assert (brent["first"],brent["last"])==("2006-01-03","2026-10-23")


def test_dynamic_statuses_use_latest_tests_and_excel_configuration(tmp_path):
    workbook=Path(__file__).resolve().parents[1]/"templates"/"Gembridge_Indicator_Series_Template.xlsx"
    registry={
        "world_bank":{"availability":"available","http_status":"200","tested_at":"2026-10-24T09:45:00Z"},
        "yahoo_market":{"availability":"available","http_status":"200","tested_at":"2026-10-24T09:45:00Z"},
        "imf_datamapper":{"availability":"temporarily unavailable","http_status":"403","tested_at":"2026-10-24T09:45:00Z"},
        "imf_sdmx":{"availability":"temporarily unavailable","http_status":"503","tested_at":"2026-10-24T09:45:00Z"},
        "fred":{"availability":"not configured","http_status":"NOT_CONFIGURED","tested_at":"2026-10-24T09:45:00Z"},
    }
    state={"ia_excel_path":str(workbook),"ia_excel_sheet":"Data_Long","ia_excel_table":"GembridgeSeries","ia_excel_format":"long","ia_excel_mapping":"Mapping"}
    snapshot=ic.coverage_snapshot(status_registry=registry,state=state,now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    assert provider(snapshot,"world_bank")["status"]=="Available · source test passed"
    assert provider(snapshot,"yahoo_market")["status"]=="Available · source test passed"
    assert provider(snapshot,"imf_datamapper")["status"]=="Blocked / unavailable"
    assert provider(snapshot,"imf_sdmx")["status"]=="Temporary maintenance / unavailable"
    assert provider(snapshot,"fred")["status"]=="API key required / not configured"
    excel=provider(snapshot,"gembridge_excel")
    assert excel["status"]=="Configured" and len(excel["catalogue"])==1
    assert excel["catalogue"][0]["first"]=="2026-01-31" and excel["catalogue"][0]["last"]=="2026-03-31"


def test_excel_unconfigured_empty_state_and_schema():
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    excel=provider(snapshot,"gembridge_excel")
    assert excel["status"]=="Workbook not configured"
    assert not excel["catalogue"]
    assert "date, series_id, value" in excel["empty_message"]
    assert "Monthly" in excel["empty_message"] and "Event" in excel["empty_message"]


def test_render_is_collapsed_accessible_and_not_cache_or_sqlite_browser():
    snapshot=ic.coverage_snapshot(status_registry={},state={},now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="",observation_metadata={})
    component=ic.render(snapshot); component_cls=getattr(sys.modules["dash"],"Component",None); details=[]; ids=[]
    def walk(value):
        if component_cls and isinstance(value,component_cls):
            if value.name=="Details": details.append(value)
            if value.props.get("id") is not None: ids.append(value.props["id"])
            walk(value.children); walk(value.props)
        elif isinstance(value,dict):
            for item in value.values(): walk(item)
        elif isinstance(value,(list,tuple)):
            for item in value: walk(item)
    walk(component); text=walk_text(component)
    assert len(details)==6 and all(getattr(detail,"open",None) is False for detail in details)
    assert "ia-cov-expand-all" in ids and "ia-cov-collapse-all" in ids
    assert "Provider universe" in text and "Current EMDASH catalogue" in text
    assert "Already pulled" not in text and "sqlite" not in text.lower() and "cache" not in text.lower()


def test_expand_collapse_state_helper():
    import database_tab
    ids=[{"type":"ia-coverage-detail","provider":key} for key in ("world_bank","fred")]
    assert database_tab._indicator_coverage_open_states("ia-cov-expand-all",ids)==[True,True]
    assert database_tab._indicator_coverage_open_states("ia-cov-collapse-all",ids)==[False,False]
    assert database_tab._indicator_coverage_open_states("ia-cov-expand-all",[])==[]


def test_responsive_stylesheet_and_readable_table_rules_exist():
    css=(Path(__file__).resolve().parents[1]/"assets"/"indicator_coverage.css").read_text()
    assert "@media (max-width:900px)" in css
    assert ".ia-cov-table-wrap" in css and "overflow-x:auto" in css
    assert ".ia-cov-detail[open]" in css


def test_existing_data_coverage_backend_and_controls_are_preserved():
    root=Path(__file__).resolve().parents[1]
    original=ast.parse((root/"_original_database_tab.py").read_text())
    current=ast.parse((root/"database_tab.py").read_text())
    def find(tree,name): return next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
    for name in ("_compute","_matrix","_simple_list","_news_source_table","_tiles","_news_coverage_panel","_sort_sources","_cell"):
        assert ast.dump(find(original,name),include_attributes=False)==ast.dump(find(current,name),include_attributes=False)
    import database_tab
    component=database_tab.tab(); text=walk_text(component); component_cls=getattr(sys.modules["dash"],"Component",None); ids=[]
    def walk(value):
        if component_cls and isinstance(value,component_cls):
            if value.props.get("id") is not None: ids.append(value.props["id"])
            walk(value.children); walk(value.props)
        elif isinstance(value,dict):
            for item in value.values(): walk(item)
        elif isinstance(value,(list,tuple)):
            for item in value: walk(item)
    walk(component)
    assert "db-refresh" in ids and "db-body" in ids
    assert getattr(component,"label",None)=="Data Coverage & Updates"


def test_fred_searched_metadata_dates_and_last_updated_when_available():
    state={"ia_series_config":[{"provider":"fred","indicator":"TESTSERIES",
        "fred_definition":{"code":"TESTSERIES","label":"Test Series","frequency":"Monthly",
        "unit":"Index","semantic_type":"index","description":"Search metadata fixture",
        "source_url":"https://fred.test/TESTSERIES","observation_start":"1990-01-01",
        "observation_end":"2026-09-01","last_updated":"2026-10-01 12:30:00",
        "geography":"United States"}}]}
    snapshot=ic.coverage_snapshot(status_registry={},state=state,
        now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc),fred_key="configured",observation_metadata={})
    row=next(row for row in provider(snapshot,"fred")["catalogue"] if row["code"]=="TESTSERIES")
    assert row["first"]=="1990-01-01" and row["last"]=="2026-09-01"
    assert row["last_updated"]=="2026-10-01 12:30:00"
