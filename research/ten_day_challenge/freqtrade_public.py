#!/usr/bin/env python3
"""Run Freqtrade with Binance restricted to keyless public market metadata.

This adapter is research-only. It blocks CCXT's authenticated Binance currency
metadata path before Freqtrade creates its exchange objects and restricts market
loading to public Spot exchange information from data-api.binance.vision.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

PUBLIC_SPOT_API = "https://data-api.binance.vision/api/v3"
PUBLIC_SPOT_API_V1 = "https://data-api.binance.vision/api/v1"


def patch_binance_class(exchange_class: type[Any]) -> None:
    """Force one CCXT Binance class to use public-only Spot metadata."""
    original: Callable[..., dict[str, Any]] = exchange_class.describe
    if getattr(original, "_ten_day_public_only", False):
        return

    def describe(self: Any) -> dict[str, Any]:
        payload = original(self)
        payload.setdefault("has", {})["fetchCurrencies"] = False
        options = payload.setdefault("options", {})
        options["fetchMargins"] = False
        options["fetchMarkets"] = {"types": ["spot"]}
        api = payload.setdefault("urls", {}).setdefault("api", {})
        api["public"] = PUBLIC_SPOT_API
        api["v1"] = PUBLIC_SPOT_API_V1
        return payload

    describe._ten_day_public_only = True  # type: ignore[attr-defined]
    exchange_class.describe = describe

    original_fetch_currencies = exchange_class.fetch_currencies
    if inspect.iscoroutinefunction(original_fetch_currencies):

        async def fetch_currencies(
            self: Any, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            del self, params
            return {}

    else:

        def fetch_currencies(
            self: Any, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            del self, params
            return {}

    fetch_currencies._ten_day_public_only = True  # type: ignore[attr-defined]
    exchange_class.fetch_currencies = fetch_currencies


def patch_ccxt() -> None:
    """Patch the sync, async and websocket Binance classes used by Freqtrade."""
    from ccxt.async_support.binance import binance as async_binance
    from ccxt.binance import binance as sync_binance

    patch_binance_class(sync_binance)
    patch_binance_class(async_binance)

    try:
        from ccxt.pro.binance import binance as pro_binance
    except (ImportError, ModuleNotFoundError):
        return
    patch_binance_class(pro_binance)


def main() -> int:
    patch_ccxt()
    from freqtrade.main import main as freqtrade_main

    result = freqtrade_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
