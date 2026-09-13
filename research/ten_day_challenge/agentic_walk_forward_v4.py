"""Aggressive V5 wrapper around the six-raster agentic walk-forward engine.

The base six-raster logic remains unchanged. This wrapper replaces Raster 5 spot
accounting with a research-only Binance isolated-margin model, makes leverage an
adaptive pre-window decision, and writes completed trade-level signal evidence to
persistent memory only after the blind run is finished.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

import agentic_walk_forward as base
from evolution import classify_regime
from margin_model import MarginSpec, run_margin_window
from signal_learning import update_signal_memory
from walk_forward import choose_test_start, training_bounds


LAST_MARGIN_SIDECAR = "latest-margin-result.json"
_ORIGINAL_REPAIR = base.repair
_STALL_MARKER = "stalled subprocess watchdog timeout"


def _load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _tail(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    return "\n".join(
        log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
    )


def _watchdog_run_command(
    command: list[str], log_path: Path, *, env: dict[str, str] | None = None
) -> None:
    """Run Hyperopt with a hard watchdog so Raster 1 always regains control."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    effective_env = env or os.environ.copy()
    timeout_seconds = int(effective_env.get("TEN_DAY_SUBPROCESS_TIMEOUT_SECONDS", "1800"))
    try:
        with log_path.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
                env=effective_env,
                timeout=timeout_seconds,
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{_STALL_MARKER} after {timeout_seconds}s: {' '.join(command)}\n{_tail(log_path)}"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{_tail(log_path)}"
        )


def _ops_watchdog_repair(root: Path, log_text: str) -> list[str]:
    """Teach Raster 1 how to recover from a process that stopped making progress."""
    actions = list(_ORIGINAL_REPAIR(root, log_text))
    if _STALL_MARKER in log_text.lower():
        actions.append(
            "OpsWatchdog diagnosed and terminated a stalled research subprocess; "
            "return the same run to Raster 1, restore the clean candidate/checkpoint, "
            "and retry without consuming or changing the blind window"
        )
    return actions


def _regime_confidence(regime: dict[str, Any]) -> float:
    r30 = abs(float(regime.get("median_return_30d") or 0.0))
    r90 = abs(float(regime.get("median_return_90d") or 0.0))
    trend = abs(float(regime.get("median_trend_gap") or 0.0))
    vol = float(regime.get("median_annualized_vol_30d") or 0.0)
    directional = min(1.0, 2.5 * r30 + 1.5 * trend + 0.5 * r90)
    volatility_support = min(1.0, max(0.0, (vol - 0.25) / 0.9))
    return max(0.0, min(1.0, 0.70 * directional + 0.30 * volatility_support))


def _historical_leverage_score(
    state: dict[str, Any], leverage: int, regime_label: str
) -> float:
    history = state.get("leverage_history") or []
    matching = [
        item
        for item in history
        if int(item.get("leverage") or 0) == leverage
        and str(item.get("regime") or "") == regime_label
    ]
    if not matching:
        return 0.15
    hits = sum(1 for item in matching if bool(item.get("target_hit")))
    liquidations = sum(1 for item in matching if bool(item.get("liquidated")))
    avg_final = sum(float(item.get("final_balance") or 0.0) for item in matching) / len(matching)
    hit_rate = hits / len(matching)
    liquidation_rate = liquidations / len(matching)
    normalized_final = max(-1.0, min(1.0, (avg_final - 100.0) / 100.0))
    exploration = math.sqrt(1.0 / (len(matching) + 1.0))
    return 2.5 * hit_rate + 0.35 * normalized_final - 0.9 * liquidation_rate + 0.25 * exploration


def _select_leverage(
    challenge: dict[str, Any], state: dict[str, Any], regime: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    policy = challenge["leverage_research"]
    allowed = sorted({int(value) for value in policy["allowed_leverage"]})
    confidence = _regime_confidence(regime)
    label = str(regime.get("label") or "unknown")

    scores: dict[int, float] = {}
    for leverage in allowed:
        history_score = _historical_leverage_score(state, leverage, label)
        if leverage == 3:
            confidence_fit = 1.0 - confidence
        elif leverage == 5:
            confidence_fit = 1.0 - abs(confidence - 0.58) * 1.7
        else:
            confidence_fit = confidence
        aggression_bonus = (leverage / max(allowed)) * 0.20
        scores[leverage] = history_score + confidence_fit + aggression_bonus

    selected = max(allowed, key=lambda value: (scores[value], value))
    decision = {
        "selected_leverage": selected,
        "regime": label,
        "confidence": confidence,
        "scores": {str(key): value for key, value in scores.items()},
        "evidence_cutoff": regime.get("evidence_cutoff"),
        "blind_window_seen": False,
        "method": "regime_confidence_plus_leverage_outcome_memory",
    }
    return selected, decision


def _margin_run_window(window: Any, **kwargs: Any) -> Any:
    config = Path(kwargs["config"]).resolve()
    root = config.parents[2]
    research_root = root / "research" / "ten_day_challenge"
    challenge = _load(research_root / "challenge.json", {})
    selected = int(os.environ["TEN_DAY_RESEARCH_LEVERAGE"])
    decision = json.loads(os.environ["TEN_DAY_LEVERAGE_DECISION"])
    policy = challenge["leverage_research"]
    levels = policy["liquidation_margin_levels"]
    spec = MarginSpec(
        leverage=selected,
        liquidation_margin_level=float(levels[str(selected)]),
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
        "leverage_decision": decision,
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
    root = args.root.resolve()
    args.data_dir = args.data_dir.resolve()
    research_root = root / "research" / "ten_day_challenge"
    challenge = _load(research_root / "challenge.json", {})
    state = _load(research_root / "walk-forward-state.json", {})
    run_id = int(state.get("run_count") or 0) + 1
    test_start = choose_test_start(challenge, state, run_id)
    history_start, _, history_end = training_bounds(challenge, test_start)
    regime = classify_regime(
        args.data_dir,
        [str(item) for item in challenge["pairs"]],
        str(challenge["timeframe"]),
        history_start,
        history_end,
    )
    selected_leverage, leverage_decision = _select_leverage(challenge, state, regime)
    os.environ["TEN_DAY_RESEARCH_LEVERAGE"] = str(selected_leverage)
    os.environ["TEN_DAY_LEVERAGE_DECISION"] = json.dumps(leverage_decision, sort_keys=True)

    sidecar_path = research_root / LAST_MARGIN_SIDECAR
    sidecar_path.unlink(missing_ok=True)
    base.run_command = _watchdog_run_command
    base.repair = _ops_watchdog_repair
    base.run_window = _margin_run_window
    record = base.execute_one_run(args)

    sidecar = _load(sidecar_path, {})
    if not sidecar:
        raise RuntimeError("V5 run completed without isolated-margin evidence")
    if int(sidecar.get("leverage") or 0) != selected_leverage:
        raise RuntimeError("Raster 3/5 leverage mismatch in V5 research run")

    record["margin_model"] = sidecar
    record["research_product"] = sidecar.get("product")
    record["leverage_used"] = sidecar.get("leverage")
    record["leverage_decision"] = leverage_decision
    record["learning_generation"] = "contextual-signal-v5"

    run_path = (
        research_root
        / "results"
        / "agentic-walk-forward"
        / f"run-{int(record['run']):06d}"
        / "run.json"
    )
    _write(run_path, record)

    # Base Raster 6 stores run-level learning before the V5 margin sidecar is
    # attached. Now that the blind run is fully complete, add its trade-level
    # evidence to persistent memory for FUTURE runs only.
    memory_path = research_root / "research-memory.json"
    memory = _load(memory_path, {})
    update_signal_memory(memory, record)
    memory["schema_version"] = max(2, int(memory.get("schema_version") or 1))
    _write(memory_path, memory)

    state_path = research_root / "walk-forward-state.json"
    state = _load(state_path, {})
    state["last_run"] = record
    state["aggressive_v5_active"] = True
    state["learning_generation"] = "contextual-signal-v5"
    state["last_leverage_used"] = sidecar.get("leverage")
    state["ops_watchdog_policy"] = {
        "subprocess_timeout_seconds": int(
            os.environ.get("TEN_DAY_SUBPROCESS_TIMEOUT_SECONDS", "1800")
        ),
        "on_timeout": "terminate_record_return_same_run_to_raster_1_clean_retry",
        "blind_window_consumed_on_technical_timeout": False,
    }
    state.setdefault("leverage_history", []).append(
        {
            "run": int(record["run"]),
            "regime": str(regime.get("label") or "unknown"),
            "leverage": int(selected_leverage),
            "target_hit": bool(record.get("outcome") == "HIT"),
            "liquidated": bool(sidecar.get("liquidated")),
            "final_balance": float(record.get("final_balance") or 0.0),
        }
    )
    state["leverage_history"] = state["leverage_history"][-1000:]
    if record.get("outcome") == "HIT" and state.get("first_hit_run") is None:
        state["first_hit_run"] = int(record["run"])
        state["phase"] = "post_first_hit_holdout_measurement"
        state["holdout_runs_completed_after_first_hit"] = 0
    elif (
        state.get("first_hit_run") is not None
        and int(record["run"]) > int(state["first_hit_run"])
    ):
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