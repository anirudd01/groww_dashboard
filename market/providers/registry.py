"""Provider registry - the single place that knows which brokers exist.

Preference order comes from config (``PULSE_MARKET_PROVIDERS``, default
``dhan,indmoney,groww,kite``). The live service walks the list in order and
uses the first broker that authenticates and resolves instruments, so Dhan is
used when it is configured, then INDmoney, then Groww, then Kite. Naming a
single broker (in config or with the dashboard's sidebar switch) pins the board
to that broker alone.

Adding a broker: implement ``MarketDataProvider`` in ``market/providers/<name>.py``
and add one line to ``PROVIDER_FACTORIES``.
"""

import logging
from typing import Callable, Dict, List

from market.providers.base import FeedHandle, InstrumentRef, MarketDataProvider

logger = logging.getLogger(__name__)


def _make_dhan() -> MarketDataProvider:
    from market.providers.dhan import DhanProvider

    return DhanProvider()


def _make_indmoney() -> MarketDataProvider:
    from market.providers.indmoney import IndMoneyProvider

    return IndMoneyProvider()


def _make_groww() -> MarketDataProvider:
    from market.providers.groww import GrowwProvider

    return GrowwProvider()


def _make_kite() -> MarketDataProvider:
    from market.providers.kite import KiteProvider

    return KiteProvider()


#: name -> factory.
PROVIDER_FACTORIES: Dict[str, Callable[[], MarketDataProvider]] = {
    "dhan": _make_dhan,
    "indmoney": _make_indmoney,
    "groww": _make_groww,
    "kite": _make_kite,
}

#: Other names people use for a broker. The app is INDmoney; its API is
#: branded INDstocks. Zerodha's API is Kite Connect.
PROVIDER_ALIASES: Dict[str, str] = {
    "indstocks": "indmoney",
    "ind_money": "indmoney",
    "zerodha": "kite",
    "kiteconnect": "kite",
}

#: Names accepted in config but not implemented yet - warned about, not fatal.
PLANNED_PROVIDERS: set = set()

#: Kite is last: it is the newest adapter and needs a browser login every
#: morning, so a board on "auto" should not stall waiting for it.
DEFAULT_PROVIDER_ORDER = ("dhan", "indmoney", "groww", "kite")


def available_provider_names() -> List[str]:
    return sorted(PROVIDER_FACTORIES)


def canonical_provider_name(raw: str) -> str:
    """Lowercased, trimmed, with aliases resolved. Unknown names pass through."""
    name = (raw or "").strip().lower()
    return PROVIDER_ALIASES.get(name, name)


def provider_label(name: str) -> str:
    """Display label for a provider name, without constructing the provider."""
    return {"dhan": "Dhan", "indmoney": "INDmoney", "groww": "Groww", "kite": "Kite"}.get(
        canonical_provider_name(name), name
    )


def build_providers(order: List[str]) -> List[MarketDataProvider]:
    """Instantiate providers in preference order, skipping unusable entries.

    Unknown names are logged and skipped rather than raising, so a typo in
    config degrades to "use the others" instead of breaking the dashboard.
    """
    providers: List[MarketDataProvider] = []
    for raw in order or DEFAULT_PROVIDER_ORDER:
        name = canonical_provider_name(raw)
        if not name:
            continue
        if name in PLANNED_PROVIDERS:
            logger.info("Provider %r is planned but not implemented yet - skipping", name)
            continue
        factory = PROVIDER_FACTORIES.get(name)
        if factory is None:
            logger.warning(
                "Unknown provider %r in configuration (known: %s) - skipping",
                name,
                ", ".join(available_provider_names()),
            )
            continue
        try:
            providers.append(factory())
        except Exception as e:
            logger.warning("Could not construct provider %r: %s", name, e)
    return providers


__all__ = [
    "FeedHandle",
    "InstrumentRef",
    "MarketDataProvider",
    "PROVIDER_FACTORIES",
    "DEFAULT_PROVIDER_ORDER",
    "available_provider_names",
    "build_providers",
    "canonical_provider_name",
    "provider_label",
]
