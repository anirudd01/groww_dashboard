"""Index constituents and their sectors, from NSE's own published lists.

niftyindices.com (NSE Indices Ltd, the index provider) publishes one CSV per index:
``Company Name, Industry, Symbol, Series, ISIN Code``. The scripts download them
(``python scripts/<broker>.py --master``) and store them as the ``index_constituents``
set in ``data/market.db``; ``market/universe.py`` reads that set. Nothing here touches
the network, and the dashboards never fetch the lists live.

Sector labels
-------------
The tile label is NSE's ``Industry`` (its macro-economic sector), with two changes:

* A few long names are shortened (``INDUSTRY_LABELS``) so the tiles stay readable,
  and so they match the labels ``market/index_mapping.py`` links the index tiles to.
* Banks are split out of Financial Services. NSE files both under "Financial
  Services"; a stock that is also in the Nifty Bank index is labelled "Banks",
  because a heatmap that lumps banks with NBFCs and insurers hides the biggest
  single move in the index. Nifty Bank's own list decides, so this needs no
  hand-kept list either.

Index member lists
------------------
The NSE Sectoral Indices board sizes each index tile by its free-float market cap,
the sum over its constituents' stored weights. ``INDEX_MEMBER_FILES`` names NSE's
list for every index tile; the same ``--master`` run stores just the symbols as the
``index_members`` section of this set (keyed by the tile's index symbol), and the
Dhan weights job weighs every symbol in them. They are not universes: nothing is
aggregated from them, and the drill-down still shows Nifty 50 members only.
"""

import csv
import io
from typing import Dict, Iterable, List, Optional, Tuple

from market import reference_store, state_store

#: The stored set.
CONSTITUENTS_SET = "index_constituents"

#: Where the lists come from. A session that has visited ``HOME_URL`` first is
#: what a browser looks like; a bare client is refused.
HOME_URL = "https://www.niftyindices.com/"
CSV_URL = "https://www.niftyindices.com/IndexConstituent/{file}"

#: Universe key -> (label, NSE file). Adding an index is one line here plus a
#: ``--master`` run; ``market/universe.py`` registers every key it finds stored.
INDEX_FILES: Dict[str, Tuple[str, str]] = {
    "NIFTY50": ("Nifty 50", "ind_nifty50list.csv"),
    "NIFTYNEXT50": ("Nifty Next 50", "ind_niftynext50list.csv"),
}

#: Only used to split banks out of Financial Services (see the module docstring).
BANK_INDEX_FILE = "ind_niftybanklist.csv"

#: Index tile symbol (``market/index_mapping.py``) -> NSE's constituent list. NSE only.
INDEX_MEMBER_FILES: Dict[str, str] = {
    "NIFTY AUTO": "ind_niftyautolist.csv",
    "BANKNIFTY": BANK_INDEX_FILE,
    "NIFTY CONSR DURBL": "ind_niftyconsumerdurableslist.csv",
    "FINNIFTY": "ind_niftyfinancelist.csv",
    "NIFTY FMCG": "ind_niftyfmcglist.csv",
    "NIFTY HEALTHCARE": "ind_niftyhealthcarelist.csv",
    "NIFTYIT": "ind_niftyitlist.csv",
    "NIFTY MEDIA": "ind_niftymedialist.csv",
    "NIFTY METAL": "ind_niftymetallist.csv",
    "NIFTY OIL AND GAS": "ind_niftyoilgaslist.csv",
    "NIFTY PHARMA": "ind_niftypharmalist.csv",
    "NIFTY PVT BANK": "ind_nifty_privatebanklist.csv",
    "NIFTY PSU BANK": "ind_niftypsubanklist.csv",
    "NIFTY REALTY": "ind_niftyrealtylist.csv",
    "NIFTY": "ind_nifty50list.csv",
    "NIFTYNXT50": "ind_niftynext50list.csv",
    "NIFTY 500": "ind_nifty500list.csv",
}

#: The section of the stored set holding those lists.
MEMBERS_SECTION = "index_members"

SECTOR_BANKS = "Banks"
FINANCIAL_SERVICES = "Financial Services"

#: NSE industry name -> tile label, where the NSE name is too long for a tile.
INDUSTRY_LABELS: Dict[str, str] = {
    "Automobile and Auto Components": "Automobile",
    "Fast Moving Consumer Goods": "FMCG",
    "Oil Gas & Consumable Fuels": "Oil, Gas & Consumable Fuels",
}

COLUMNS = ("Company Name", "Industry", "Symbol", "Series", "ISIN Code")


def parse_csv(text: str) -> List[dict]:
    """One NSE constituent CSV -> ``[{symbol, company, industry, series, isin}]``.

    Raises ValueError when the header is not NSE's, so an HTML error page saved
    as ``.csv`` is never stored as an empty index.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [name.strip() for name in reader.fieldnames or []]
    if not set(COLUMNS) <= set(header):
        raise ValueError(f"not an NSE constituent list (columns: {', '.join(header) or 'none'})")
    rows = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if row.get("Symbol"):
            rows.append({"symbol": row["Symbol"], "company": row["Company Name"], "industry": row["Industry"],
                         "series": row["Series"], "isin": row["ISIN Code"]})
    return rows


def sector_label(industry: str, is_bank: bool = False) -> str:
    """The tile label for an NSE industry (see the module docstring)."""
    if is_bank and industry == FINANCIAL_SERVICES:
        return SECTOR_BANKS
    return INDUSTRY_LABELS.get(industry, industry)


def build_document(lists: Dict[str, List[dict]], bank_symbols: Iterable[str], generated_at: str,
                   members: Optional[Dict[str, Iterable[str]]] = None) -> dict:
    """The set to store: each index's constituents with their sector label.

    ``members`` is index tile symbol -> constituent symbols (``INDEX_MEMBER_FILES``).
    """
    banks = set(bank_symbols)
    indices = {}
    for key, rows in lists.items():
        indices[key] = {row["symbol"]: {**row, "sector": sector_label(row["industry"], row["symbol"] in banks)}
                        for row in rows}
    return {
        "generated_at": generated_at,
        "source": "niftyindices.com constituent CSVs (NSE Indices Ltd)",
        "labels": {key: INDEX_FILES.get(key, (key, ""))[0] for key in lists},
        "bank_index_symbols": sorted(banks),
        "counts": {key: len(rows) for key, rows in lists.items()},
        "indices": indices,
        MEMBERS_SECTION: {symbol: sorted(set(rows)) for symbol, rows in (members or {}).items()},
    }


def save(document: dict, path: Optional[str] = None) -> int:
    return reference_store.save_document(CONSTITUENTS_SET, document, sections=(MEMBERS_SECTION,),
                                         nested=("indices",), path=path)


def load(path: Optional[str] = None) -> Optional[dict]:
    """The stored set, or None when no ``--master`` run has stored it on this machine."""
    return reference_store.load_document(CONSTITUENTS_SET, path or state_store.db_path())


def load_index_members(path: Optional[str] = None) -> Dict[str, List[str]]:
    """Index tile symbol -> its constituent symbols, as stored. Empty when none are."""
    stored = (load(path) or {}).get(MEMBERS_SECTION) or {}
    return {symbol: list(rows) for symbol, rows in stored.items() if isinstance(rows, list)}


def index_member_symbols(path: Optional[str] = None) -> List[str]:
    """Every stock in any stored index member list - what the weights job must also weigh."""
    return sorted({symbol for rows in load_index_members(path).values() for symbol in rows})
