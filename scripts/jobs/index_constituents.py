"""Download NSE's constituent lists and store them as the ``index_constituents`` set.

Runs first in every broker's ``--master``: the instrument ids each broker resolves are
the members of these lists. Source and sector labelling: ``market/index_constituents.py``.

niftyindices.com refuses a client that does not look like a browser (the connection is
dropped), so this uses one ``requests`` session with a browser User-Agent and opens the
home page before the CSVs, as a browser would. Five small requests, about a second.

Public files: no account, no credentials. Read-only.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from market import index_constituents as ic
from market import state_store

logger = logging.getLogger("index_constituents")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/csv,text/html,*/*"})
    session.get(ic.HOME_URL, timeout=30)
    return session


def fetch_list(session: requests.Session, filename: str) -> list:
    response = session.get(ic.CSV_URL.format(file=filename), timeout=30)
    response.raise_for_status()
    rows = ic.parse_csv(response.content.decode("utf-8-sig", errors="replace"))
    if not rows:
        raise ValueError(f"{filename} is empty")
    return rows


def run(db: Optional[str] = None) -> int:
    try:
        session = new_session()
        lists = {}
        for key, (label, filename) in ic.INDEX_FILES.items():
            lists[key] = fetch_list(session, filename)
            logger.info("  %-12s %3d stocks  (%s)", key, len(lists[key]), filename)
        banks = {row["symbol"] for row in fetch_list(session, ic.BANK_INDEX_FILE)}
    except (requests.RequestException, ValueError) as exc:
        stored = ic.load(db)
        logger.error("Could not download NSE's lists: %s", exc)
        logger.error("Keeping the stored lists (from %s).", stored.get("generated_at") if stored else "never - none stored")
        return 1

    document = ic.build_document(lists, banks, datetime.now(timezone.utc).isoformat())
    previous = (ic.load(db) or {}).get("indices") or {}
    for key, members in document["indices"].items():
        before = set(previous.get(key) or ())
        added, removed = sorted(set(members) - before), sorted(before - set(members))
        if before and (added or removed):
            logger.info("  %s changed: +%s  -%s", key, ", ".join(added) or "none", ", ".join(removed) or "none")
    ic.save(document, db)
    sectors = sorted({row["sector"] for members in document["indices"].values() for row in members.values()})
    logger.info("Stored %s in %s (%d sectors: %s)", ic.CONSTITUENTS_SET, db or state_store.db_path(),
                len(sectors), ", ".join(sectors))
    return 0
