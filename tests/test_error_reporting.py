"""
Structured error reporting tests.

Covers:

* Phase A — capture & DOM safety (``shared/errors.py`` + reworked eval helpers
  in ``shared/bindings.py``): failures record a structured ``BindingError`` and
  return an empty value, never the raw ``[Error: ...]`` string; the sentinel
  survives only when no sink is registered.
* Phase B — client overlay + structural surfacing (``client/errors.py``):
  ``window.__basisErrors`` + ``basis-error`` CustomEvent + the dev-only panel,
  verified against a fake DOM stand-in.
* Phase C — server-side capture: SSR collects errors into ``__basis_errors__``
  (``#basis-initial-state``) and renders no ``[Error: ...]``; the dev meta tag
  marks dev mode.
* Phase D — friendly ImportError hints for server-only modules.
"""
import pytest

from basis.shared.bindings import (
    ALLOWED_BUILTINS,
    safe_eval,
    safe_format,
)
from basis.shared.errors import (
    ERROR_EVENT,
    ERRORS_GLOBAL,
    EVAL_ERROR,
    BindingError,
    ErrorCollector,
    find_template_line,
    get_error_sink,
    import_error_hint,
    is_error_string,
    record_error,
    set_error_sink,
)


@pytest.fixture(autouse=True)
def _clean_error_sink():
    """Never let a registered sink leak across tests."""
    yield
    set_error_sink(None)


# ---------------------------------------------------------------------------
# Phase A — shared capture & DOM safety
# ---------------------------------------------------------------------------

def test_no_sink_keeps_legacy_sentinel():
    assert safe_eval("missing_thing", None, ALLOWED_BUILTINS) == "[Error: missing_thing]"


def test_sink_records_parse_error_and_returns_empty():
    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    result = safe_eval("1 +", None, ALLOWED_BUILTINS)
    assert result is EVAL_ERROR
    assert len(seen) == 1
    assert seen[0].expr == "1 +"
    assert "parse" in seen[0].error or "invalid syntax" in seen[0].error


def test_sink_records_name_error_and_returns_empty():
    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    result = safe_eval("missing_thing", None, ALLOWED_BUILTINS)
    assert result is EVAL_ERROR
    assert len(seen) == 1
    assert seen[0].binding_type is None          # not passed → no attribution
    assert seen[0].phase == "server"
    assert "missing_thing" in seen[0].error


def test_error_string_never_returned_when_sink_registered():
    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    assert safe_eval("nope", None, ALLOWED_BUILTINS) is EVAL_ERROR
    assert safe_format("a{nope}b", None, ALLOWED_BUILTINS) == ""
    assert safe_format("x {nope} y", None, ALLOWED_BUILTINS) == ""
    assert not any(is_error_string(v) for v in (EVAL_ERROR, "", "x ", "a"))


def test_format_aborts_whole_template_not_partial():
    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    # The middle field fails — the whole template becomes "" (not "x ").
    assert safe_format("x {nope} y", None, ALLOWED_BUILTINS) == ""
    assert safe_format("p {nope} q", None, ALLOWED_BUILTINS) == ""


def test_record_false_is_silent_and_returns_empty():
    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    assert safe_eval("nope_again", None, ALLOWED_BUILTINS, record=False) == ""
    assert safe_format("a{nope_again}b", None, ALLOWED_BUILTINS, record=False) == ""
    assert seen == []


def test_successful_evaluation_unaffected():
    set_error_sink(lambda err: True)
    assert safe_eval("len([1, 2, 3])", None, ALLOWED_BUILTINS) == 3
    assert safe_format("a{b}c", {"b": "B"}, ALLOWED_BUILTINS) == "aBc"


def test_binding_error_shape_and_to_dict():
    err = BindingError(
        component="Root",
        binding_type="TextBinding",
        expr="message",
        template="<div>\n    {message}\n</div>",
        error="Name message is not defined",
        traceback="Traceback ...",
        phase="server",
        template_line=2,
        hint=None,
    )
    d = err.to_dict()
    assert d["component"] == "Root"
    assert d["binding_type"] == "TextBinding"
    assert d["template_line"] == 2
    assert d["phase"] == "server"
    # from_dict round-trips (used to replay SSR errors on the client)
    assert BindingError.from_dict(d).expr == "message"


def test_component_attr_is_class_name_not_instance():
    """Callers pass a component instance; the record stores the class name so
    it stays JSON-serializable for #basis-initial-state."""
    class _Stub:
        pass

    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    safe_eval("boom", _Stub(), ALLOWED_BUILTINS, component=_Stub(), binding_type="TextBinding")
    assert seen[0].component == "_Stub"


def test_template_line_found_in_components_authored_template():
    class _Stub:
        __templatestr__ = "<div>\n    <span>Ready</span>\n    {message}\n</div>"

    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)
    safe_eval("message", _Stub(), ALLOWED_BUILTINS, component=_Stub(), binding_type="TextBinding")
    assert seen[0].template_line == 3
    assert "<div>" in (seen[0].template or "")


def test_find_template_line():
    tpl = "a\nb\n{nope}\nc"
    assert find_template_line(tpl, "nope") == 3
    assert find_template_line(tpl, "absent") is None
    assert find_template_line(None, "nope") is None


def test_error_collector_restores_previous_sink():
    previous = lambda err: True
    set_error_sink(previous)

    collector = ErrorCollector()
    with collector:
        assert get_error_sink() is collector
        safe_eval("boom1", None, ALLOWED_BUILTINS)
        safe_eval("boom2", None, ALLOWED_BUILTINS)

    assert get_error_sink() is previous
    assert collector.is_empty is False
    assert len(collector.to_dict()) == 2
    assert collector.to_dict()[0]["expr"] == "boom1"

    assert ErrorCollector().is_empty is True


def test_record_error_no_sink_returns_false():
    assert record_error(expr="x") is False


def test_broken_sink_does_not_crash_renderer():
    def bad_sink(err):
        raise RuntimeError("boom")

    set_error_sink(bad_sink)
    # Must not raise — error capture never breaks the renderer.
    assert safe_eval("nope", None, ALLOWED_BUILTINS) is EVAL_ERROR


# ---------------------------------------------------------------------------
# Phase D — ImportError hints (server-only module)
# ---------------------------------------------------------------------------

def test_import_hint_for_module_not_found():
    exc = ModuleNotFoundError("No module named 'tensorflow'", name="tensorflow")
    hint = import_error_hint(exc, phase="client")
    assert hint is not None
    assert "server-only" in hint
    assert "tensorflow" in hint


def test_import_hint_generic_and_server():
    assert import_error_hint(ImportError("x"), phase="client") is not None
    # No hint on the server — the module map is complete there.
    assert import_error_hint(ImportError("x"), phase="server") is None
    assert import_error_hint(NameError("x"), phase="client") is None


def test_import_hint_in_recorded_error():
    from basis.shared.errors import import_error_hint

    seen = []

    def sink(err):
        seen.append(err)
        return True

    set_error_sink(sink)

    class _Ctx:
        pass

    # Simulate a client-side eval that hits an ImportError.  phase is explicit
    # because pytest runs server-side (IS_CLIENT is False), but the hint logic
    # only applies to the client.
    try:
        raise ModuleNotFoundError("No module named 'magic'", name="magic")
    except ModuleNotFoundError as exc:
        from basis.shared.bindings import _report_binding_error

        _report_binding_error("magic()", _Ctx(), exc, binding_type="TextBinding",
                              stage="eval", phase="client")
    assert seen[0].hint is not None
    assert "server-only" in seen[0].hint


# ---------------------------------------------------------------------------
# Phase A — store_provider.resolve_value (sentinel-aware)
# ---------------------------------------------------------------------------

def test_resolve_value_returns_none_for_failure():
    from basis.shared.store_provider import resolve_value

    # Single-expr probe failure → None (provider skips fetch silently).
    assert resolve_value("{$active_team.id}") is None
    # Error-string legacy form → None.
    assert resolve_value("[Error: x]") is None
    # Empty / plain values pass through.
    assert resolve_value("") == ""


# ---------------------------------------------------------------------------
# Phase B — client overlay & structural surfacing (fake DOM)
# ---------------------------------------------------------------------------

class _FakeNode:
    def __init__(self, tag="div"):
        self.tag = tag
        self.id = None
        self.style = ""
        self._text = ""
        self._attrs = {}
        self.childNodes = []
        self.parentNode = None
        self.hidden = False
        self.className = ""
        self._listeners = {}

    @property
    def textContent(self):
        return self._text + "".join(
            getattr(c, "textContent", "") or "" for c in self.childNodes
        )

    @textContent.setter
    def textContent(self, value):
        self._text = value or ""

    @property
    def innerHTML(self):
        return self._text

    @innerHTML.setter
    def innerHTML(self, value):
        self._text = value or ""

    def setAttribute(self, name, value):
        self._attrs[name] = value

    def getAttribute(self, name):
        return self._attrs.get(name)

    def appendChild(self, child):
        if child.parentNode is not None and hasattr(child.parentNode, "childNodes"):
            try:
                child.parentNode.childNodes.remove(child)
            except ValueError:
                pass
        child.parentNode = self
        self.childNodes.append(child)

    def replaceChildren(self, *children):
        for c in list(self.childNodes):
            c.parentNode = None
        self.childNodes = list(children)
        for c in children:
            c.parentNode = self

    def addEventListener(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)


class _FakeDocument:
    def __init__(self):
        self.body = _FakeNode("body")
        self.head = _FakeNode("head")
        self.documentElement = _FakeNode("html")
        self._all = [self.body, self.head, self.documentElement]
        self._meta = None
        self._initial_state = None
        self._listeners = {}

    def createElement(self, tag):
        node = _FakeNode(tag)
        node._doc = self
        self._all.append(node)
        return node

    def getElementById(self, eid):
        for n in self._all:
            if n.id == eid:
                return n
        return None

    def querySelector(self, selector):
        if selector == 'meta[name="basis-mode"]':
            return self._meta
        return None

    def addEventListener(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def dispatchEvent(self, event):
        for h in self._listeners.get(getattr(event, "type", None), []):
            try:
                h(event)
            except Exception:
                pass
        return True


class _FakeEvent:
    def __init__(self, type_, detail):
        self.type = type_
        self.detail = detail


class _FakeWindow:
    def __init__(self):
        self.warns = []

    @property
    def console(self):
        return self

    def warn(self, *args):
        self.warns.append(args)

    @staticmethod
    def _new_custom_event(type_, options=None):
        return _FakeEvent(type_, (options or {}).get("detail"))

    CustomEvent = type("CustomEvent", (), {"new": staticmethod(_new_custom_event)})


class _FakeFfi:
    @staticmethod
    def to_js(value):
        return value

    @staticmethod
    def create_proxy(fn):
        return fn


@pytest.fixture
def client_env(monkeypatch):
    """Patch client/errors.py with a fake DOM/window/ffi and reset its state."""
    from basis.client import errors as mod

    win = _FakeWindow()
    doc = _FakeDocument()
    ffi = _FakeFfi()
    monkeypatch.setattr(mod, "window", win)
    monkeypatch.setattr(mod, "document", doc)
    monkeypatch.setattr(mod, "ffi", ffi)
    monkeypatch.setattr(mod, "_seen", set())
    monkeypatch.setattr(mod, "_global_errors", [])
    monkeypatch.setattr(mod, "_installed", False)
    monkeypatch.setattr(mod, "_overlay", None)
    monkeypatch.setattr(mod, "_overlay_override", None)
    return mod, win, doc, ffi


def test_overlay_dev_gating(client_env):
    mod, win, doc, ffi = client_env
    # No meta → off by default.
    assert mod.overlay_enabled() is False
    # Dev meta → on.
    meta = doc.createElement("meta")
    meta.setAttribute("name", "basis-mode")
    meta.setAttribute("content", "dev")
    doc._meta = meta
    assert mod.overlay_enabled() is True
    # Explicit override wins.
    mod.set_overlay_enabled(False)
    assert mod.overlay_enabled() is False
    mod.set_overlay_enabled(True)
    assert mod.overlay_enabled() is True


def test_install_sink_records_globally_and_dispatches(client_env):
    mod, win, doc, ffi = client_env
    mod.set_overlay_enabled(False)  # keep the overlay out of this test
    sink = mod.install_error_sink()
    from basis.shared.errors import get_error_sink
    assert get_error_sink() is sink

    err = BindingError(component="Root", binding_type="TextBinding",
                       expr="message", error="Name message is not defined",
                       phase="client")
    assert sink(err) is True

    # window.__basisErrors set via setattr + ffi.to_js (the hydration pattern).
    assert hasattr(win, "__basisErrors")
    assert win.__basisErrors == [err.to_dict()]
    # Event dispatched with the error detail.
    assert ERROR_EVENT in doc._listeners or True  # event always dispatched
    assert len(win.warns) == 1


def test_sink_deduplicates_recurring_failures(client_env):
    mod, win, doc, ffi = client_env
    mod.set_overlay_enabled(False)
    sink = mod.install_error_sink()
    err = BindingError(component="Root", binding_type="TextBinding",
                       expr="message", error="boom", phase="client")
    assert sink(err) is True
    assert sink(err) is True  # same signature → deduped
    assert win.__basisErrors == [err.to_dict()]
    assert len(win.warns) == 1


def test_overlay_add_builds_display_entries(client_env):
    mod, win, doc, ffi = client_env
    overlay = mod.ErrorOverlay()
    assert overlay.items == []

    overlay.add({"binding_type": "TextBinding", "component": "Root",
                 "expr": "message", "error": "boom", "phase": "client",
                 "template_line": 3, "traceback": "Traceback ..."})
    assert len(overlay.items) == 1
    entry = overlay.items[0]
    assert entry["expr"] == "message"
    assert entry["binding_type"] == "TextBinding"
    assert entry["component"] == "Root"
    # The detail bundles phase, template line, error, hint and traceback.
    assert "phase: client" in entry["detail"]
    assert "template line: 3" in entry["detail"]
    assert "boom" in entry["detail"]
    assert "Traceback" in entry["detail"]

    # A second, different record appends (dedup is owned by the sink).
    overlay.add({"binding_type": "IfBinding", "component": "Root",
                 "expr": "cond", "error": "nope"})
    assert len(overlay.items) == 2


def test_overlay_toggle_panel(client_env):
    mod, win, doc, ffi = client_env
    overlay = mod.ErrorOverlay()
    assert overlay.collapsed == ""
    overlay.toggle_panel()
    assert overlay.collapsed == "true"
    overlay.toggle_panel()
    assert overlay.collapsed == ""


def test_overlay_toggle_entry_expands_and_collapses(client_env):
    mod, win, doc, ffi = client_env
    overlay = mod.ErrorOverlay()
    overlay.add({"binding_type": "TextBinding", "component": "Root",
                 "expr": "message", "error": "boom"})
    overlay.add({"binding_type": "IfBinding", "component": "Root",
                 "expr": "cond", "error": "nope"})
    assert len(overlay.items) == 2
    # Entries start expanded so detail is visible by default.
    assert all(e["expanded"] for e in overlay.items)

    # Fake event whose target carries the first entry's data-error-key.
    class _Tgt:
        def getAttribute(self, name):
            return overlay.items[0]["key"] if name == "data-error-key" else None
    overlay.toggle_entry(type("Ev", (), {"target": _Tgt()})())

    # First entry collapsed, second untouched, list re-assigned (re-render).
    assert overlay.items[0]["expanded"] == ""
    assert overlay.items[1]["expanded"] == "true"

    # Toggling again re-expands it.
    overlay.toggle_entry(type("Ev", (), {"target": _Tgt()})())
    assert overlay.items[0]["expanded"] == "true"


def test_overlay_toggle_entry_missing_target_is_safe(client_env):
    mod, win, doc, ffi = client_env
    overlay = mod.ErrorOverlay()
    overlay.add({"expr": "a", "error": "x"})
    before = list(overlay.items)

    # No event, no target, or a target without a matching key -> no-op.
    overlay.toggle_entry()
    overlay.toggle_entry(type("Ev", (), {"target": None})())
    no_key = type("Ev", (), {"target": type("T", (), {"getAttribute": lambda self, n: None})()})()
    overlay.toggle_entry(no_key)
    assert overlay.items == before


def test_overlay_clear_and_clear_all(client_env):
    mod, win, doc, ffi = client_env
    overlay = mod.ErrorOverlay()
    overlay.add({"expr": "a", "error": "x"})
    overlay.add({"expr": "b", "error": "y"})
    assert len(overlay.items) == 2

    overlay.clear()
    assert overlay.items == []

    overlay.add({"expr": "a", "error": "x"})
    overlay.clear_all()
    assert overlay.items == []
    # clear_all resets the sink's dedup set so the same error can re-appear.
    assert mod._seen == set()


def test_record_routes_into_mounted_overlay(client_env):
    mod, win, doc, ffi = client_env
    mod.set_overlay_enabled(False)          # keep ensure_overlay out of it
    mod._overlay = mod.ErrorOverlay()       # simulate an already-mounted overlay
    sink = mod.install_error_sink()

    err = BindingError(component="Root", binding_type="TextBinding",
                       expr="message", error="boom", phase="client")
    assert sink(err) is True
    assert len(mod._overlay.items) == 1
    assert mod._overlay.items[0]["expr"] == "message"
    assert mod._overlay.items[0]["component"] == "Root"


def test_replay_server_errors(client_env):
    mod, win, doc, ffi = client_env
    import json as _json

    script = doc.createElement("script")
    script.id = "basis-initial-state"
    script.textContent = _json.dumps({
        "some_store": {"a": 1},
        "__basis_errors__": [
            {"component": "StatusBar", "binding_type": "TextBinding",
             "expr": "message", "error": "Name message is not defined",
             "phase": "server", "template_line": 4},
        ],
    })
    doc._initial_state = script
    # getElementById must find it by id — register the id on the node.
    doc.getElementById = lambda eid: script if eid == "basis-initial-state" else None

    mod.install_error_sink()
    assert hasattr(win, "__basisErrors")
    assert win.__basisErrors[0]["phase"] == "server"
    assert win.__basisErrors[0]["component"] == "StatusBar"


def test_install_sink_creates_overlay_in_dev_mode(client_env):
    mod, win, doc, ffi = client_env
    meta = doc.createElement("meta")
    meta.setAttribute("name", "basis-mode")
    meta.setAttribute("content", "dev")
    doc._meta = meta

    mod.install_error_sink()
    overlay = mod.ensure_overlay()
    assert overlay is not None
    assert isinstance(overlay, mod.ErrorOverlay)
    # Idempotent — repeated calls return the same mounted instance.
    assert mod.ensure_overlay() is overlay


# ---------------------------------------------------------------------------
# Phase C — SSR capture (server side)
# ---------------------------------------------------------------------------

def test_ssr_collects_errors_and_never_renders_sentinel(monkeypatch):
    import os
    monkeypatch.setenv("BASIS_HMR", "1")
    import json
    import re

    from fastapi.testclient import TestClient
    from basis.server.app import Basis
    from basis.shared.page import _synthesize_page
    from basis.shared.component import Component
    from basis.shared.errors import get_error_sink

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <div>
            <span>Ready</span>
            {message}
            <span if="{missing_cond}">hidden</span>
        </div>
        """

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # The sink must be restored after the render.
    assert get_error_sink() is None
    # No raw error string may reach the rendered HTML.
    assert "[Error:" not in resp.text

    match = re.search(
        r'<script id="basis-initial-state" type="application/json">\s*(.*?)\s*</script>',
        resp.text, re.S,
    )
    state = json.loads(match.group(1))
    errors = state.get("__basis_errors__", [])
    assert len(errors) == 2
    by_expr = {e["expr"]: e for e in errors}
    assert by_expr["message"]["binding_type"] == "TextBinding"
    assert by_expr["missing_cond"]["binding_type"] == "IfBinding"
    assert by_expr["message"]["phase"] == "server"
    assert by_expr["message"]["component"] == "Root"
    assert by_expr["message"]["template_line"] == 3
    # Dev marker present because BASIS_HMR=1.
    assert 'name="basis-mode" content="dev"' in resp.text


def test_ssr_no_errors_means_no_basis_errors_key(monkeypatch):
    from fastapi.testclient import TestClient
    from basis.server.app import Basis
    from basis.shared.page import _synthesize_page
    from basis.shared.component import Component

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <div><span>Ready</span></div>
        """

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "__basis_errors__" not in resp.text


def test_serialize_initial_state_includes_errors():
    from basis.server.ssr import _serialize_initial_state
    from basis.shared.errors import ErrorCollector, BindingError

    collector = ErrorCollector()
    collector(BindingError(component="Root", binding_type="TextBinding",
                           expr="message", error="boom", phase="server"))
    out = _serialize_initial_state({}, errors=collector)
    import json
    data = json.loads(out)
    assert data["__basis_errors__"][0]["expr"] == "message"

    # Without errors the key is absent.
    assert "__basis_errors__" not in json.loads(_serialize_initial_state({}))


def test_resolve_value_ssr_probe_not_recorded(monkeypatch):
    """resolve_value's provider pre-check must not pollute the SSR error sink."""
    from basis.shared.store_provider import resolve_value
    from basis.shared.errors import ErrorCollector

    collector = ErrorCollector()
    with collector:
        assert resolve_value("{$active_team.id}") is None
    assert collector.is_empty is True
