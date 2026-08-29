"""The official ``ambient`` theme — a calm, teal-accented alternative to the
default, shipped in-tree as the theme-package dogfood (ROADMAP-THEMING.md §6.5).

It is a plain ``Theme(BasisPlugin)`` (``kind=\"theme\"``) registered through the
standard ``basis.plugins`` entry point, so it exercises the exact same
discovery → ``$themes`` catalog → apply → disable path as any community theme
package. Token-only (no css/fonts to serve), so no ``serving_dir``.
"""

from basis.plugins.ambient.theme import definition, plugin

__all__ = ["definition", "plugin"]
