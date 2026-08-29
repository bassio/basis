"""The official shell plugin — app-frame primitives + default chrome.

Serves the shell's component files (``Stack``, ``Splitter`` and the default
chrome parts) to the client and registers the ``basis.plugins.shell`` package
under the standard ``basis.plugins`` entry point, so it rides the same
discovery/lifecycle path as any third-party plugin.

P1 scope (ROADMAP-SHELL.md §10, simplified): behavior primitives + default
chrome, composed with the ``Stack`` primitive (slot-based, shadcn copy-paste
style). The ``$layout`` store plan is postponed. ``on_register`` is a no-op: the
shell has no boot-time state to claim yet.
"""
from pathlib import Path

from basis.shared.plugin import BasisPlugin


class ShellPlugin(BasisPlugin):
    """The shell plugin — no runtime dependencies (requires=[])."""

    def on_register(self, app) -> None:
        # P1: the shell only serves its component files; it owns no stores or
        # registry state at boot ($layout / $app_state are postponed).
        pass


plugin = ShellPlugin(
    prefix="",
    serving_dir=Path(__file__).parent,
    serving_mount="/basis/plugins/shell",
    name="shell",
    tags=None,
    requires=["theme"],
)
