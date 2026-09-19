"""Numbers arriving from markup — what the value-shaped families share.

An attribute is text, and the framework's "unset" is the empty string, so every numeric
prop has to tell ``""`` apart from a real ``0`` and survive whatever an author typed.
"""


def number(raw, default=None):
    """*raw* as a float, or *default* when it is no number at all.

    ``bool`` is rejected on purpose: ``True`` is a state, not a quantity.
    """
    if raw is None or raw == "" or isinstance(raw, bool):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def plain(value):
    """*value* as text without a trailing ``.0`` or a float artefact.

    30.0 → "30", 0.1 + 0.2 → "0.3"; ``None`` renders as nothing.
    """
    if value is None:
        return ""
    return f"{round(value, 6):g}"
