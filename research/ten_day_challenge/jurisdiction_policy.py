"""Fail-closed jurisdiction gate for Germany/Saarland retail research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_VERIFICATION_FIELDS = (
    "data_adapter_verified",
    "cost_model_verified",
    "margin_model_verified",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path) -> dict[str, Any]:
    research_root = root / "research/ten_day_challenge"
    challenge = load_json(research_root / "challenge.json")
    profile_name = str(challenge.get("jurisdiction_profile") or "")
    if not profile_name:
        raise RuntimeError("challenge has no jurisdiction_profile")
    profile = load_json(research_root / profile_name)

    if profile.get("jurisdiction") != "Germany":
        raise RuntimeError("research jurisdiction must be Germany")
    if profile.get("client_class") != "retail":
        raise RuntimeError("research client class must be retail")

    active: dict[str, Any] = {}
    for name, market in dict(profile.get("market_classes") or {}).items():
        if not bool(market.get("enabled_for_backtest")):
            continue
        missing = [
            field
            for field in REQUIRED_VERIFICATION_FIELDS
            if not bool(market.get(field))
        ]
        if missing:
            raise RuntimeError(
                f"market class {name!r} enabled without verification: {missing}"
            )
        active[name] = market

    if not active:
        raise RuntimeError("no verified German-retail market class is active")

    crypto_cap = int(
        profile["market_classes"]["crypto_cfd"]["max_leverage"]
    )
    if crypto_cap != 2:
        raise RuntimeError("German-retail crypto CFD leverage cap must remain 2x")

    return {
        "jurisdiction": profile["jurisdiction"],
        "region": profile.get("region"),
        "client_class": profile["client_class"],
        "active_market_classes": sorted(active),
        "research_only": True,
        "live_trading_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
