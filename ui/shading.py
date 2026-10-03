"""Cell shading for gainers/losers tables, shared by the F&O and Dhan movers pages.

Green for gains, red for losses; the largest move in a table is the darkest, so a
quiet day and a violent one both show contrast within their own table.
"""

import pandas as pd

# (lightest, darkest) RGB for the smallest and largest move in a table.
GREEN_SHADES = ((198, 239, 206), (0, 110, 40))
RED_SHADES = ((255, 205, 205), (170, 10, 10))


def shade_change(column: pd.Series) -> list:
    """CSS styles for a column of percentage moves, for ``Styler.apply``."""
    biggest = column.abs().max()
    styles = []
    for value in column:
        if not value or not biggest:
            styles.append("")
            continue
        light, dark = GREEN_SHADES if value > 0 else RED_SHADES
        weight = abs(value) / biggest
        r, g, b = (round(lo + (hi - lo) * weight) for lo, hi in zip(light, dark))
        text = "#ffffff" if weight > 0.45 else "#1a1a1a"
        styles.append(f"background-color: rgb({r},{g},{b}); color: {text}; font-weight: 600")
    return styles
