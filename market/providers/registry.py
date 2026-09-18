"""Provider registry - the single place that knows which brokers exist.

Preference order comes from config (``PULSE_MARKET_PROVIDERS``, default
``dhan,groww``). The live service walks the list in order and uses the first
broker that authenticates and resolves instruments, so Dhan is used when it is
configured and Groww is the fallback.

Adding Kite later: implement ``MarketDataProvider`` in ``market/providers/kite.py``
and add one line to ``PROVIDER_FACTORIES``.
"""

import logging
from typing import Callable, Dict, List

from market.providers.base import FeedHandle, InstrumentRef, MarketDataProvider

logger = logging.getLogger(__name__)


def _make_dhan() -> MarketDataProvider:
    from market.providers.dhan import DhanProvider

    return DhanProvider()


def _make_groww() -> MarketDataProvider:
    from market.providers.groww import GrowwProvider

    return GrowwProvider()


#: name -> factory. Kite/Zerodha goes here when implemented.
PROVIDER_FACTORIES: Dict[str, Callable[[], MarketDataProvider]] = {
    "dhan": _make_dhan,
    "groww": _make_groww,
}

#: Names accepted in config but not implemented yet - warned about, not fatal.
PLANNED_PROVIDERS = {"kite", "zerodha"}

DEFAULT_PROVIDER_ORDER = ("dhan", "groww")


def available_provider_names() -> List[str]:
    return sorted(PROVIDER_FACTORIES)


def build_providers(order: List[str]) -> List[MarketDataProvider]:
    """Instantiate providers in preference order, skipping unusable entries.

    Unknown names are logged and skipped rather than raising, so a typo in
    config degrades to "use the others" instead of breaking the dashboard.
    """
    providers: List[MarketDataProvider] = []
    for raw in order or DEFAULT_PROVIDER_ORDER:
        name = (raw or "").strip().lower()
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
]
