"""
Item 5 of the bindings review (BINDINGS-REVIEW.md): one name resolver.

``safe_eval`` desugars ``$store.x`` / ``#id.x`` itself when no cached tree is
supplied, and ``safe_format`` is the single interpolation entry point (the old
``safe_format_with_stores`` plus its ``$``/``#`` string fast-path are gone).
A missing ``#component.attr`` reference resolves to the falsy placeholder
(renders ``""``), matching the old tolerant behaviour.
"""

import basis.shared.base_component  # noqa: F401  (injects BaseComponent into ALLOWED_BUILTINS)

from basis.shared.bindings import ALLOWED_BUILTINS, safe_eval, safe_format
from basis.shared.expr import extract_dependencies
from basis.shared.store import Store


def test_safe_eval_desugars_store_without_cached_tree():
    Store("probe")
    Store._registry["probe"].value = 42
    # No precomputed tree: safe_eval desugars $store.value itself (the old
    # safe_format_with_stores string fast-path is gone).
    assert safe_eval("$probe.value", None, ALLOWED_BUILTINS) == 42


def test_safe_format_resolves_store_and_missing_component():
    Store("probe2")
    Store._registry["probe2"].name = "basis"
    assert safe_format("hi {$probe2.name}", None, ALLOWED_BUILTINS) == "hi basis"

    # A missing #component reference renders "" (the missing-ref placeholder),
    # never an error string — this is what the old fast-path returned.
    assert safe_format("x{#nope.attr}y", None, ALLOWED_BUILTINS) == "xy"


def test_safe_format_with_cached_ast_trees_still_works():
    # The binding path passes cached desugared trees; that must keep working.
    Store("t3")
    Store._registry["t3"].x = 7
    deps, trees = extract_dependencies("{$t3.x}", ALLOWED_BUILTINS)
    # extract_dependencies also flags the bare store ref ($t3) via its
    # Subscript fallback; the attr form is what we feed safe_format.
    assert "$t3.x" in deps
    assert "$t3.x" in trees
    assert safe_format("{$t3.x}", None, ALLOWED_BUILTINS, ast_trees=trees) == "7"
