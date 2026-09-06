"""Isomorphic, plugin-extensible JSON serialization.

Core knows only JSON primitives and a few generic fallbacks; type families are
taught to it via :func:`register_serializer`. The module lives in ``shared/`` so
the same pure-stdlib code runs on the server (SSR ``#basis-initial-state``, RPC
``new_state``) and in the browser (Pyodide VFS) — the isomorphism principle.

Dispatch order in :func:`jsonable`::

    JSON primitives
      → containers (cycle-guarded)
      → ``__json__`` (per-object opt-in protocol)
      → registered type handlers (MRO: a subclass shadows its base)
      → generic ``model_dump``/``dict``/``dataclasses.asdict``
      → public ``__dict__``
      → ``None`` (unsupported leaf — deterministic)

Plugins/apps register handlers for the type families they own (e.g. the DB layer
registers a ``SQLModel`` handler; an app registers ``datetime``/``UUID``). A
handler returns *anything* — :func:`jsonable` recurses into the result, so
handlers compose.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def json_dumps_script_safe(obj, **kwargs) -> str:
    """``json.dumps`` output that is safe to embed inside a ``<script>`` tag.

    The page template HTML-escapes interpolated text (``&`` → ``&amp;``), but
    script content is NOT entity-decoded by browsers — so a literal ``&``
    would hydrate as ``&amp;``. Escaping ``<``/``>``/``&`` as ``\\uXXXX``
    sequences keeps ``</script>`` from closing the tag and round-trips
    through ``json.loads`` back to the original characters.
    """
    return (
        json.dumps(obj, **kwargs)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

#: type -> handler. Later registrations replace earlier ones (last include
#: wins). Process-global, populated at boot / plugin-include time (single
#: threaded), so no locking is required.
_HANDLERS: dict[type, Callable[[Any], Any]] = {}


def register_serializer(
    for_type: type,
    handler: Callable[[Any], Any] | None = None,
) -> Callable[[Any], Any]:
    """Register a JSON handler for a type family (decorator or direct call).

    ``handler(obj)`` returns anything — :func:`jsonable` recurses into the
    result, so a handler may return a dict/list that itself contains objects
    (including objects with their own handlers).

    Dispatch is by MRO: registering a base class (e.g. ``SQLModel``) covers
    every subclass; registering a subclass shadows the base. Re-registering
    the same type replaces the handler (last include wins). Handlers run
    BEFORE the generic ``model_dump``/``__dict__`` fallbacks, so registering a
    type is how a plugin takes over serialization for that family.

    Example::

        @register_serializer(for_type=UUID)
        def _(v):
            return str(v)
    """

    def _register(h: Callable[[Any], Any]) -> Callable[[Any], Any]:
        _HANDLERS[for_type] = h
        return h

    return _register(handler) if handler is not None else _register


def unregister_serializer(for_type: type) -> None:
    """Remove a registered handler (plugins call this on shutdown to revert)."""
    _HANDLERS.pop(for_type, None)


def _model_export(value: Any) -> Any | None:
    """Generic model export: ``model_dump()`` / ``dict()`` / ``asdict``."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    try:
        import dataclasses

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return dataclasses.asdict(value)
    except Exception:
        pass
    return None


def jsonable(value: Any, _seen: set[int] | None = None) -> Any:
    """Return the JSON-safe form of *value* — the projection boundary.

    The result contains only JSON primitives, dicts and lists (nested values
    are recursed). Unsupported leaves project to ``None`` so the boundary is
    deterministic; register a handler to take over a type family, or a
    ``for_type=object`` catch-all to raise instead.
    """
    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    vid = id(value)
    if vid in _seen:
        return None
    _seen = _seen | {vid}

    if isinstance(value, (list, tuple, set)):
        return [jsonable(x, _seen) for x in value]
    if isinstance(value, dict):
        return {k: jsonable(v, _seen) for k, v in value.items()}

    # 1. Per-object opt-in protocol — the object knows itself best.
    if hasattr(value, "__json__"):
        return jsonable(value.__json__(), _seen)

    # 2. Registered type handlers — subclass shadows base (MRO order).
    for cls in type(value).__mro__:
        handler = _HANDLERS.get(cls)
        if handler is not None:
            return jsonable(handler(value), _seen)

    # 3. Generic model export (pydantic / SQLModel / dataclass).
    exported = _model_export(value)
    if exported is not None:
        return jsonable(exported, _seen)

    # 4. Generic fallback: public attributes.
    if hasattr(value, "__dict__"):
        return jsonable(
            {k: v for k, v in vars(value).items() if not k.startswith("_")},
            _seen,
        )

    # 5. Unsupported leaf → deterministic None.
    return None
