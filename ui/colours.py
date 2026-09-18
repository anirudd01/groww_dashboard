"""Shared diverging colour scale for the heatmap tiles and the detail table.

One implementation so a sector tile and its constituent rows read the same:
percentage change drives the colour, zero is neutral, and intensity is relative
to the strongest move currently on screen.
"""

from typing import Optional, Sequence, Tuple

# Endpoints of the diverging ramp. Light ends sit next to zero, dark ends at the
# strongest move in either direction.
NEUTRAL = (242, 242, 242)
POSITIVE_LIGHT = (214, 240, 219)
POSITIVE_DARK = (11, 99, 31)
NEGATIVE_LIGHT = (250, 219, 217)
NEGATIVE_DARK = (139, 26, 26)

#: Colour scale never saturates below this move, so a flat day still shows
#: contrast instead of rendering as uniform grey.
MIN_SCALE_PCT = 0.75

TEXT_ON_LIGHT = "#111111"
TEXT_ON_DARK = "#ffffff"
TEXT_MUTED = "#666666"


def _hex(rgb: Tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _mix(start: Tuple[int, int, int], end: Tuple[int, int, int], t: float):
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(start, end))


def scale_limit(values: Sequence[Optional[float]], minimum: float = MIN_SCALE_PCT) -> float:
    """Symmetric +/- bound for a set of percentage changes."""
    magnitudes = [abs(v) for v in values if v is not None]
    return max([minimum] + magnitudes)


def change_colours(value: Optional[float], limit: float) -> Tuple[str, str]:
    """Background and text colour for one percentage change.

    ``value`` of ``None`` means "no data" and renders neutral - never as if it
    were a flat 0%. Intensity scales with ``|value| / limit``, so the strongest
    mover on screen is the darkest tile and small moves stay pale.
    """
    if value is None:
        return _hex(NEUTRAL), TEXT_MUTED

    limit = max(limit, 1e-9)
    intensity = min(1.0, abs(float(value)) / limit)

    if value > 0:
        rgb = _mix(POSITIVE_LIGHT, POSITIVE_DARK, intensity)
    elif value < 0:
        rgb = _mix(NEGATIVE_LIGHT, NEGATIVE_DARK, intensity)
    else:
        return _hex(NEUTRAL), TEXT_ON_LIGHT

    # Dark backgrounds need light text; the ramp crosses over around halfway.
    text = TEXT_ON_DARK if intensity > 0.55 else TEXT_ON_LIGHT
    return _hex(rgb), text


def change_background(value: Optional[float], limit: float) -> str:
    """CSS declaration for a table cell, as pandas Styler expects."""
    background, text = change_colours(value, limit)
    return f"background-color: {background}; color: {text};"
