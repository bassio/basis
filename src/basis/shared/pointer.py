"""Input-capability media queries — the pointer counterpart of ``breakpoints``.

Hover is **decoration** in Basis. It may add emphasis; it may never be the only way
to see or reach something, because a touch engine answers ``:hover`` on tap and —
unlike a mouse — never un-answers it. An unguarded hover rule therefore latches as a
stuck style on a phone, and a hover-*revealed* affordance is simply unreachable.

Component styles put their hover rules inside an explicit ``@media (hover: hover)``
guard. The constants here are the single source that guard text, ``$device``'s
declared capability fields and the audit test all speak, so they cannot drift.

``pointer`` rather than ``hover`` answers the SIZING question ("is the primary input
a finger?"): a touchscreen laptop whose primary pointer is a mouse stays ``fine`` and
keeps its dense controls, while a phone is ``coarse`` and gets touch targets.
"""
from __future__ import annotations

#: A fine pointer that can hover — the desktop/laptop default.
HOVER_QUERY = "(hover: hover)"

#: No hover at all: a phone, or a device whose primary pointer cannot hover.
NO_HOVER_QUERY = "(hover: none)"

#: The primary input is a finger.
COARSE_QUERY = "(pointer: coarse)"

#: Every pointer query the framework speaks (the audit test checks component CSS
#: against this set).
POINTER_QUERIES = (HOVER_QUERY, NO_HOVER_QUERY, COARSE_QUERY)

#: The touch-target floor, and the fallback for the ``--touch-target`` theme token:
#: a page rendered without a theme provider still gets finger-sized controls.
TOUCH_TARGET = "44px"
