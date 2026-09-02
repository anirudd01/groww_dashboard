"""Constants used across the FnO dashboard and API client."""

# Segment and Exchange Constants
SEGMENT_FNO = "FNO"
SEGMENT_COMMODITY = "COMMODITY"
SEGMENT_CASH = "CASH"

EXCHANGE_NSE = "NSE"
EXCHANGE_MCX = "MCX"

# Asset Type Classification
ASSET_TYPE_EQUITY = "EQUITY"
ASSET_TYPE_COMMODITY = "COMMODITY"

# Index Keywords (NSE - for equity classification)
INDEX_KEYWORDS = [
    "NIFTY",
    "BANK",
    "SENSEX",
    "FINNIFTY",
    "MIDCAP",
    "NSEINDEX"
]

# Commodity Keywords (MCX)
COMMODITY_KEYWORDS = [
    "GOLD",
    "SILVER",
    "CRUDE",
    "COPPER",
    "NICKEL",
    "ZINC",
    "LEAD",
    "ALUMINUM",
    "NATURALGAS",
    "COBALT",
    "COAL",
    "GOLDM",
    "SILVERM",
    "CRUDEOIL",
    "MCX_"
]

# Position Segments
POSITION_SEGMENTS = {
    SEGMENT_FNO: "NSE Equity/Index Derivatives",
    SEGMENT_COMMODITY: "MCX Commodity Derivatives",
    SEGMENT_CASH: "Equity Holdings"
}

# Greeks Symbols
GREEKS = {
    "DELTA": "Δ",
    "GAMMA": "Γ",
    "THETA": "Θ",
    "VEGA": "ν"
}

# Default Cache Duration (in seconds)
DEFAULT_CACHE_DURATION = 60

# Date Format Constants
MONTH_MAP = {
    'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
    'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
    'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
}

MONTH_DISPLAY_MAP = {
    'JAN': 'Jan', 'FEB': 'Feb', 'MAR': 'Mar', 'APR': 'Apr',
    'MAY': 'May', 'JUN': 'Jun', 'JUL': 'Jul', 'AUG': 'Aug',
    'SEP': 'Sept', 'OCT': 'Oct', 'NOV': 'Nov', 'DEC': 'Dec'
}

# Auth Modes
AUTH_MODE_TOTP = "TOTP"
AUTH_MODE_API_KEY = "API_KEY"
AUTH_MODE_TOKEN = "TOKEN"
