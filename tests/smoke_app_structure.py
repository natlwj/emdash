"""Dependency-light structural smoke test for environments where Dash is unavailable.

It validates that the complete app imports, registers callbacks, constructs the full
layout, and exposes the expected tab labels. It does not replace a real browser test.
"""
from __future__ import annotations

import sys
import types


class Component:
    def __init__(self, name, *children, **props):
        self.name = name
        self.children = children if children else props.get("children")
        self.props = props
        for key, value in props.items():
            setattr(self, key, value)


class Namespace:
    def __getattr__(self, name):
        return lambda *args, **kwargs: Component(name, *args, **kwargs)


class StubDash:
    def __init__(self, *args, **kwargs):
        self.config = types.SimpleNamespace(suppress_callback_exceptions=False)
        self.server = object()
        self.callbacks = []
        self.layout = None

    def callback(self, *args, **kwargs):
        def decorator(function):
            self.callbacks.append((args, kwargs, function))
            return function
        return decorator

    def run(self, *args, **kwargs):
        raise RuntimeError("The structural stub cannot run a web server.")


def install_stub():
    dash = types.ModuleType("dash")
    dash.Dash = StubDash
    dash.dcc = Namespace()
    dash.html = Namespace()
    dash.dash_table = Namespace()
    dash.Input = lambda *args, **kwargs: ("Input", args, kwargs)
    dash.Output = lambda *args, **kwargs: ("Output", args, kwargs)
    dash.State = lambda *args, **kwargs: ("State", args, kwargs)
    dash.ALL = "ALL"
    dash.MATCH = "MATCH"
    dash.no_update = object()
    dash.callback_context = types.SimpleNamespace(triggered=[])
    dash.ctx = types.SimpleNamespace(triggered_id=None)
    sys.modules["dash"] = dash


def walk(component, labels):
    if isinstance(component, Component):
        if component.name == "Tab":
            labels.append(getattr(component, "label", None))
        children = component.children
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child, labels)
        elif children is not None:
            walk(children, labels)
    elif isinstance(component, (list, tuple)):
        for child in component:
            walk(child, labels)


def main():
    install_stub()
    import app

    layout = app.serve_layout()
    labels = []
    walk(layout, labels)
    expected = {
        "Data Coverage & Updates", "News Feed", "Indicator Analysis",
        "Event Study", "Regime (MRC)",
    }
    assert expected.issubset(set(labels)), (expected, labels)
    assert len(app.app.callbacks) >= 10, len(app.app.callbacks)
    print(f"app structure smoke OK: {len(app.app.callbacks)} callbacks; tabs={labels}")


if __name__ == "__main__":
    main()
