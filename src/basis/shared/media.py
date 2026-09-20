"""Named CSS media queries as reactive fields.

``media()`` declares a query on a class attribute of a ``Store`` or a ``Component``::

    class LayoutStore(Store):
        narrow = media("(width <= 600px)")
        hover = media("(hover: hover)", default=True)

The declaring owner materialises a real boolean field under that name, so from then on it
serialises, hydrates and reacts like any other field — ``$layout.narrow`` in a template, or a
``@computed`` reading ``self.narrow``.

Only the browser can evaluate a query, so ``default`` is the neutral the two sides agree on:
server-rendered markup and the client's first paint match, and the first write the browser
causes is an ordinary DAG update. Declaring the same query string twice hands back the same
:class:`MediaQuery`, so the page holds one ``MediaQueryList`` and one ``change`` registration
per distinct query, however many owners ask about it.

The browser half belongs to ``basis.shared.events``, not here: a query is observed *through
its ``change`` event*, so ``media()`` is a **level** declaration on the query's
``MediaQueryList`` and ``@on_media(...)`` an **edge** declaration on the same registration.
Two facets of one observation, one lifetime, one place that knows how to attach and release
it.

Client-only in effect, importable everywhere in practice: without a browser nothing is
created and the declaration is inert.
"""

import sys

from basis.shared.events import Declaration, LevelDeclaration, on_global

IS_CLIENT = "pyscript" in sys.modules or "pyodide" in sys.modules

if IS_CLIENT:
    try:
        from pyscript import window  # type: ignore[reportMissingImports]  # client runtime only
    except ImportError:
        window = None
else:
    window = None


def media(query: str, *, default: bool = False) -> "MediaQuery":
    """Declare *query* as a reactive field on the owning class.

    *default* is the neutral both sides agree on before the browser is asked: the value true of
    the widest range of clients. ``False`` suits a width query; ``(hover: hover)`` wants
    ``True`` so a desktop render is already correct and touch is a client-only correction.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("media() requires a non-empty media query string")
    return MediaQuery(query.strip(), bool(default))


class MediaQuery(LevelDeclaration):
    """A declared media query — one instance per distinct query string.

    Declaration and browser object are the same thing, which is what makes the sharing fall out
    for free: whoever declares the string second gets the first one's instance, so the page
    never holds two ``MediaQueryList``s for one query.

    It holds no value of its own. The declaring owner materialises a real field under the
    attribute name, and because this defines ``__get__`` without ``__set__`` the instance dict
    shadows the class attribute from the first write on — leaving reads, writes, serialisation
    and hydration on the ordinary path.
    """

    _instance_registry = {}  # query string -> MediaQuery

    def __new__(cls, query: str, default: bool = False):
        existing = cls._instance_registry.get(query)
        if existing is not None:
            if existing.default is not default:
                raise ValueError(
                    f"media({query!r}) was already declared with "
                    f"default={existing.default!r}; one query has one neutral, because the "
                    "server and the client both render it before the browser answers."
                )
            return existing
        instance = super().__new__(cls)
        cls._instance_registry[query] = instance
        return instance

    def __init__(self, query: str, default: bool = False):
        if "query" in self.__dict__:  # a multiton hit runs __init__ again
            return
        super().__init__(default)
        self.query = query
        self.default = bool(default)
        self._mql = None

    def target(self):
        """The ``MediaQueryList`` for this query, created when the first subscriber arrives.

        The query string is the multiton key, so both facets of one query — the level
        ``media(...)`` declares and any ``@on_media(...)`` handler — share this object, and
        therefore one registration. A query nobody subscribes to creates nothing.
        """
        if window is None:
            return None
        if self._mql is None:
            self._mql = window.matchMedia(self.query)
        return self._mql

    def declarations(self) -> tuple:
        """The level this descriptor declares: the browser's answer, written into the field."""
        return (Declaration(
            "change",
            target=self.target,
            kind="level",
            derive=lambda event: bool(getattr(event, "matches", False)),
            neutral=self.default,
            resync=lambda target: bool(getattr(target, "matches", self.default)),
        ),)


class MediaEdge:
    """The edge of a query, as a matcher.

    ``change`` fires only when the answer *changes*, so ``matches`` is the direction: true is
    the query starting to match, false is it stopping.
    """

    def __init__(self, entering=False, leaving=False):
        if entering and leaving:
            raise ValueError("on_media() takes entering or leaving, not both")
        self.entering = bool(entering)
        self.leaving = bool(leaving)

    def matches(self, event) -> bool:
        if self.entering:
            return bool(getattr(event, "matches", False))
        if self.leaving:
            return not bool(getattr(event, "matches", False))
        return True


def on_media(query, *, entering=False, leaving=False, **kwargs):
    """Declare a handler for the *edge* of *query*: it started matching, or stopped.

    ``media(query)`` is the level — the value, for as long as it holds. This is the moment it
    flips, which is what a layout-sensitive control actually needs: a level cannot tell you that
    it just changed. Both ride one ``MediaQueryList``.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("on_media() requires a non-empty media query string")
    observation = MediaQuery(query.strip())
    return on_global("change", target=observation.target,
                     matcher=MediaEdge(entering, leaving), **kwargs)
