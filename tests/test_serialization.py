"""Tests for the shared, plugin-extensible serializer (shared/serialization.py).

Covers the ``jsonable()`` projection boundary + the ``register_serializer`` /
``unregister_serializer`` registry: dispatch order (primitives → containers →
``__json__`` → registered handlers by MRO → ``model_dump`` → ``__dict__`` →
``None``), subclass/base shadowing, last-wins, revertibility, cycle guard, and
the ``Store.serialize()`` integration.
"""

import pytest

from basis.shared.serialization import (
    jsonable,
    register_serializer,
    unregister_serializer,
)
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Snapshot + restore the process-global handler registry.

    Framework code (e.g. ``basis.server.db``) registers handlers at import
    time; tests must not leak their own registrations into other tests or wipe
    the framework's. Save the pre-test state, clear, and restore after.
    """
    import basis.shared.serialization as s

    saved = dict(s._HANDLERS)
    s._HANDLERS.clear()
    yield
    s._HANDLERS.clear()
    s._HANDLERS.update(saved)


# ── primitives & containers ────────────────────────────────────────────────


def test_primitives_pass_through():
    assert jsonable(None) is None
    assert jsonable(1) == 1
    assert jsonable(1.5) == 1.5
    assert jsonable("hi") == "hi"
    assert jsonable(True) is True


def test_containers_recursed():
    assert jsonable([1, {"a": [2, 3]}]) == [1, {"a": [2, 3]}]
    assert jsonable((1, 2)) == [1, 2]
    assert jsonable({1, 2}) == [1, 2]


def test_cycle_guard():
    lst = []
    lst.append(lst)
    assert jsonable(lst) == [None]

    d = {"self": None}
    d["self"] = d
    assert jsonable(d) == {"self": None}


# ── __json__ protocol ──────────────────────────────────────────────────────


def test_json_dunder_honored():
    class Widget:
        def __init__(self, name):
            self.name = name

        def __json__(self):
            return {"name": self.name}

    assert jsonable(Widget("w")) == {"name": "w"}


def test_json_dunder_result_is_recursed():
    class Inner:
        def __json__(self):
            return {"v": 1}

    class Outer:
        def __json__(self):
            return {"inner": Inner()}

    assert jsonable(Outer()) == {"inner": {"v": 1}}


# ── registered handlers ────────────────────────────────────────────────────


def test_register_decorator_and_direct_forms():
    @register_serializer(for_type=complex)
    def _(v):
        return {"real": v.real, "imag": v.imag}

    assert jsonable(complex(1, 2)) == {"real": 1.0, "imag": 2.0}

    register_serializer(for_type=bytes, handler=lambda v: v.decode())
    assert jsonable(b"hi") == "hi"


def test_base_class_covers_subclasses_via_mro():
    class Animal:
        pass

    class Dog(Animal):
        def __init__(self, name):
            self.name = name

    @register_serializer(for_type=Animal)
    def _(a):
        return {"kind": a.__class__.__name__}

    assert jsonable(Dog("rex")) == {"kind": "Dog"}


def test_subclass_handler_shadows_base():
    class Animal:
        pass

    class Dog(Animal):
        pass

    @register_serializer(for_type=Animal)
    def _base(a):
        return "animal"

    @register_serializer(for_type=Dog)
    def _dog(d):
        return "dog"

    assert jsonable(Dog()) == "dog"
    assert jsonable(Animal()) == "animal"


def test_last_registration_wins():
    class Thing:
        pass

    @register_serializer(for_type=Thing)
    def _one(t):
        return 1

    register_serializer(for_type=Thing, handler=lambda t: 2)
    assert jsonable(Thing()) == 2


def test_unregister_removes_handler():
    class Thing:
        pass

    @register_serializer(for_type=Thing)
    def _h(t):
        return 1

    assert jsonable(Thing()) == 1
    unregister_serializer(Thing)
    # falls back to public __dict__ (empty) → {}
    assert jsonable(Thing()) == {}


def test_handler_result_is_recursed_into_other_handlers():
    class Point:
        def __init__(self, x):
            self.x = x

    class Line:
        def __init__(self, a, b):
            self.a, self.b = a, b

    @register_serializer(for_type=Point)
    def _(p):
        return {"x": p.x}

    @register_serializer(for_type=Line)
    def _(l):
        return {"a": l.a, "b": l.b}

    assert jsonable(Line(Point(1), Point(2))) == {"a": {"x": 1}, "b": {"x": 2}}


# ── generic fallbacks ──────────────────────────────────────────────────────


def test_model_dump_fallback():
    class FakeModel:
        def model_dump(self):
            return {"a": 1, "b": [2, 3]}

    assert jsonable(FakeModel()) == {"a": 1, "b": [2, 3]}


def test_dict_fallback():
    class Obj:
        def __init__(self):
            self.a = 1
            self._secret = 2

    assert jsonable(Obj()) == {"a": 1}


def test_unsupported_leaf_projects_to_none():
    class Opaque:
        __slots__ = ()

    assert jsonable(Opaque()) is None


def test_object_catch_all_raises():
    class Opaque:
        __slots__ = ()

    @register_serializer(for_type=object)
    def _strict(v):
        raise TypeError(f"no serializer for {type(v).__name__}")

    with pytest.raises(TypeError):
        jsonable(Opaque())


# ── db-layer SQLModel handler (the plugin pattern) ─────────────────────────


def test_db_layer_serialize_sqlmodel_handler():
    """The DB layer registers a SQLModel handler that jsonable dispatches to.

    ``_serialize_sqlmodel`` lives in ``basis/server/db.py`` (the db plugin
    pattern) — core ``jsonable`` stays free of sqlmodel. Registering for the
    ``SQLModel`` base covers every SQLModel subclass via MRO.
    """
    from sqlmodel import SQLModel, Field

    from basis.server.db import _serialize_sqlmodel

    register_serializer(for_type=SQLModel)(_serialize_sqlmodel)

    class Rec(SQLModel):
        id: int | None = Field(default=None, primary_key=True)
        text: str = "hi"

    rec = Rec(id=1, text="hello")
    assert jsonable(rec) == {"id": 1, "text": "hello"}


# ── Store.serialize() integration ──────────────────────────────────────────


def test_store_serialize_uses_jsonable():
    class Jsonish:
        def __json__(self):
            return {"ok": True}

    name = "test_serialization_store"
    Store._store_blueprints.pop(name, None)
    try:
        store = Store(name)
        store.__dict__["plain"] = 1
        store.__dict__["obj"] = Jsonish()
        store.__dict__["unsupported"] = object()
        state = store.serialize()
        assert state["plain"] == 1
        assert state["obj"] == {"ok": True}
        # unsupported leaf → deterministic None (explicit, not silently dropped)
        assert state["unsupported"] is None
    finally:
        Store._store_blueprints.pop(name, None)
