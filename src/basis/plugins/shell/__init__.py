"""The official shell plugin.

Slot-based, shadcn copy-paste style: every component is a self-contained,
behavior-first custom element composed with the ``Stack`` primitive.

Primitives:
- ``Stack`` — the layout atom (positioned flex/grid container),
- ``Splitter`` — a drag-to-resize divider between any two Stack children,
  gated by an ``if=`` binding on a ``resizeable`` flag.

Default chrome (each in its own module):
- ``AppShell`` — the whole frame (title bar / workspace / status bar),
- ``TitleBar``, ``StatusBar``, ``Workspace``,
- ``Sidebar`` (``side="left" | "right"``) + ``SidebarLeft`` / ``SidebarRight``
  (thin distinct-tag subclasses for DX) + ``SidebarTrigger``,
- ``ActivityBar``, ``MainContainer``, ``TabsBar``.

Site (document-flow) layout:
- ``Header`` / ``Main`` / ``Footer`` (semantic ``<header>`` / ``<main>`` /
  ``<footer>`` skeletons) + ``SiteShell`` (a ``min-height: 100vh`` column —
  header / main / footer with normal page scrolling).

Responsive:
- Every part sizes itself through CSS custom properties and moves its compact
  behaviour into a ``@media`` block built from ``basis.shared.breakpoints``, so the
  frame rearranges for a phone in CSS alone — the markup is the same at any viewport
  (hydration-safe). ``<shell-stack layout="workbench">`` names the arrangement (the
  surface first, the rail as bottom navigation, sidebars as overlay drawers);
  ``$device.tier`` tells Python which tier the browser is in. See
  ``docs/04_components/shell-components.md``.

Importing this package registers every custom element. The plugin instance is
``plugin`` (also re-exported here, mirroring ``regions`` / ``ui``).
"""
from basis.plugins.shell.plugin import ShellPlugin, plugin as shell_plugin
from basis.plugins.shell.stack import Stack
from basis.plugins.shell.splitter import Splitter
from basis.plugins.shell.activity_bar import ActivityBar
from basis.plugins.shell.title_bar import TitleBar
from basis.plugins.shell.status_bar import StatusBar
from basis.plugins.shell.sidebar import Sidebar, SidebarLeft, SidebarRight, SidebarTrigger
from basis.plugins.shell.main_container import MainContainer
from basis.plugins.shell.tabs_bar import TabsBar
from basis.plugins.shell.workspace import Workspace
from basis.plugins.shell.app_shell import AppShell
from basis.plugins.shell.site import Header, Main, Footer, SiteShell

plugin = shell_plugin

__all__ = [
    "ShellPlugin",
    "plugin",
    "Stack",
    "Splitter",
    "ActivityBar",
    "AppShell",
    "TitleBar",
    "StatusBar",
    "Workspace",
    "Sidebar",
    "SidebarLeft",
    "SidebarRight",
    "SidebarTrigger",
    "MainContainer",
    "TabsBar",
    "Header",
    "Main",
    "Footer",
    "SiteShell",
]
