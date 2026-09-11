"""Formatting utilities for Indian currency and date formats."""

import re

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


def format_expiry_date(date_str: str) -> str:
    """
    Convert NSE date format (e.g., '26SEP24') to readable format (e.g., '2026 Sept 26').
    """
    if not date_str or len(date_str) < 5:
        return date_str

    try:
        day = date_str[:2]
        month_str = date_str[2:5].upper()
        year = date_str[5:]

        if month_str not in MONTH_DISPLAY_MAP:
            return date_str

        year_full = f"20{year}" if len(year) == 2 else year
        return f"{year_full} {MONTH_DISPLAY_MAP[month_str]} {day}"
    except Exception:
        return date_str


def format_expiry_short(symbol: str) -> str:
    """
    Extract a short "Month Day" expiry display (e.g. "Sept 26") from a trading
    symbol like 'EICHERMOT26SEP7900CE'. Returns "N/A" if no expiry pattern is found.
    """
    if not symbol:
        return "N/A"

    match = re.search(r'(\d{2})([A-Z]{3})', symbol.upper())
    if not match:
        return "N/A"

    day, month = match.groups()
    month_abbr = MONTH_DISPLAY_MAP.get(month, month)
    return f"{month_abbr} {int(day)}"


# ============= ANALYTICS FUNCTIONS =============

def extract_position_sentiment(symbol: str) -> dict:
    """
    Extract position sentiment from symbol string.
    Analyzes if position is bullish (Call) or bearish (Put).

    Returns dict with:
    - underlying: The asset name (e.g., 'GOLD', 'NIFTY', 'CRUDEOIL')
    - option_type: 'CALL' or 'PUT' (last 2 chars)
    - strike: Strike price extracted from symbol
    - sentiment: 'BULLISH' (Call) or 'BEARISH' (Put)
    - prediction: Human-readable prediction
    """
    if not symbol or len(symbol) < 2:
        return {
            "underlying": "N/A",
            "option_type": "N/A",
            "strike": "N/A",
            "sentiment": "N/A",
            "prediction": "Unable to parse"
        }

    # Extract option type from last 2 characters
    option_type_code = symbol[-2:].upper()

    if option_type_code == "CE":
        option_type = "CALL"
        sentiment = "BULLISH"
    elif option_type_code == "PE":
        option_type = "PUT"
        sentiment = "BEARISH"
    else:
        return {
            "underlying": symbol[:10],
            "option_type": "UNKNOWN",
            "strike": "N/A",
            "sentiment": "NEUTRAL",
            "prediction": "Unable to determine (not an option)"
        }

    # Extract strike price (last 4 digits before CE/PE)
    try:
        strike_match = re.search(r'(\d+)(CE|PE)$', symbol)
        if strike_match:
            strike = strike_match.group(1)
        else:
            strike = "N/A"
    except Exception:
        strike = "N/A"

    # Extract underlying asset (everything before expiry date pattern)
    # Pattern: Symbol + 2-digit day + 3-letter month + 2-digit year
    underlying_match = re.match(r'^([A-Z0-9]+?)(?:\d{2}[A-Z]{3}\d{2,4})', symbol)
    if underlying_match:
        underlying = underlying_match.group(1)
    else:
        underlying = symbol[:-7] if len(symbol) > 7 else symbol[:5]

    # Generate prediction
    if sentiment == "BULLISH":
        prediction = f"If {underlying} goes UP ↑, you make money"
    else:
        prediction = f"If {underlying} goes DOWN ↓, you make money"

    return {
        "underlying": underlying,
        "option_type": option_type,
        "strike": strike,
        "sentiment": sentiment,
        "prediction": prediction
    }


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
    Group positions by underlying asset, expiry date, AND call/put type.
    Returns aggregated data with separate rows for calls and puts.

    Returns list of dicts with:
    - underlying: Asset name
    - option_type: "CALL" or "PUT"
    - expiry: Expiry date formatted (Day Month only, e.g., "Oct 15")
    - position_count: Number of contracts in this group
    - total_pnl: Sum of P&L for all positions in group
    - total_pnl_pct: Average P&L % for group
    - total_invested: Sum of entry values
    - total_value: Sum of current values
    - symbols: List of symbols in group
    - pnl_arrow: 📈 for positive, 📉 for negative
    """
    # Group by (underlying, expiry, call/put type) - 3 dimensions!
    groups = {}

    for pos in positions:
        if pos.get("entry_value", 0.0) <= 0 and pos.get("total_value", 0.0) <= 0:
            continue  # Skip inactive positions

        symbol = pos.get("symbol", "")
        sentiment_info = extract_position_sentiment(symbol)
        underlying = sentiment_info.get("underlying", "UNKNOWN")
        option_type = sentiment_info.get("option_type", "UNKNOWN")  # CALL or PUT

        # Extract expiry from symbol: find pattern DD+MMM (e.g., "25SEP", "17OCT")
        expiry_match = re.search(r'(\d{2})([A-Z]{3})', symbol)
        if expiry_match:
            day, month = expiry_match.groups()
            expiry_key = f"{day}{month}"
            # Format as "Oct 15" (just day and month, no year)
            month_abbr = MONTH_DISPLAY_MAP.get(month, month)
            expiry_display = f"{month_abbr} {int(day)}"
        else:
            expiry_key = "UNKNOWN"
            expiry_display = "N/A"

        # Group key now includes call/put type
        group_key = (underlying, expiry_key, option_type)

        if group_key not in groups:
            groups[group_key] = {
                "underlying": underlying,
                "option_type": option_type,
                "expiry": expiry_display,
                "expiry_key": expiry_key,
                "total_pnl": 0.0,
                "total_invested": 0.0,
                "total_value": 0.0,
                "symbols": []
            }

        # Update group
        groups[group_key]["total_pnl"] += float(pos.get("unrealized_pnl", 0.0))
        groups[group_key]["total_invested"] += float(pos.get("entry_value", 0.0))
        groups[group_key]["total_value"] += float(pos.get("total_value", 0.0))
        groups[group_key]["symbols"].append(symbol)

    # Convert to list and calculate metrics
    result = []
    for (underlying, expiry_key, option_type), group in groups.items():
        # Calculate P&L %
        if group["total_invested"] > 0:
            pnl_pct = (group["total_pnl"] / group["total_invested"]) * 100.0
        else:
            pnl_pct = 0.0

        # P&L arrow emoji
        if group["total_pnl"] > 0:
            pnl_arrow = "📈"
        elif group["total_pnl"] < 0:
            pnl_arrow = "📉"
        else:
            pnl_arrow = "➡️"

        position_count = len(group["symbols"])

        result.append({
            "underlying": underlying,
            "option_type": option_type,
            "expiry": group["expiry"],
            "expiry_key": expiry_key,
            "position_count": position_count,
            "total_pnl": group["total_pnl"],
            "total_pnl_pct": pnl_pct,
            "total_invested": group["total_invested"],
            "total_value": group["total_value"],
            "symbols": group["symbols"],
            "pnl_arrow": pnl_arrow
        })

    # Sort: by underlying, then expiry, then type (calls first)
    result.sort(key=lambda x: (x["underlying"], x["expiry"], x["option_type"] == "PUT"))

    return result


def get_position_summary(positions: list) -> dict:
    """
    Analyze all positions and return portfolio sentiment summary.

    Returns dict with:
    - total_bullish: Count of bullish (Call) positions
    - total_bearish: Count of bearish (Put) positions
    - net_sentiment: Overall portfolio sentiment
    - bullish_underlying: Set of underlyings where user is bullish
    - bearish_underlying: Set of underlyings where user is bearish
    - conflicting: Underlyings where user has both calls and puts
    """
    bullish_count = 0
    bearish_count = 0
    bullish_underlying = set()
    bearish_underlying = set()

    for pos in positions:
        sentiment_info = extract_position_sentiment(pos.get("symbol", ""))
        underlying = sentiment_info.get("underlying", "")
        sentiment = sentiment_info.get("sentiment", "")

        if sentiment == "BULLISH":
            bullish_count += 1
            if underlying:
                bullish_underlying.add(underlying)
        elif sentiment == "BEARISH":
            bearish_count += 1
            if underlying:
                bearish_underlying.add(underlying)

    # Find conflicts (same underlying with both calls and puts)
    conflicting = bullish_underlying & bearish_underlying

    # Net sentiment
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
