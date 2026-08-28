"""The `Theme` base — a theme is a plugin, classified as a theme.

Structurally a :class:`~basis.shared.plugin.BasisPlugin` (full plugin lifecycle:
entry-point discovery, static serving of css/fonts, ``requires``, revertible
registration), semantically a theme: it carries a
:class:`~basis.plugins.theme.schema.ThemeDefinition` manifest and sets
``kind = "theme"`` so the shared registry (and therefore the managers)
classifies it as a theme — it appears only in the theme manager, never the
plugin manager.

ROADMAP-THEMING.md §6.5.1.
"""

from basis.plugins.theme.schema import ThemeDefinition
from basis.shared.plugin import BasisPlugin


class Theme(BasisPlugin):
    """A BasisPlugin classified as a theme.

    ``include_plugin`` registers it like any plugin (the shared registry); the
    ``$themes`` catalog store (a ``kind``-filtered projection) lists it, and
    ``$theme.set_theme(definition.id)`` resolves + applies it. The built-in
    default theme is a ``Theme`` instance too, so community themes ride the
    identical path.
    """

    kind = "theme"

    def __init__(self, definition: ThemeDefinition, **plugin_kwargs):
        self.definition = definition
        definition.validate()  # loud errors on a broken manifest (P4)
        # Plugin names must be valid Python identifiers ($plugins.<name> DSL), so
        # derive one from the definition id (underscores, never hyphens).
        safe_id = definition.id.replace("-", "_").replace(".", "_")
        kwargs = {
            "prefix": "",
            "name": f"theme_{safe_id}",
            "requires": ["theme"],
            **plugin_kwargs,
        }
        super().__init__(**kwargs)
        # NOTE (isomorphism rule): a theme that ships css/fonts passes BOTH
        # ``static_dir`` (its package dir) and ``static_mount`` = "/" + the
        # package path (e.g. ``"/dracula_basis"``), so the client VFS name
        # equals the filesystem import name. Never derive the mount from the
        # id (``"/basis/themes/<id>"") — that breaks client imports.
        if self.static_dir is not None and not plugin_kwargs.get("static_mount"):
            # Default the mount to the top-level package of static_dir, the
            # same derivation ``include_plugin`` validates against.
            self.static_mount = "/" + _package_path(self.static_dir)


def _package_path(dir_path) -> str:
    """Top-level dotted package name containing *dir_path* (walking up
    ``__init__.py`` chain), for the default static mount."""
    parts = []
    current = dir_path.resolve()
    while (current / "__init__.py").exists():
        parts.append(current.name)
        current = current.parent
    return ".".join(reversed(parts)) if parts else ""
