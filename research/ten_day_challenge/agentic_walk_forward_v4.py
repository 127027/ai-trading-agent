"""Aggressive V4 wrapper around the six-raster agentic walk-forward engine.

The base six-raster logic remains unchanged. This wrapper replaces only Raster 5's
spot accounting with a research-only Binance isolated-margin model and persists
its leverage/liquidation evidence into each run record.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import agentic_walk_forward as base
from margin_model import MarginSpec, run_margin_window


LAST_MARGIN_SIDECAR = "latest-margin-result.json"


def _load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _select_leverage(challenge: dict[str, Any], state: dict[str, Any]) -> int:
    policy = challenge["leverage_research"]
    allowed = sorted({int(value) for value in policy["allowed_leverage"]})
    preferred = int(policy["preferred_leverage"])
    if preferred not in allowed:
        raise ValueError("preferred leverage must be in allowed_leverage")

    last_margin = (state.get("last_run") or {}).get("margin_model") or {}
    if not bool(last_margin.get("liquidated")):
        return preferred

    previous = int(last_margin.get("leverage") or preferred)
    lower = [value for value in allowed if value < previous]
    if lower:
        return max(lower)
    return preferred


def _margin_run_window(window: Any, **kwargs: Any) -> Any:
    config = Path(kwargs["config"]).resolve()
    root = config.parents[2]
    research_root = root / "research" / "ten_day_challenge"
    challenge = _load(research_root / "challenge.json", {})
    state = _load(research_root / "walk-forward-state.json", {})
    policy = challenge["leverage_research"]
    leverage = _select_leverage(challenge, state)
    levels = policy["liquidation_margin_levels"]
    spec = MarginSpec(
        leverage=leverage,
        liquidation_margin_level=float(levels[str(leverage)]),
        liquidation_fee_fraction=float(policy["liquidation_fee_fraction_of_repaid_debt"]),
        borrow_interest_apr=float(policy["borrow_interest_apr_proxy"]),
        product=str(policy["product"]),
        direction=str(policy["direction"]),
    )
    result, margin = run_margin_window(window, spec=spec, **kwargs)
    evidence = {
        **margin,
        "product": spec.product,
        "direction": spec.direction,
        "leverage": spec.leverage,
        "liquidation_margin_level": spec.liquidation_margin_level,
        "liquidation_fee_fraction": spec.liquidation_fee_fraction,
        "borrow_interest_apr_proxy": spec.borrow_interest_apr,
        "availability_evidence": policy["availability_evidence"],
        "research_only": True,
        "live_release_allowed": False,
        "model_is_not_spot_multiplier_only": True,
    }
    _write(research_root / LAST_MARGIN_SIDECAR, evidence)
    return result


def execute_one_run(args: argparse.Namespace) -> dict[str, Any]:
    base.run_window = _margin_run_window
    record = base.execute_one_run(args)

    root = args.root.resolve()
    research_root = root / "research" / "ten_day_challenge"
    sidecar = _load(research_root / LAST_MARGIN_SIDECAR, {})
    if not sidecar:
        raise RuntimeError("V4 run completed without isolated-margin evidence")

    record["margin_model"] = sidecar
    record["research_product"] = sidecar.get("product")
    record["leverage_used"] = sidecar.get("leverage")

    run_path = (
        research_root
        / "results"
        / "agentic-walk-forward"
        / f"run-{int(record['run']):06d}"
        / "run.json"
    )
    _write(run_path, record)

    state_path = research_root / "walk-forward-state.json"
    state = _load(state_path, {})
    state["last_run"] = record
    state["aggressive_v4_active"] = True
    if record.get("outcome") == "HIT" and state.get("first_hit_run") is None:
        state["first_hit_run"] = int(record["run"])
        state["phase"] = "post_first_hit_holdout_measurement"
        state["holdout_runs_completed_after_first_hit"] = 0
    elif state.get("first_hit_run") is not None and int(record["run"]) > int(state["first_hit_run"]):
        state["phase"] = "post_first_hit_holdout_measurement"
        state["holdout_runs_completed_after_first_hit"] = int(
            state.get("holdout_runs_completed_after_first_hit") or 0
        ) + 1
    else:
        state["phase"] = "search_first_200_hit"
    _write(state_path, state)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--python", default="python")
    parser.add_argument("--freqtrade", default="freqtrade")
    parser.add_argument("--max-raster-restarts", type=int, default=6)
    args = parser.parse_args()
    execute_one_run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
