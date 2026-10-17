"""Formatting utilities for Indian currency, expiry dates and position direction."""

from datetime import datetime

from utils.constants import MONTH_DISPLAY_MAP


def format_inr(value: float, precision: int = 2) -> str:
    """
    Formats a number into Indian currency shorthand (Cr, L, K) or full standard format.
    Examples: 1453500 -> '₹14.54 L', 29700000 -> '₹2.97 Cr', 2296.1 -> '₹2.30 K'
    """
    if value is None:
        return "₹0.00"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 10_000_000:
        return f"{sign}₹{abs_val / 10_000_000:.{precision}f} Cr"
    elif abs_val >= 100_000:
        return f"{sign}₹{abs_val / 100_000:.{precision}f} L"
    elif abs_val >= 1_000:
        return f"{sign}₹{abs_val / 1_000:.{precision}f} K"
    else:
        return f"{sign}₹{abs_val:.{precision}f}"


def format_inr_full(value: float) -> str:
    """Full Indian comma-separated format, e.g. ₹14,53,500.00"""
    if value is None:
        return "₹0.00"
    s = f"{abs(value):.2f}"
    parts = s.split(".")
    int_part, dec_part = parts[0], parts[1]
    if len(int_part) > 3:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted_int = ",".join(groups) + "," + last3
    else:
        formatted_int = int_part
    sign = "-" if value < 0 else ""
    return f"{sign}₹{formatted_int}.{dec_part}"


def format_expiry_short(expiry_date) -> str:
    """'2026-10-27' -> 'Oct 27'; 'N/A' when the expiry is unknown.

    Takes the ``expiry_date`` the position processor read from Groww's instrument list. Expiries
    are never parsed from trading symbols: Groww uses three layouts (NIFTY26OCTFUT is year+month,
    NIFTY26O1918150CE is year+month letter+day, GOLD04DEC26FUT is day+month+year).
    """
    try:
        day = datetime.strptime(str(expiry_date), "%Y-%m-%d")
    except (TypeError, ValueError):
        return "N/A"
    return f"{MONTH_DISPLAY_MAP[day.strftime('%b').upper()]} {day.day}"


# ============= ANALYTICS FUNCTIONS =============

def position_sentiment(pos: dict) -> dict:
    """Which way a position profits, from its contract kind and the sign of its quantity.

    A bought call or a long future profits if the underlying rises; a sold call profits if it
    does not. ``kind`` (CALL, PUT, FUTURE) comes from the instrument list via the processor.

    Returns underlying, option_type (CALL / PUT / FUTURE / UNKNOWN), side (LONG / SHORT),
    sentiment (BULLISH / BEARISH / NEUTRAL) and a one-line prediction.
    """
    kind = pos.get("kind") or "UNKNOWN"
    quantity = pos.get("quantity") or 0
    underlying = pos.get("underlying") or pos.get("symbol") or "N/A"
    side = "LONG" if quantity > 0 else "SHORT" if quantity < 0 else "CLOSED"

    rises = {"CALL": True, "FUTURE": True, "PUT": False}.get(kind)
    if rises is None or side == "CLOSED":
        sentiment = "NEUTRAL"
    else:
        sentiment = "BULLISH" if rises == (side == "LONG") else "BEARISH"

    if sentiment == "BULLISH":
        prediction = f"If {underlying} goes UP ↑, you make money"
    elif sentiment == "BEARISH":
        prediction = f"If {underlying} goes DOWN ↓, you make money"
    else:
        prediction = "No directional exposure"
    return {"underlying": underlying, "option_type": kind, "side": side,
            "sentiment": sentiment, "prediction": prediction}


def get_sentiment_color(sentiment: str) -> str:
    """Return color for sentiment badge."""
    if sentiment == "BULLISH":
        return "🟢"
    elif sentiment == "BEARISH":
        return "🔴"
    else:
        return "⚪"


def group_positions_by_underlying_expiry(positions: list) -> list:
    """
    Group open positions by underlying, expiry, contract kind (CALL / PUT / FUTURE) and side.

    Returns list of dicts with:
    - underlying, option_type, side, asset_type (EQUITY / COMMODITY)
    - expiry: "Oct 27" display, expiry_key: ISO date (or "UNKNOWN")
    - position_count: Number of contracts in this group
    - total_invested: notional at entry of every open position (known without a price)
    - total_pnl / total_value: sums over the *priced* positions only
    - total_pnl_pct: total_pnl over the priced positions' notional
    - unpriced: how many positions in the group had no live price
    - symbols: List of symbols in group
    - pnl_arrow: 📈 for positive, 📉 for negative
    """
    groups = {}

    for pos in positions:
        if not pos.get("quantity"):
            continue  # closed today: realised P&L only, nothing open to group

        expiry_key = pos.get("expiry_date") or "UNKNOWN"
        sentiment = position_sentiment(pos)
        group_key = (pos.get("type", "UNKNOWN"), sentiment["underlying"], expiry_key,
                     sentiment["option_type"], sentiment["side"])

        group = groups.setdefault(group_key, {
            "asset_type": pos.get("type", "UNKNOWN"),
            "underlying": sentiment["underlying"],
            "option_type": sentiment["option_type"],
            "side": sentiment["side"],
            "expiry": format_expiry_short(pos.get("expiry_date")),
            "expiry_key": expiry_key,
            "total_pnl": 0.0,
            "total_invested": 0.0,
            "priced_invested": 0.0,
            "total_value": 0.0,
            "unpriced": 0,
            "symbols": [],
        })
        group["symbols"].append(pos.get("symbol", ""))
        group["total_invested"] += float(pos.get("entry_value") or 0.0)
        if pos.get("unrealized_pnl") is None:
            group["unpriced"] += 1
            continue
        group["total_pnl"] += float(pos["unrealized_pnl"])
        group["priced_invested"] += float(pos.get("entry_value") or 0.0)
        group["total_value"] += float(pos.get("total_value") or 0.0)

    result = []
    for group in groups.values():
        group["total_pnl_pct"] = (group["total_pnl"] / group["priced_invested"] * 100.0
                                  if group["priced_invested"] > 0 else 0.0)
        group["pnl_arrow"] = "📈" if group["total_pnl"] > 0 else "📉" if group["total_pnl"] < 0 else "➡️"
        group["position_count"] = len(group["symbols"])
        result.append(group)

    # By underlying, then expiry date, then calls, puts, futures
    order = {"CALL": 0, "PUT": 1, "FUTURE": 2}
    result.sort(key=lambda g: (g["underlying"], g["expiry_key"], order.get(g["option_type"], 3), g["side"]))
    return result


def get_position_summary(positions: list) -> dict:
    """
    Directional summary of the open positions (closed ones are skipped).

    Returns dict with:
    - total_bullish / total_bearish: counts of positions that profit from a rise / a fall
    - net_sentiment: Overall portfolio sentiment
    - bullish_underlying / bearish_underlying: underlyings on each side
    - conflicting: Underlyings with exposure on both sides (hedges, straddles, spreads)
    """
    bullish_count = 0
    bearish_count = 0
    bullish_underlying = set()
    bearish_underlying = set()

    for pos in positions:
        if not pos.get("quantity"):
            continue
        info = position_sentiment(pos)
        if info["sentiment"] == "BULLISH":
            bullish_count += 1
            bullish_underlying.add(info["underlying"])
        elif info["sentiment"] == "BEARISH":
            bearish_count += 1
            bearish_underlying.add(info["underlying"])

    conflicting = bullish_underlying & bearish_underlying

    if bullish_count > bearish_count:
        net_sentiment = "BULLISH 🟢"
    elif bearish_count > bullish_count:
        net_sentiment = "BEARISH 🔴"
    else:
        net_sentiment = "NEUTRAL ⚪"

    return {
        "total_bullish": bullish_count,
        "total_bearish": bearish_count,
        "net_sentiment": net_sentiment,
        "bullish_underlying": bullish_underlying,
        "bearish_underlying": bearish_underlying,
        "conflicting": conflicting
    }
