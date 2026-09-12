#!/usr/bin/env python3
"""Run Freqtrade with Binance restricted to keyless public market metadata.

This adapter is research-only. It blocks CCXT's authenticated Binance currency
metadata path before Freqtrade creates its exchange objects and restricts market
loading to public Spot exchange information from data-api.binance.vision.
"""

from __future__ import annotations

import inspect
import sys
import traceback
from collections.abc import Callable
from typing import Any

PUBLIC_SPOT_API = "https://data-api.binance.vision/api/v3"
PUBLIC_SPOT_API_V1 = "https://data-api.binance.vision/api/v1"


def enforce_public_market_state(instance: Any) -> None:
    """Re-apply public-only market settings at the actual CCXT call boundary."""
    # Freqtrade passes empty strings for dry-run credentials. CCXT 4.5.73 treats
    # an empty apiKey as present (`is not None`) and then requests authenticated
    # tokenized-equity metadata. Explicit None keeps the research exchange truly
    # keyless and prevents that irrelevant SAPI path from being scheduled.
    instance.apiKey = None
    instance.secret = None
    instance.has["fetchCurrencies"] = False
    instance.options["fetchMargins"] = False
    instance.options["fetchMarkets"] = {"types": ["spot"]}
    api = instance.urls.setdefault("api", {})
    api["public"] = PUBLIC_SPOT_API
    api["v1"] = PUBLIC_SPOT_API_V1
    instance.urls["apiBackup"] = dict(api)


def compact_stack() -> str:
    """Return a compact caller chain that survives rolling-window log truncation."""
    frames = traceback.extract_stack(limit=10)[:-1]
    return " > ".join(
        f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}:{frame.name}"
        for frame in frames
    )


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
        urls = payload.setdefault("urls", {})
        api = urls.setdefault("api", {})
        api["public"] = PUBLIC_SPOT_API
        api["v1"] = PUBLIC_SPOT_API_V1
        urls["apiBackup"] = dict(api)
        return payload

    describe._ten_day_public_only = True  # type: ignore[attr-defined]
    exchange_class.describe = describe

    original_fetch_markets = exchange_class.fetch_markets
    if inspect.iscoroutinefunction(original_fetch_markets):

        async def fetch_markets(
            self: Any, params: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            enforce_public_market_state(self)
            return await original_fetch_markets(self, params or {})

    else:

        def fetch_markets(
            self: Any, params: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            enforce_public_market_state(self)
            return original_fetch_markets(self, params or {})

    fetch_markets._ten_day_public_only = True  # type: ignore[attr-defined]
    exchange_class.fetch_markets = fetch_markets

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

    original_sign = exchange_class.sign

    def sign(
        self: Any,
        path: str,
        api: Any = "public",
        method: str = "GET",
        params: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        try:
            return original_sign(
                self,
                path,
                api,
                method,
                params or {},
                headers,
                body,
            )
        except Exception as exc:
            marker = f"TEN_DAY_SIGN_FAILURE path={path} api={api!r} method={method}"
            print(marker, file=sys.stderr)
            raise type(exc)(f"{exc}; {marker}") from exc

    sign._ten_day_public_only = True  # type: ignore[attr-defined]
    exchange_class.sign = sign

    original_check = exchange_class.check_required_credentials

    def check_required_credentials(self: Any, error: bool = True) -> bool:
        try:
            return bool(original_check(self, error))
        except Exception as exc:
            caller = compact_stack()
            marker = (
                "TEN_DAY_CREDENTIAL_FAILURE "
                f"class={type(self).__module__}.{type(self).__name__} "
                f"error={error} has_api_key={bool(getattr(self, 'apiKey', None))} "
                f"caller={caller}"
            )
            print(marker, file=sys.stderr)
            raise type(exc)(f"{exc}; {marker}") from exc

    check_required_credentials._ten_day_public_only = True  # type: ignore[attr-defined]
    exchange_class.check_required_credentials = check_required_credentials


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
    print("TEN_DAY_PUBLIC_ADAPTER_ACTIVE", file=sys.stderr)
    from freqtrade.main import main as freqtrade_main

    result = freqtrade_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
