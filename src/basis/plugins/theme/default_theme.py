"""The built-in ``basis`` default theme, registered as a `Theme` plugin.

It rides the exact same path as a community theme package (a
``Theme(BasisPlugin)`` discovered through the ``basis.plugins`` entry point), so
the ``$themes`` catalog and the theme manager handle the default and community
themes identically — the framework dogfoods its own format
(ROADMAP-THEMING.md §6.5.1).
"""

from basis.plugins.theme.default import DEFAULT_DEFINITION
from basis.plugins.theme.theme import Theme

# The default theme — token-only (no css/fonts to serve), so no static_dir.
theme = Theme(definition=DEFAULT_DEFINITION)
