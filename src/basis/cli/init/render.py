"""Thin Jinja2 wrapper for the ``basis init`` template system.

Templates live under ``templates/`` as ``.j2`` files that mirror the generated
project tree. Jinja's delimiters (``{{ }}`` / ``{% %}`` / ``{# #}``) never
collide with Basis's single-brace ``{expr}`` reactivity, ``$store`` DSL, or
``@decorators`` — which is exactly why we use Jinja2 rather than a bespoke
placeholder language.

Render configuration (see ``build_environment``):

- ``keep_trailing_newline`` — generated files keep their final newline.
- ``trim_blocks`` + ``lstrip_blocks`` — a removed ``{% if %}`` branch leaves no
  blank-line gap in the generated file.
- ``StrictUndefined`` — any template referencing an unknown context key fails
  loudly (the generator contract: every key a template uses MUST be provided by
  ``layout.build_context``).
- ``autoescape=False`` — we generate source code, never HTML output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from jinja2 import BaseLoader, Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(__file__).parent / "templates"

_ENV: Environment | None = None


def build_environment(loader: BaseLoader | None = None) -> Environment:
    """A configured Jinja2 environment for code generation."""
    return Environment(
        loader=loader,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,
    )


def _default_env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = build_environment(FileSystemLoader(str(TEMPLATES_DIR)))
    return _ENV


def render_string(template_source: str, context: Mapping[str, Any]) -> str:
    """Render an inline template string with ``context`` (unit-test friendly)."""
    return build_environment().from_string(template_source).render(**context)


def render_template(source_name: str, context: Mapping[str, Any]) -> str:
    """Render one template file (path relative to ``TEMPLATES_DIR``)."""
    return _default_env().get_template(source_name).render(**context)
