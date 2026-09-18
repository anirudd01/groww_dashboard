"""Symbol -> sector classification for index constituents.

Groww's instrument master does NOT carry the sector classification this
dashboard needs, so the mapping is maintained here as plain data.

To update a sector: edit the dict below. Nothing else needs to change.
To add a new index (Phase 3, e.g. Nifty Next 50): add a new dict and
register it in ``market/universe.py``.
"""

from typing import Dict

# Sector names are free text - they are used verbatim as heatmap tile labels.
# Keeping them consistent across indices lets sectors merge cleanly when more
# than one index is loaded.
SECTOR_AUTOMOBILE = "Automobile"
SECTOR_BANKS = "Banks"
SECTOR_CAPITAL_GOODS = "Capital Goods"
SECTOR_CONSTRUCTION = "Construction"
SECTOR_CONSTRUCTION_MATERIALS = "Construction Materials"
SECTOR_CONSUMER_DURABLES = "Consumer Durables"
SECTOR_CONSUMER_SERVICES = "Consumer Services"
SECTOR_FINANCIAL_SERVICES = "Financial Services"
SECTOR_FMCG = "FMCG"
SECTOR_HEALTHCARE = "Healthcare"
SECTOR_IT = "Information Technology"
SECTOR_METALS = "Metals & Mining"
SECTOR_OIL_GAS = "Oil, Gas & Consumable Fuels"
SECTOR_POWER = "Power"
SECTOR_SERVICES = "Services"
SECTOR_TELECOM = "Telecommunication"


# --------------------------------------------------------------------------
# NIFTY 50
# --------------------------------------------------------------------------
# Reviewed against the NSE Nifty 50 constituent list. NSE reconstitutes the
# index periodically (typically March and September), so re-check this list
# after every reshuffle. `scripts/check_heatmap_universe.py` reports any symbol
# here that no longer resolves in Groww's instrument master.
NIFTY_50_SECTORS: Dict[str, str] = {
    "ADANIENT": SECTOR_METALS,
    "ADANIPORTS": SECTOR_SERVICES,
    "APOLLOHOSP": SECTOR_HEALTHCARE,
    "ASIANPAINT": SECTOR_CONSUMER_DURABLES,
    "AXISBANK": SECTOR_BANKS,
    "BAJAJ-AUTO": SECTOR_AUTOMOBILE,
    "BAJAJFINSV": SECTOR_FINANCIAL_SERVICES,
    "BAJFINANCE": SECTOR_FINANCIAL_SERVICES,
    "BEL": SECTOR_CAPITAL_GOODS,
    "BHARTIARTL": SECTOR_TELECOM,
    "CIPLA": SECTOR_HEALTHCARE,
    "COALINDIA": SECTOR_OIL_GAS,
    "DRREDDY": SECTOR_HEALTHCARE,
    "EICHERMOT": SECTOR_AUTOMOBILE,
    "ETERNAL": SECTOR_CONSUMER_SERVICES,
    "GRASIM": SECTOR_CONSTRUCTION_MATERIALS,
    "HCLTECH": SECTOR_IT,
    "HDFCBANK": SECTOR_BANKS,
    "HDFCLIFE": SECTOR_FINANCIAL_SERVICES,
    "HEROMOTOCO": SECTOR_AUTOMOBILE,
    "HINDALCO": SECTOR_METALS,
    "HINDUNILVR": SECTOR_FMCG,
    "ICICIBANK": SECTOR_BANKS,
    "INDUSINDBK": SECTOR_BANKS,
    "INFY": SECTOR_IT,
    "ITC": SECTOR_FMCG,
    "JIOFIN": SECTOR_FINANCIAL_SERVICES,
    "JSWSTEEL": SECTOR_METALS,
    "KOTAKBANK": SECTOR_BANKS,
    "LT": SECTOR_CONSTRUCTION,
    "M&M": SECTOR_AUTOMOBILE,
    "MARUTI": SECTOR_AUTOMOBILE,
    "NESTLEIND": SECTOR_FMCG,
    "NTPC": SECTOR_POWER,
    "ONGC": SECTOR_OIL_GAS,
    "POWERGRID": SECTOR_POWER,
    "RELIANCE": SECTOR_OIL_GAS,
    "SBILIFE": SECTOR_FINANCIAL_SERVICES,
    "SBIN": SECTOR_BANKS,
    "SHRIRAMFIN": SECTOR_FINANCIAL_SERVICES,
    "SUNPHARMA": SECTOR_HEALTHCARE,
    "TATACONSUM": SECTOR_FMCG,
    # Tata Motors demerged: TMPV (passenger vehicles) carries the original
    # ISIN INE155A01022 and is used here as the continuing index entity.
    # If NSE also includes TMCV (commercial vehicles), add it below.
    "TMPV": SECTOR_AUTOMOBILE,
    "TATASTEEL": SECTOR_METALS,
    "TCS": SECTOR_IT,
    "TECHM": SECTOR_IT,
    "TITAN": SECTOR_CONSUMER_DURABLES,
    "TRENT": SECTOR_CONSUMER_SERVICES,
    "ULTRACEMCO": SECTOR_CONSTRUCTION_MATERIALS,
    "WIPRO": SECTOR_IT,
}


# --------------------------------------------------------------------------
# NIFTY NEXT 50 - Phase 3 placeholder
# --------------------------------------------------------------------------
# Deliberately left empty: an out-of-date list is worse than no list. Fill it
# in and the universe registry will pick it up with no other code changes.
NIFTY_NEXT_50_SECTORS: Dict[str, str] = {}
