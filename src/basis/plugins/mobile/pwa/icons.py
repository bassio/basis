"""The app's icons — declared, or a generated placeholder.

An installable app needs icons, and an app that declares none should still be installable
rather than quietly unsupported. So the plugin serves a placeholder it can draw itself:
the theme's ``bg_primary`` (or its browser-chrome color) as the field and ``accent_color``
as a rounded mark, falling back to the field's contrast color when a token is not a
literal color — tokens are CSS values, and a theme is free to define them with
``light-dark()`` or a ``var()`` chain, neither of which can be rasterized.

The placeholder is deliberately a solid field plus a mark: no font rendering, no logo. It
exists so the install criteria are met out of the box, not to be a brand. An app with a
brand declares it — as a URL (used as given) or as a dict (``src``/``sizes``/``type``/
``purpose`` passed through), because only the app knows how large its own art is.

Everything here is stdlib: ``zlib`` + ``struct`` for the PNG, and no image library, so the
plugin adds no dependency and the same module imports in PyScript (the store imports it
for the head links).
"""

import binascii
import struct
import zlib
from functools import lru_cache

from basis.plugins.mobile.pwa import ICON_SIZES, ICON_URL

#: The manifest icon keys an app's dict entry may carry.
_ICON_KEYS = ("src", "sizes", "type", "purpose")

#: The field color when neither the theme nor its chrome color is a literal.
_DEFAULT_FIELD = "#f5f5f7"


# ── colors ─────────────────────────────────────────────────────────────────


def parse_color(value) -> tuple[int, int, int] | None:
    """A concrete ``RGB`` from a CSS color literal, or ``None``.

    Only the literal forms are understood (``#rgb``, ``#rrggbb``, ``rgb()``/``rgba()``):
    a token that resolves through ``light-dark()``/``var()``/``color-mix()`` has no single
    answer here, and guessing one would paint an icon nobody chose.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) == 8:  # #rrggbbaa — the alpha is dropped, the field stays opaque
            digits = digits[:6]
        if len(digits) != 6:
            return None
        try:
            return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    if text.startswith("rgb"):
        inner = text[text.find("(") + 1:text.rfind(")")]
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) < 3:
            return None
        try:
            channels = [int(float(p)) for p in parts[:3]]
        except ValueError:
            return None
        if any(c < 0 or c > 255 for c in channels):
            return None
        return tuple(channels)
    return None


def _luminance(color: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """The readable text color on a *color* field: dark on light, light on dark."""
    return (16, 18, 22) if _luminance(color) > 0.5 else (247, 247, 248)


def icon_colors(theme=None) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """The placeholder's ``(field, mark)`` from the theme, or its defaults.

    Tokens first (they are the theme's design intent), then the browser-chrome color, then
    a neutral field. A mark too close to its field falls back to the field's contrast
    color, so a theme whose accent matches its background still gets a legible icon.
    """
    field = (
        parse_color(_token(theme, "bg_primary"))
        or parse_color(_token(theme, "theme_color_light"))
        or parse_color(_DEFAULT_FIELD)
    )
    mark = parse_color(_token(theme, "accent_color"))
    if mark is None or abs(_luminance(mark) - _luminance(field)) < 0.25:
        mark = contrast_color(field)
    return field, mark


def _token(theme, name: str):
    """A theme store's public field, tolerating a store with fewer fields than expected."""
    return getattr(theme, name, None) if theme is not None else None


# ── the placeholder PNG ────────────────────────────────────────────────────


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", binascii.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _in_rounded_square(x: int, y: int, lo: int, hi: int, radius: int) -> bool:
    """Whether ``(x, y)`` is inside the square ``[lo, hi)`` with rounded corners.

    The shape is the inner rectangle grown by *radius*, so a point is inside exactly when
    its distance to that inner rectangle is at most *radius* — which is why clamping the
    point into the rectangle and measuring that distance is enough (and why only the four
    corner regions can ever fall outside it).
    """
    if not (lo <= x < hi and lo <= y < hi):
        return False
    nearest_x = min(max(x, lo + radius), hi - radius - 1)
    nearest_y = min(max(y, lo + radius), hi - radius - 1)
    dx, dy = x - nearest_x, y - nearest_y
    return dx * dx + dy * dy <= radius * radius


@lru_cache(maxsize=8)
def placeholder_png(size: int, field, mark) -> bytes:
    """A square PNG: the field, with a rounded ``mark`` block inside the safe area.

    Cached per ``(size, field, mark)`` — the pixels are a pure function of those three,
    and a page render asks for the same icon on every request.
    """
    inset = max(1, size // 6)
    radius = max(1, size // 8)
    lo, hi = inset, size - inset
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type: none
        for x in range(size):
            raw.extend(mark if _in_rounded_square(x, y, lo, hi, radius) else field)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit truecolor
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def generated_png(size: int, theme=None) -> bytes:
    """The placeholder for *size*, colored from *theme* (see :func:`icon_colors`)."""
    field, mark = icon_colors(theme)
    return placeholder_png(int(size), field, mark)


# ── the manifest's and the head's icon entries ─────────────────────────────


def icon_url(size: int) -> str:
    """The URL the placeholder for *size* is served at."""
    return ICON_URL.format(size=size)


def _normalize(item) -> dict | None:
    """One declared icon → a manifest entry, or ``None`` when it is unusable."""
    if isinstance(item, str):
        return {"src": item} if item else None
    if isinstance(item, dict):
        src = item.get("src")
        if not src:
            return None
        return {key: item[key] for key in _ICON_KEYS if item.get(key)}
    return None


def _generated_items() -> list[dict]:
    """The placeholder entries, derived from :data:`ICON_SIZES`.

    The largest size is the maskable one — Android masks it without upscaling — and every
    other entry is ``any``. Derived rather than spelled out so the manifest, the head
    links and the icon route's allowlist cannot drift apart.
    """
    sizes = tuple(ICON_SIZES)
    largest = max(sizes)
    return [
        {
            "src": icon_url(size),
            "sizes": f"{size}x{size}",
            "type": "image/png",
            "purpose": "any maskable" if size == largest else "any",
        }
        for size in sizes
    ]


def icon_items(store) -> list[dict]:
    """The manifest's ``icons``: the app's declaration, else the generated pair."""
    declared = [
        entry
        for entry in (_normalize(item) for item in (getattr(store, "icons", None) or []))
        if entry is not None
    ]
    return declared or _generated_items()


def icon_links(store) -> list[dict]:
    """The declared/generated icons as ``<link rel="icon">`` contributions."""
    return [
        {"src": item["src"], "type": item.get("type"), "sizes": item.get("sizes")}
        for item in icon_items(store)
    ]


def apple_touch_href(store) -> str | None:
    """The iOS home-screen icon: the app's, else the largest it declared, else the
    generated 192 (iOS scales it)."""
    declared = getattr(store, "apple_touch_icon", None)
    if declared:
        return declared
    entries = icon_items(store)
    if not entries:
        return None
    sized = [entry for entry in entries if entry.get("sizes")]
    if not sized:
        return entries[0]["src"]
    return max(sized, key=lambda entry: _size_px(entry["sizes"]))["src"]


def _size_px(sizes: str) -> int:
    """The largest pixel dimension in a manifest ``sizes`` value ("192x192" → 192)."""
    digits = "".join(ch if ch.isdigit() else " " for ch in str(sizes)).split()
    return max((int(d) for d in digits), default=0)
