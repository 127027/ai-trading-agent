#!/usr/bin/env python3
"""Run Freqtrade with Binance restricted to keyless public market metadata.

This adapter is research-only. It disables CCXT's authenticated currency metadata
lookup before Freqtrade creates its exchange objects and routes only Binance's
public Spot market metadata endpoints through data-api.binance.vision.
"""

from __future__ import annotations

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
        api = payload.setdefault("urls", {}).setdefault("api", {})
        api["public"] = PUBLIC_SPOT_API
        api["v1"] = PUBLIC_SPOT_API_V1
        return payload

    setattr(describe, "_ten_day_public_only", True)
    exchange_class.describe = describe


def patch_ccxt() -> None:
    """Patch the sync, async and websocket Binance classes used by Freqtrade."""
    from ccxt.binance import binance as sync_binance
    from ccxt.async_support.binance import binance as async_binance

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
