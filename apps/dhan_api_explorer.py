"""Dhan API explorer - send one market-movers request and look at exactly what comes back.

Two screens:

    Request  - build a ``POST /v2/data/marketmovers`` body from the controls (or edit the JSON by
               hand), send it, and see the reply as a table and as raw JSON, with the time it took
    Members  - for each Dhan stock universe chosen, take its gainers and losers and mark which
               members of a stored NSE index (Nifty 50 / Next 50) appear in it, next to the NSE
               sector. Shows what the rankings can and cannot tell you about classification

Nothing is stored and nothing runs until a button is pressed. Read-only: no orders.

This is the "Dhan API explorer" page of pulse_dashboard.py; running this file directly shows just it:

    streamlit run apps/dhan_api_explorer.py --server.port 8506
"""

import os as _os
import sys as _sys

# Repo root on the path, so `market` and `apps` import when this file is run directly.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import json
import time
from datetime import date

import pandas as pd
import streamlit as st

from apps.dhan_movers_dashboard import dhan_provider
from market import dhan_movers as dm
from market.universe import available_universes

VIEW_REQUEST, VIEW_MEMBERS = "Request", "Members"
KIND_LABELS = {dm.STOCKS: "Stocks", dm.STOCK_FUTURES: "Stock futures", dm.INDEX_FUTURES: "Index futures",
               dm.STOCK_OPTIONS: "Stock options", dm.INDEX_OPTIONS: "Index options"}
#: The NSE sector indices among Dhan's universes, the default columns of the Members screen.
SECTOR_UNIVERSES = ["Nifty Bank", "Nifty Private Bank", "Nifty PSU Bank", "Nifty IT", "Nifty Auto",
                    "Nifty Pharma", "Nifty FMCG", "Nifty Metal", "Nifty Energy", "Nifty Realty",
                    "Nifty Infra", "Nifty Media"]
TRIES = 3


# -- data --------------------------------------------------------------------


def send(body: dict) -> dict:
    """One raw call. Returns {ok, seconds, payload | error}; never raises."""
    started = time.perf_counter()
    try:
        payload = dhan_provider().market_movers(body)
        return {"ok": True, "seconds": time.perf_counter() - started, "payload": payload}
    except Exception as exc:  # noqa: BLE001 - shown in the UI
        return {"ok": False, "seconds": time.perf_counter() - started, "error": str(exc),
                "code": getattr(exc, "code", None)}


@st.cache_data(ttl="5m", show_spinner=False)
def ranking_rows(universe: str, category: str) -> list:
    """Raw ``data`` rows of one stock ranking (100 rows, the most Dhan returns), retried on a timeout."""
    body = dm.build_request(dm.STOCKS, category, universe=universe, limit=dm.MAX_LIMIT)
    error = None
    for attempt in range(TRIES):
        result = send(body)
        if result["ok"]:
            return result["payload"].get("data") or []
        if result.get("code") == dm.NO_DATA_CODE:
            return []
        error = result["error"]
        time.sleep(1 + attempt)
    raise RuntimeError(error)


# -- screens -----------------------------------------------------------------


def request_screen() -> None:
    with st.container(border=True):
        with st.container(horizontal=True):
            kind = st.selectbox("Instruments", list(KIND_LABELS), format_func=KIND_LABELS.get, key="api_kind")
            category = st.selectbox("Ranking", dm.CATEGORIES[kind], key=f"api_category_{kind}")
            limit = st.number_input("Limit", 1, dm.MAX_LIMIT, 20, key="api_limit")
        options = {"limit": int(limit)}
        with st.container(horizontal=True):
            if kind == dm.STOCKS:
                label = st.selectbox("Universe", list(dm.UNIVERSES), index=1, key="api_universe",
                                     help="The ones the Dhan Movers page uses. Type any other Dhan key on the right.")
                other = st.text_input("Or any Dhan universe key", key="api_universe_other", placeholder="e.g. NIFTY_FIN_SERVICE")
                options["universe"] = other.strip().upper() or dm.UNIVERSES[label]
            else:
                options["expiry"] = st.date_input("Expiry", dm.monthly_expiry(date.today()), key="api_expiry",
                                                  help="Derivative rankings are per expiry; the default is this month's.")
        body = dm.build_request(kind, category, **options)
        # Keyed by the body, so changing a control refreshes the editor while hand edits survive a rerun.
        text = st.text_area("Request body (edit freely, it is sent as written)", json.dumps(body, indent=2),
                            height=200, key=f"api_body_{json.dumps(body, sort_keys=True)}")
        if st.button("Send", icon=":material/send:", type="primary", key="api_send"):
            try:
                sent = json.loads(text)
            except ValueError as exc:
                st.error(f"The body is not valid JSON: {exc}", icon=":material/error:")
                return
            with st.spinner("Asking Dhan...", show_time=True):
                st.session_state.api_result = {"body": sent, **send(sent)}

    result = st.session_state.get("api_result")
    if not result:
        st.caption("Pick a request and press Send. `POST https://api.dhan.co/v2/data/marketmovers`")
        return
    with st.container(horizontal=True):
        st.metric("Status", "OK" if result["ok"] else (result.get("code") or "Error"), border=True)
        st.metric("Took", f"{result['seconds']:.2f} s", border=True)
        rows = (result.get("payload") or {}).get("data") or []
        st.metric("Rows", len(rows) if result["ok"] else "-", border=True)
    if not result["ok"]:
        st.error(result["error"], icon=":material/error:")
        st.json(result["body"], expanded=True)
        return
    table, raw, sent = st.tabs(["Table", "Raw JSON", "Request sent"])
    with table:
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, height=min(38 * len(rows) + 40, 640))
        else:
            st.info("Dhan answered with no rows.", icon=":material/inbox:")
    with raw:
        st.json(result["payload"], expanded=2)
        st.download_button("Download JSON", json.dumps(result["payload"], indent=2), "marketmovers.json",
                           "application/json", icon=":material/download:")
    with sent:
        st.json(result["body"], expanded=True)


def members_screen() -> None:
    stored = [u for u in available_universes() if not u.is_index_board]
    if not stored:
        st.error("No NSE index lists stored. Run 'python scripts/dhan.py --master' first.", icon=":material/error:")
        return
    with st.container(border=True):
        base = st.segmented_control("Compare against", [u.key for u in stored], default=stored[0].key, required=True,
                                    format_func=lambda k: next(u.label for u in stored if u.key == k), key="api_base")
        chosen = st.multiselect("Dhan universes (two calls each: gainers and losers)", list(dm.UNIVERSES),
                                default=SECTOR_UNIVERSES, key="api_members_universes")
        go = st.button("Fetch", icon=":material/download:", type="primary", key="api_members_go")
    if go:
        found, capped, errors = {}, [], {}
        progress = st.progress(0.0, "Asking Dhan...")
        for i, label in enumerate(chosen, 1):
            key = dm.UNIVERSES[label]
            try:
                members, cut = dm.universe_members(ranking_rows(key, dm.PRICE_GAINERS), ranking_rows(key, dm.PRICE_LOSERS))
                found[label] = members
                if cut:
                    capped.append(label)
            except Exception as exc:  # noqa: BLE001 - shown in the UI
                errors[label] = str(exc)
            progress.progress(i / max(len(chosen), 1), f"{label} ({i}/{len(chosen)})")
        progress.empty()
        st.session_state.api_members = {"base": base, "found": found, "capped": capped, "errors": errors}

    state = st.session_state.get("api_members")
    if not state:
        st.caption("Choose the Dhan universes to fetch and press Fetch. Each one is two calls (~1 s each).")
        return
    universe = next(u for u in stored if u.key == state["base"])
    found = state["found"]
    for label, error in state["errors"].items():
        st.warning(f"{label}: {error}", icon=":material/warning:")
    if state["capped"]:
        st.warning(f"Dhan returned 100 rows on a side for {', '.join(state['capped'])}: those lists may be cut short.",
                   icon=":material/warning:")

    frame = pd.DataFrame([{"Symbol": c.symbol, "NSE sector": c.sector,
                           **{label: c.symbol in members for label, members in found.items()}}
                          for c in universe.constituents])
    frame["Dhan universes"] = frame[list(found)].sum(axis=1) if found else 0
    none = frame[frame["Dhan universes"] == 0]
    several = frame[frame["Dhan universes"] > 1]
    with st.container(horizontal=True):
        st.metric(f"{universe.label} stocks", len(frame), border=True)
        st.metric("In none of these universes", len(none), border=True)
        st.metric("In two or more", len(several), border=True)
    st.caption("A tick means the stock appeared in that universe's gainers or losers. Dhan's rows carry no sector "
               "field: the NSE sector column comes from the stored NSE list, not from Dhan.")
    st.dataframe(frame.sort_values(["NSE sector", "Symbol"]), hide_index=True, height=min(38 * len(frame) + 40, 900),
                 column_config={label: st.column_config.CheckboxColumn(label, width="small") for label in found})

    sizes = pd.DataFrame([{"Dhan universe": label, "Members returned": len(members),
                           f"Also in {universe.label}": len(set(members) & set(universe.symbols)),
                           f"Not in {universe.label}": len(set(members) - set(universe.symbols))}
                          for label, members in found.items()])
    st.subheader("Universe sizes")
    st.dataframe(sizes, hide_index=True)


def main() -> None:
    st.title("Dhan API explorer")
    st.caption("Send a market-movers request and see Dhan's reply exactly as it comes back. Nothing is stored.")
    view = st.segmented_control("View", [VIEW_REQUEST, VIEW_MEMBERS], default=VIEW_REQUEST, required=True,
                                key="api_view", label_visibility="collapsed")
    try:
        dhan_provider()
    except Exception as exc:  # noqa: BLE001 - shown in the UI
        st.error(f"Could not connect to Dhan: {exc}", icon=":material/error:")
        return
    (request_screen if view == VIEW_REQUEST else members_screen)()


def page_dhan_api_explorer() -> None:
    main()


if __name__ == "__main__":
    st.set_page_config(page_title="Dhan API explorer", page_icon=":material/api:", layout="wide")
    main()
