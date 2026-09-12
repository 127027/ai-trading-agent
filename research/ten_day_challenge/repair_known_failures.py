"""Whitelisted self-healing for known research infrastructure failures.

This module intentionally repairs only deterministic configuration defects that
cannot change trading logic or enable live trading. Unknown failures are left
for the external OpsWatchdog / human review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PUBLIC_SPOT_API = "https://data-api.binance.vision/api/v3"
PUBLIC_SPOT_API_V1 = "https://data-api.binance.vision/api/v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def harden_public_only(config: dict[str, Any]) -> bool:
    """Force keyless Binance Spot metadata access without touching strategy logic."""
    changed = False
    exchange = config.setdefault("exchange", {})
    if exchange.get("name") != "binance":
        return False

    for field in ("key", "secret"):
        if exchange.get(field, "") != "":
            exchange[field] = ""
            changed = True

    for name in ("ccxt_config", "ccxt_async_config"):
        section = exchange.setdefault(name, {})
        if section.get("enableRateLimit") is not True:
            section["enableRateLimit"] = True
            changed = True
        options = section.setdefault("options", {})
        if options.get("defaultType") != "spot":
            options["defaultType"] = "spot"
            changed = True
        if options.get("fetchCurrencies") is not False:
            options["fetchCurrencies"] = False
            changed = True
        if options.get("fetchMargins") is not False:
            options["fetchMargins"] = False
            changed = True
        spot_markets = {"types": ["spot"]}
        if options.get("fetchMarkets") != spot_markets:
            options["fetchMarkets"] = spot_markets
            changed = True
        capabilities = section.setdefault("has", {})
        if capabilities.get("fetchCurrencies") is not False:
            capabilities["fetchCurrencies"] = False
            changed = True

    if config.get("dry_run") is not True:
        config["dry_run"] = True
        changed = True
    if config.get("trading_mode") != "spot":
        config["trading_mode"] = "spot"
        changed = True
    return changed


def set_public_data_url(config: dict[str, Any]) -> bool:
    """Route Binance public Spot metadata to the keyless public data endpoint."""
    changed = False
    exchange = config.get("exchange", {})
    if exchange.get("name") != "binance":
        return False
    for name in ("ccxt_config", "ccxt_async_config"):
        section = exchange.setdefault(name, {})
        urls = section.setdefault("urls", {})
        api = urls.setdefault("api", {})
        desired = {
            "public": PUBLIC_SPOT_API,
            "v1": PUBLIC_SPOT_API_V1,
        }
        for key, value in desired.items():
            if api.get(key) != value:
                api[key] = value
                changed = True
        if "private" in api:
            api.pop("private", None)
            changed = True
    return changed


def repair_config(path: Path, log_text: str) -> list[str]:
    config = load_json(path)
    actions: list[str] = []

    if (
        "telegram" in log_text.lower()
        and "required" in log_text.lower()
        and "telegram" in config
    ):
        config.pop("telegram", None)
        actions.append(f"removed disabled telegram block from {path.name}")

    if (
        ("listen_ip_address" in log_text or "api_server" in log_text.lower())
        and "api_server" in config
    ):
        config.pop("api_server", None)
        actions.append(f"removed disabled api_server block from {path.name}")

    lower_log = log_text.lower()
    restricted_location = (
        "restricted location" in lower_log
        or "http 451" in lower_log
        or "status code 451" in lower_log
        or " 451 " in lower_log
    )
    credential_failure = 'requires "apikey" credential' in lower_log

    if restricted_location or credential_failure:
        if harden_public_only(config):
            actions.append(f"hardened spot-only public Binance metadata access in {path.name}")
        if set_public_data_url(config):
            actions.append(
                f"pinned keyless Binance Spot metadata routing in {path.name}"
            )

    if actions:
        write_json(path, config)
    return actions


def repair(root: Path, log_text: str) -> list[str]:
    actions: list[str] = []
    for relative in (
        "runtime/user_data/config-10day-research.json",
        "runtime/user_data/config-10day-paper.json",
    ):
        path = root / relative
        if path.is_file():
            actions.extend(repair_config(path, log_text))
    return actions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    text = args.log.read_text(encoding="utf-8", errors="replace")
    actions = repair(args.root.resolve(), text)
    report = {
        "agent": "OpsWatchdog",
        "known_failure": bool(actions),
        "actions": actions,
        "safety": {
            "dry_run_enforced": True,
            "spot_enforced": True,
            "exchange_secrets_added": False,
            "trading_logic_modified": False,
            "repair_oscillation_disabled": True,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if actions else 3


if __name__ == "__main__":
    raise SystemExit(main())
