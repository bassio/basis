"""Official theme plugin — the theming mechanism (ROADMAP-THEMING.md).

Moved out of the UI plugin (``basis.plugins.ui.theme``) into its own plugin on
the standard ``basis.plugins`` entry point ("everything is a plugin"), so the
``ui`` / ``shell`` plugins depend on it and third-party **theme packages**
(installable skins) are plugins contributing a ``ThemeDefinition``.

It provides:

- ``ThemeStore`` — the ``$theme`` control plane (reactive design tokens,
  ``dark_mode`` / ``toggle_dark_mode()``, ``set_theme``/``set_mode``/``set_accent``,
  cookie persistence via ``apply_request``/``persist_prefs``),
- ``ThemeProvider`` (``<ui-theme-provider>``) — injects the tokens as CSS
  variables on ``:root`` (+ ``data-theme`` / ``data-theme-mode`` hooks),
- ``ThemeDefinition`` / ``ThemeTokens`` — the declarative token schema,
- ``Theme`` — the plugin base for installable themes (``kind="theme"``),
- ``ThemeRegistryStore`` (``$themes``) — the theme catalog, a ``kind``-filtered
  slice of the shared registry (sibling of ``$plugins``),
- ``DEFAULT_DEFINITION`` / ``DEFAULT_TOKENS`` — the built-in ``basis`` theme.

Importing this package binds the canonical ``plugin`` instance and registers
``<ui-theme-provider>``; apps include ``<ui-theme-provider>`` once in their root
template to apply the tokens.
"""

from basis.plugins.theme.plugin import ThemePlugin, plugin as theme_plugin
from basis.plugins.theme.schema import (
    ThemeDefinition,
    ThemeTokens,
    TOKEN_SLOTS,
    css_var,
)
from basis.plugins.theme.default import DEFAULT_DEFINITION, DEFAULT_TOKENS
from basis.plugins.theme.store import ThemeStore, PREFS_COOKIE
from basis.plugins.theme.theme import Theme
from basis.plugins.theme.registry import ThemeRegistryStore, ensure_theme_registry
from basis.plugins.theme.provider import ThemeProvider

# The canonical module-level ``plugin`` variable (entry-point convention).
# Re-exposed explicitly: importing the package also binds the submodule
# ``basis.plugins.theme.plugin`` as a package attribute, which would shadow this
# otherwise (entry points must resolve the instance, not the submodule).
plugin = theme_plugin

__all__ = [
    "ThemePlugin",
    "plugin",
    "theme_plugin",
    "ThemeStore",
    "ThemeProvider",
    "ThemeDefinition",
    "ThemeTokens",
    "TOKEN_SLOTS",
    "css_var",
    "DEFAULT_DEFINITION",
    "DEFAULT_TOKENS",
    "Theme",
    "ThemeRegistryStore",
    "ensure_theme_registry",
    "PREFS_COOKIE",
]
