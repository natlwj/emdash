from __future__ import annotations

import importlib
import sys
import types

import numpy as np
import pandas as pd
import pytest


def install_dash_stub():
    try:
        import dash  # noqa
        return
    except ImportError:
        pass
    class Component:
        def __init__(self, name, *children, **props):
            self.name=name; self.children=children if children else props.get("children"); self.props=props
            for k,v in props.items(): setattr(self,k,v)
        def __repr__(self): return f"<{self.name}>"
    class Namespace:
        def __getattr__(self,name): return lambda *a,**kw: Component(name,*a,**kw)
    dash=types.ModuleType("dash"); dash.ALL="ALL"; dash.MATCH="MATCH"; dash.no_update=object()
    dash.Input=lambda *a,**kw:("Input",a,kw); dash.Output=lambda *a,**kw:("Output",a,kw); dash.State=lambda *a,**kw:("State",a,kw)
    dash.ctx=types.SimpleNamespace(triggered_id=None); dash.dcc=Namespace(); dash.html=Namespace(); dash.dash_table=Namespace(); dash.Component=Component
    sys.modules["dash"]=dash

install_dash_stub()
ia=importlib.import_module("indicator_analysis")


def payload():
    return {"series":[
        {"records":[
            {"date":"2020-12-31","period":"2020","value":100.0,"is_projection":False},
            {"date":"2021-12-31","period":"2021","value":110.0,"is_projection":False},
            {"date":"2022-12-31","period":"2022","value":121.0,"is_projection":False},
            {"date":"2023-12-31","period":"2023","value":133.1,"is_projection":False},
            {"date":"2024-12-31","period":"2024","value":146.41,"is_projection":False},
        ],"meta":{"request_id":"u1","provider_label":"World Bank WDI","source":"WDI","source_url":"x","geography":"USA","geography_label":"United States","label":"GDP per capita","series_code":"GDP","frequency":"Annual","unit":"USD per person","semantic_type":"raw_level","retrieved_at":"2026-10-23T00:00:00Z","cache_status":"live"}},
        {"records":[
            {"date":"2024-01-01","period":"2024-01","value":200.0,"is_projection":False},
            {"date":"2024-02-01","period":"2024-02","value":202.0,"is_projection":False},
            {"date":"2024-03-01","period":"2024-03","value":204.0,"is_projection":False},
            {"date":"2024-04-01","period":"2024-04","value":206.0,"is_projection":False},
        ],"meta":{"request_id":"u2","provider_label":"IMF SDMX — CPI","source":"IMF CPI","source_url":"x","geography":"USA","geography_label":"United States","label":"CPI","series_code":"CPI","frequency":"Monthly","unit":"Index","semantic_type":"index","retrieved_at":"2026-10-23T00:00:00Z","cache_status":"fresh cache"}},
    ],"errors":[]}


def configs():
    return [
        {"uid":"u1","included":True,"collapsed":False,"provider":"world_bank","geography":"USA","indicator":"NY.GDP.PCAP.CD","transform":"yoy","window":3,"colour":"#2E5C96"},
        {"uid":"u2","included":True,"collapsed":True,"provider":"imf_sdmx","geography":"USA","indicator":"CPI_ALL_ITEMS_INDEX_M","transform":"mom","window":3,"colour":"#948A54"},
    ]


def test_frequency_aware_transform_options():
    annual=ia.valid_transforms("Annual"); monthly=ia.valid_transforms("Monthly"); event=ia.valid_transforms("Event")
    assert "yoy" in annual and "mom" not in annual and "qoq" not in annual
    assert {"mom","qoq","yoy"} <= set(monthly)
    assert "pop_pct" not in event and "mom" not in event and "level" in event


def test_series_transform_math_annual_and_monthly():
    annual=pd.Series([100,110,121],index=pd.to_datetime(["2020-12-31","2021-12-31","2022-12-31"]))
    yoy,unit=ia.apply_series_transform(annual,"yoy","Annual",5)
    assert yoy.dropna().tolist()==pytest.approx([10,10]); assert unit=="%"
    monthly=pd.Series([100,101,103,106],index=pd.date_range("2024-01-01",periods=4,freq="MS"))
    mom,_=ia.apply_series_transform(monthly,"mom","Monthly",3); qoq,_=ia.apply_series_transform(monthly,"qoq","Monthly",3)
    assert mom.dropna().iloc[0]==pytest.approx(1.0); assert qoq.dropna().iloc[0]==pytest.approx(6.0)


def test_difference_rolling_rebase_and_zscore():
    s=pd.Series([1,2,3,4,5],index=pd.date_range("2020",periods=5,freq="YS"))
    diff,_=ia.apply_series_transform(s,"diff","Annual",3); avg,_=ia.apply_series_transform(s,"rolling_mean","Annual",3)
    rebased,u=ia.apply_series_transform(s,"rebase","Annual",3); z,zu=ia.apply_series_transform(s,"rolling_zscore","Annual",3)
    assert diff.dropna().tolist()==[1,1,1,1]; assert avg.dropna().tolist()==[2,3,4]
    assert rebased.iloc[-1]==500 and u=="Index"; assert np.isfinite(z.dropna().iloc[-1]) and zu=="Z-score"


def test_global_modes_apply_after_series_transform():
    s=pd.Series([10,12,15],index=pd.date_range("2024-01-01",periods=3,freq="MS"))
    assert ia.apply_global_mode(s,"indexed").tolist()==pytest.approx([100,120,150])
    assert ia.apply_global_mode(s,"pct_start").tolist()==pytest.approx([0,20,50])
    standardized=ia.apply_global_mode(s,"standardised")
    assert standardized.mean()==pytest.approx(0) and standardized.std(ddof=0)==pytest.approx(1)


def test_chart_analysis_preserves_native_dates_without_filling():
    frame=ia._frame(payload()); analysis=ia._analysis_series(frame,configs(),"native")
    assert analysis["u1"]["series"].dropna().index.tolist()==pd.to_datetime(["2021-12-31","2022-12-31","2023-12-31","2024-12-31"]).tolist()
    assert analysis["u2"]["series"].dropna().index.tolist()==pd.to_datetime(["2024-02-01","2024-03-01","2024-04-01"]).tolist()


def test_native_mode_uses_two_axes_and_blocks_three_units():
    frame=ia._frame(payload()); level_configs=configs()
    level_configs[0]["transform"]="level"; level_configs[1]["transform"]="level"
    analysis=ia._analysis_series(frame,level_configs,"native")
    fig,subtitle,_=ia._build_chart(analysis,"native")
    assert len(fig.data)==2 and "left/right axes" in subtitle
    third=copy_payload=payload(); third_series={"records":[{"date":"2024-12-31","period":"2024","value":5.0,"is_projection":False}],"meta":{"request_id":"u3","provider_label":"WB","source":"WDI","source_url":"x","geography":"CHN","geography_label":"China","label":"Inflation","series_code":"CPI","frequency":"Annual","unit":"% YoY","semantic_type":"growth_rate","retrieved_at":"x","cache_status":"live"}}
    copy_payload["series"].append(third_series)
    c=level_configs+[{"uid":"u3","included":True,"collapsed":False,"provider":"world_bank","geography":"CHN","indicator":"FP.CPI.TOTL.ZG","transform":"level","window":3,"colour":"#6593C4"}]
    blocked,title,_=ia._build_chart(ia._analysis_series(ia._frame(copy_payload),c,"native"),"native")
    assert len(blocked.data)==0 and "More than two units" in title


def test_chart_period_custom_and_max():
    frame=ia._frame(payload()); assert ia._chart_bounds("max",None,None,frame)==(None,None)
    lo,hi=ia._chart_bounds("custom","2024-01-01","2024-06-30",frame)
    assert lo==pd.Timestamp("2024-01-01") and hi==pd.Timestamp("2024-06-30")


def test_dynamic_series_state_add_collapse_duplicate_reorder_delete_and_limit():
    rows=ia.default_series(); first=rows[0]["uid"]
    rows=ia.mutate_series_config(rows,"collapse",uid=first); assert rows[0]["collapsed"] is True
    rows=ia.mutate_series_config(rows,"duplicate",uid=first); assert len(rows)==3 and rows[1]["uid"]!=first
    duplicate=rows[1]["uid"]; rows=ia.mutate_series_config(rows,"down",uid=duplicate); assert rows[2]["uid"]==duplicate
    rows=ia.mutate_series_config(rows,"delete",uid=duplicate); assert len(rows)==2
    while len(rows)<ia.MAX_SERIES: rows=ia.mutate_series_config(rows,"add")
    capped=ia.mutate_series_config(rows,"add"); assert len(capped)==ia.MAX_SERIES==8


def test_provider_change_resets_invalid_indicator_and_transform():
    rows=configs(); uid=rows[0]["uid"]
    updated=ia.mutate_series_config(rows,"set",uid=uid,field="provider",value="yahoo_market")
    assert updated[0]["indicator"] in ia.MARKET_INDICATORS and updated[0]["transform"]=="level" and updated[0]["geography"]==""


def test_statistics_are_contextual_to_per_series_transform():
    analysis=ia._analysis_series(ia._frame(payload()),configs(),"indexed")
    rows=ia._stats(analysis)
    assert rows[0]["Transformation"]=="YoY %" and rows[0]["Unit"]=="%"
    assert rows[1]["Transformation"]=="MoM %"


def test_layout_is_chart_first_and_underlying_data_collapsed():
    component=ia.tab({}); component_cls=getattr(sys.modules["dash"],"Component",None); texts=[]; details=[]
    def walk(value):
        if component_cls and isinstance(value,component_cls):
            if value.name=="Details":details.append(value)
            walk(value.children); walk(value.props)
        elif isinstance(value,dict):
            for v in value.values():walk(v)
        elif isinstance(value,(list,tuple)):
            for v in value:walk(v)
        elif isinstance(value,str):texts.append(value)
    walk(component); joined=" ".join(texts)
    assert "Add Series" in joined and "Series Statistics" in joined and "View underlying data" in joined
    assert "Data Source Test" in joined and "Fetch History" in joined and "Chart Period" in joined
    assert any(getattr(detail,"open",None) is False for detail in details)
    assert "AI-generated prose" in joined


def test_semantic_rules_prevent_double_transformations_and_use_pp_differences():
    growth = ia.valid_transforms("Annual", "growth_rate")
    ratio = ia.valid_transforms("Annual", "ratio")
    assert "yoy" not in growth and "pop_pct" not in growth
    assert "pp_diff" in growth and "pp_diff" in ratio
    annual = pd.Series([2.0, 2.5, 2.2], index=pd.date_range("2022", periods=3, freq="YS"))
    with pytest.raises(ValueError, match="not valid"):
        ia.apply_series_transform(annual, "yoy", "Annual", semantic_type="growth_rate")
    pp, unit = ia.apply_series_transform(annual, "pp_diff", "Annual",
                                         semantic_type="growth_rate")
    assert pp.dropna().tolist() == pytest.approx([0.5, -0.3])
    assert unit == "percentage points"


def test_sensible_defaults_by_semantic_type():
    assert ia.default_transform("Annual", "growth_rate") == "level"
    assert ia.default_transform("Annual", "ratio") == "level"
    assert ia.default_transform("Monthly", "index") == "yoy"
    assert ia.default_transform("Daily", "price") == "level"
    assert ia.default_transform("Monthly", "spread") == "level"


def test_collapse_expand_persistence_and_unused_colour_assignment():
    rows = ia.default_series()
    original_colours = {row["colour"] for row in rows}
    rows = ia.mutate_series_config(rows, "add")
    assert rows[-1]["colour"] not in original_colours
    rows = ia.mutate_series_config(rows, "collapse_all")
    assert all(row["collapsed"] for row in rows)
    rows = ia.mutate_series_config(rows, "expand_all")
    assert not any(row["collapsed"] for row in rows)
    first = rows[0]["uid"]
    rows = ia.mutate_series_config(rows, "duplicate", uid=first)
    assert rows[1]["colour"] != rows[0]["colour"]
    rows[1]["colour"] = rows[0]["colour"]
    assert "Duplicate colours" in ia.duplicate_colour_warning(rows)


def test_imf_provider_defaults_to_yoy_and_market_hides_geography_editor():
    rows = ia.default_series(); uid = rows[0]["uid"]
    imf = ia.mutate_series_config(rows, "set", uid=uid, field="provider", value="imf_sdmx")
    assert imf[0]["transform"] == "yoy"
    market = ia.mutate_series_config(rows, "set", uid=uid, field="provider", value="yahoo_market")
    component = ia._series_card(market[0], 0, [])
    component_cls = getattr(sys.modules["dash"], "Component", None)
    geography_inputs, texts = [], []
    def walk(value):
        if component_cls and isinstance(value, component_cls):
            component_id = value.props.get("id")
            if isinstance(component_id, dict) and component_id.get("field") == "geography":
                geography_inputs.append(value)
            walk(value.children); walk(value.props)
        elif isinstance(value, dict):
            for item in value.values(): walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value: walk(item)
        elif isinstance(value, str): texts.append(value)
    walk(component)
    assert not geography_inputs
    assert "Asset class" in " ".join(texts)


def test_native_scale_dominance_warning_does_not_change_mode():
    index = pd.date_range("2024-01-01", periods=3, freq="MS")
    analysis = {
        "a": {"chart": pd.Series([1, 2, 3], index=index), "unit": "Index",
              "meta": {"series_name": "Small"}},
        "b": {"chart": pd.Series([1000, 1200, 1400], index=index), "unit": "Index",
              "meta": {"series_name": "Large"}},
    }
    warning = ia.scale_dominance_warning(analysis, "native")
    assert "Scale warning" in warning and "no mode was changed" in warning
    assert ia.scale_dominance_warning(analysis, "indexed") == ""


def test_statistics_include_previous_contextual_change_and_transformed_basis():
    analysis = ia._analysis_series(ia._frame(payload()), configs(), "native")
    rows = ia._stats(analysis)
    first = rows[0]
    assert first["Value Basis"] == "Transformed"
    assert first["Previous"] != "—"
    assert first["Change"].endswith("pp")
    assert first["Unit"] == "%"
    level_configs = configs(); level_configs[1]["transform"] = "level"
    level_rows = ia._stats(ia._analysis_series(ia._frame(payload()), level_configs, "native"))
    assert level_rows[1]["Value Basis"] == "Source level"
    assert level_rows[1]["Latest"] == "206.00"


def test_layout_has_collapse_expand_controls_and_underlying_data_remains_closed():
    component=ia.tab({}); component_cls=getattr(sys.modules["dash"],"Component",None); texts=[]; details=[]
    def walk(value):
        if component_cls and isinstance(value,component_cls):
            if value.name=="Details": details.append(value)
            walk(value.children); walk(value.props)
        elif isinstance(value,dict):
            for item in value.values(): walk(item)
        elif isinstance(value,(list,tuple)):
            for item in value: walk(item)
        elif isinstance(value,str): texts.append(value)
    walk(component); joined=" ".join(texts)
    assert "Collapse All" in joined and "Expand All" in joined
    assert "View underlying data" in joined
    assert any(getattr(detail,"open",None) is False for detail in details)
