"""
basis/shared/errors.py
----------------------
Structured error capture for Basis bindings — the shared single source for how
a binding-evaluation failure is *represented*, *recorded*, and *surfaced*.

This module plays the same role for error reporting that
``basis/shared/hydration.py`` plays for hydration diagnostics: it is the single
source of truth, duck-typed so the exact same functions run in both worlds:

* server:  Python-side SSR rendering.  ``safe_eval`` / ``safe_format``
  record into an :class:`ErrorCollector` installed around each render, and the
  collected errors are serialized into ``#basis-initial-state`` under the
  ``__basis_errors__`` key.
* client:  the browser (Pyodide).  ``safe_eval`` records through the sink
  installed by ``basis.client.errors``, which publishes ``window.__basisErrors``
  and a ``basis-error`` ``CustomEvent`` and drives the dev-only overlay panel.

On failure the evaluation helpers RECORD a structured :class:`BindingError`
and return ``""`` (an empty, neutral value) so the literal ``[Error: ...]``
string can never reach the rendered DOM.  A ``[Error: ...]`` string is only
produced as a last resort when no sink is registered, so string-prefix checks
keep working alongside the structured API.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import sys

# Events/globals surfaced on the client, mirroring the hydration report
# (``basis-hydration-mismatch`` / ``__basisHydrationReport``).
ERROR_EVENT = "basis-error"
ERRORS_GLOBAL = "__basisErrors"

# Sentinel produced only when no error sink is registered.
ERROR_PREFIX = "[Error: "


class _BindingEvalError:
    """Sentinel returned by the eval helpers when a binding expression fails and
    an error sink consumed the record.

    It behaves like an empty/neutral value (falsy, ``str() == ""``) so direct
    callers (``AttributeBinding``, ``IfBinding``, …) never render the raw
    ``[Error: ...]`` string, while ``safe_format*`` can detect it by identity
    and abort the whole template to ``""`` instead of a partial result.
    """

    __slots__ = ()

    def __repr__(self):
        return "<binding eval error>"

    def __bool__(self):
        return False

    def __str__(self):
        return ""

    def __eq__(self, other):
        return isinstance(other, _BindingEvalError)


EVAL_ERROR = _BindingEvalError()


class _SilentEvalError:
    """Sentinel returned by the eval helpers when a binding expression fails
    with ``record=False`` (a silent *probe* — no sink is notified).

    Like :class:`_BindingEvalError` it is an empty/neutral value (falsy,
    ``str() == ""``), but it is also intentionally *equal to* ``""`` so probe
    callers that test ``result == ""`` (e.g. ``store_provider.resolve_value``)
    treat it as "cannot resolve yet".  The format helpers abort the whole
    template to ``""`` when a field yields it, so a silent probe never renders
    a partial string.
    """

    __slots__ = ()

    def __repr__(self):
        return "<silent eval error>"

    def __bool__(self):
        return False

    def __str__(self):
        return ""

    def __eq__(self, other):
        if isinstance(other, _SilentEvalError):
            return True
        if isinstance(other, str):
            return other == ""
        return False

    __hash__ = object.__hash__


# Returned (instead of EVAL_ERROR) when ``record=False`` and the expression
# failed: no sink is notified, but the caller can still detect the failure and
# abort a template to "".
SILENT_ERROR = _SilentEvalError()


def is_error_string(value) -> bool:
    """True for the ``[Error: ...]`` sentinel string."""
    return isinstance(value, str) and value.startswith(ERROR_PREFIX)


SERVER_ONLY_IMPORT_HINT = (
    "This module may be server-only — import it inside a @server_action "
    "or guard with IS_SERVER."
)


def import_error_hint(exc: BaseException, phase: str = "client") -> str | None:
    """Friendly hint for ImportError/ModuleNotFoundError on the client.

    These usually mean the module exists only in the server process (not in the
    Pyodide VFS).  Only meaningful client-side, where the module map is a
    subset of the server's.
    """
    if phase != "client":
        return None
    if isinstance(exc, ModuleNotFoundError):
        name = getattr(exc, "name", None)
        if name:
            return f"Module {name!r} may be server-only — " + (
                "import it inside a @server_action or guard with IS_SERVER."
            )
        return SERVER_ONLY_IMPORT_HINT
    if isinstance(exc, ImportError):
        return SERVER_ONLY_IMPORT_HINT
    return None


@dataclass(kw_only=True)
class BindingError:
    """A structured record of one failed binding evaluation."""

    component: str | None = None       # owning component class name
    binding_type: str | None = None    # e.g. "TextBinding", "AttributeBinding"
    expr: str = ""                     # the failing expression / field name
    template: str | None = None        # the raw template content evaluated
    error: str = ""                    # str(exception)
    traceback: str | None = None       # formatted traceback (best-effort)
    phase: str = "server"              # "server" (SSR) | "client" (Pyodide)
    template_line: int | None = None   # 1-based line in ``template`` (best-effort)
    hint: str | None = None            # friendly extra guidance (e.g. imports)

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "binding_type": self.binding_type,
            "expr": self.expr,
            "template": self.template,
            "error": self.error,
            "traceback": self.traceback,
            "phase": self.phase,
            "template_line": self.template_line,
            "hint": self.hint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BindingError":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def find_template_line(template: str | None, expr: str) -> int | None:
    """Best-effort 1-based line number of the first template line mentioning
    ``expr`` (or its ``{...}`` binding form).  Returns None when it cannot be
    determined.
    """
    if not template or not expr:
        return None
    lines = template.splitlines()
    # Docstring-style component templates begin with a blank line; number lines
    # relative to the first non-blank line so the reported line matches what
    # the author sees in their template.
    offset = 0
    for i, line in enumerate(lines):
        if line.strip():
            offset = i
            break
    for i, line in enumerate(lines):
        if expr in line or ("{" + expr + "}") in line:
            return (i - offset) + 1
    return None


# ---------------------------------------------------------------------------
# Error sink
# ---------------------------------------------------------------------------

_error_sink = None


def set_error_sink(fn) -> None:
    """Register the callable that consumes :class:`BindingError` records.

    ``fn(err)`` should return a truthy value to confirm it handled the record.
    Only one sink is active at a time (the SSR collector restores the previous
    one on exit).
    """
    global _error_sink
    _error_sink = fn


def get_error_sink():
    """The currently registered sink, or None."""
    return _error_sink


def record_error(**kwargs) -> bool:
    """Build a :class:`BindingError` and hand it to the registered sink.

    Returns True when a sink consumed it (callers then return the empty value),
    False when no sink is registered (callers keep the sentinel behaviour).
    A failing sink never raises — error capture must not crash the renderer.
    """
    sink = _error_sink
    if sink is None:
        return False
    err = BindingError(**kwargs)
    try:
        return bool(sink(err))
    except Exception:
        # A broken sink must not crash the renderer — and must not let a raw
        # ``[Error: ...]`` string through.  A registered sink (even one that
        # raised) counts as "handled": the caller returns the empty value.
        return True


class ErrorCollector:
    """A :class:`BindingError` sink used by SSR to collect every binding error
    raised while rendering a page.

    Usable as a context manager so the previously-registered sink (if any) is
    restored afterwards.  Errors are serialized into ``#basis-initial-state``
    via :meth:`to_dict` so the client overlay can surface server-side failures.
    """

    def __init__(self):
        self.errors: list[BindingError] = []
        self._prev = None

    def __call__(self, err: BindingError) -> bool:
        self.errors.append(err)
        return True

    def __enter__(self) -> "ErrorCollector":
        self._prev = get_error_sink()
        set_error_sink(self)
        return self

    def __exit__(self, *exc_info) -> bool:
        set_error_sink(self._prev)
        return False

    @property
    def is_empty(self) -> bool:
        return not self.errors

    def to_dict(self) -> list[dict]:
        return [e.to_dict() for e in self.errors]


# Re-export for convenience (keeps ``sys`` import used in Pyodide-compatible
# code paths that introspect import failures).
__all__ = [
    "BindingError",
    "ErrorCollector",
    "ERROR_EVENT",
    "ERRORS_GLOBAL",
    "ERROR_PREFIX",
    "EVAL_ERROR",
    "find_template_line",
    "get_error_sink",
    "import_error_hint",
    "is_error_string",
    "record_error",
    "set_error_sink",
    "SILENT_ERROR",
]
