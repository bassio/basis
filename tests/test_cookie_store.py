"""Unit tests for the shared ``CookieStore`` base (basis/shared/cookie_store.py).

Verifies the generic contract: a subclass declares ``cookie_name`` +
``persisted_fields`` (or overrides ``_payload`` / ``_apply_payload``) and gets
read-on-request / write-on-action cookie persistence for free, with automatic
dirty tracking — only changed prefs rewrite the cookie. ``$theme``'s
``basis_theme`` persistence is the dogfood consumer (test_theme_registry.py).
"""

import json
from types import SimpleNamespace

from basis.shared.cookie_store import CookieStore


class PrefsStore(CookieStore):
    cookie_name = "my_prefs"
    persisted_fields = ("volume", "muted")

    def __init__(self, name="prefs"):
        super().__init__(name)
        # Store-subclass footgun: never clobber SSR-hydrated values.
        if getattr(self, "_hydrated_from_ssr", False):
            return
        self.volume = 0.5
        self.muted = False
        # a public attr NOT in persisted_fields must never leak into the cookie
        self.other = "secret"


def _request(cookie_value, name="my_prefs"):
    cookies = {name: cookie_value} if cookie_value is not None else {}
    return SimpleNamespace(cookies=cookies)


def test_persist_prefs_writes_only_declared_fields():
    store = PrefsStore()
    store.volume = 0.8
    store._mark_dirty()
    pair = store.persist_prefs()
    assert pair is not None
    name, value = pair
    assert name == "my_prefs"
    assert json.loads(value) == {"volume": 0.8, "muted": False}
    assert "other" not in json.loads(value)


def test_persist_prefs_none_when_not_dirty():
    store = PrefsStore()
    assert store.persist_prefs() is None


def test_persist_prefs_clears_dirty_flag():
    store = PrefsStore()
    store._mark_dirty()
    store.persist_prefs()
    # only one cookie write per change — the flag resets after persist
    assert store.persist_prefs() is None


def test_apply_request_hydrates_declared_fields():
    store = PrefsStore()
    store.apply_request(_request(json.dumps({"volume": 0.2, "muted": True})))
    assert store.volume == 0.2
    assert store.muted is True
    # a field not present in the cookie is left alone
    assert store.other == "secret"


def test_apply_request_ignores_missing_or_malformed_cookie():
    store = PrefsStore()
    store.apply_request(_request(None))        # no cookie → no-op
    assert store.volume == 0.5
    store.apply_request(_request("not-json"))  # malformed → no-op
    assert store.volume == 0.5
    # a partial payload hydrates only the fields it carries
    store.apply_request(_request(json.dumps({"volume": 0.9})))
    assert store.volume == 0.9
    assert store.muted is False


def test_custom_payload_shape_via_override():
    """Subclasses can override _payload/_apply_payload for a custom shape (the
    pattern the theme store uses for bool coercion / definition resolution)."""

    class ShapeStore(CookieStore):
        cookie_name = "shape"

        def _payload(self):
            return {"upper": self.value.upper()}

        def _apply_payload(self, data):
            self.value = data.get("upper", "").lower()

    store = ShapeStore("shape")
    store.value = "hi"
    store._mark_dirty()
    _name, value = store.persist_prefs()
    assert json.loads(value) == {"upper": "HI"}
    store.apply_request(_request(json.dumps({"upper": "BYE"}), name="shape"))
    assert store.value == "bye"
