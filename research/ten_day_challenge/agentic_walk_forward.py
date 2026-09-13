"""Agentic six-raster walk-forward research cycle.

One run is one blind 10-day test.  The six rasters are not six backtests; they
are the reasoning/development pipeline around that one test.  Technical faults
always return to raster 1.  A valid MISS reaches raster 6, is learned from, and
then the entire next run starts again at raster 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from council import assemble_council, quant_review, risk_review, validation_review
from evolution import (
    classify_regime,
    extract_selected_family,
    initial_memory,
    load_json as load_memory_json,
    plan_hypothesis,
    update_memory_after_completed_run,
    write_json as write_memory_json,
)
from repair_known_failures import repair
from rolling_windows import Window, run_window, summarize
from walk_forward import (
    choose_test_start,
    health_gate,
    learning_directive,
    load_json,
    parameter_fingerprint,
    persist_state,
    restore_candidate,
    run_command,
    training_bounds,
    write_json,
)

RASTER_NAMES = {
    1: "OpsWatchdog",
    2: "EvidenceRegimeAgent",
    3: "EvolutionResearchAgent",
    4: "BuildValidationAgent",
    5: "QuantExperimentAgent",
    6: "TenDaySupervisor",
}
STRATEGY = "TenDayAdaptiveV2"


def set_raster(path: Path, state: dict[str, Any], run_id: int, raster: int) -> None:
    state["run_in_progress"] = run_id
    state["current_raster"] = raster
    state["current_agent"] = RASTER_NAMES[raster]
    state["raster_status"] = "running"
    persist_state(path, state)


def pass_raster(path: Path, state: dict[str, Any], run_id: int, raster: int, detail: str) -> None:
    state.setdefault("raster_history", []).append(
        {
            "run": run_id,
            "raster": raster,
            "agent": RASTER_NAMES[raster],
            "status": "passed",
            "detail": detail,
            "at_utc": datetime.now(UTC).isoformat(),
        }
    )
    state["raster_history"] = state["raster_history"][-600:]
    state["raster_status"] = "passed"
    state["next_raster"] = 1 if raster == 6 else raster + 1
    persist_state(path, state)


def epochs_for_plan(challenge: dict[str, Any], plan: dict[str, Any], state: dict[str, Any]) -> int:
    base = int(challenge["hyperopt_epochs_per_run"])
    directive = str(plan.get("learning_directive") or "")
    last = state.get("last_run") or {}
    if directive.startswith("near_target") or float(last.get("final_balance") or 0.0) >= 150.0:
        return max(base, int(base * 1.75))
    if int(last.get("trades") or 0) == 0:
        return max(base, int(base * 1.25))
    return base


def run_hyperopt(
    *,
    args: argparse.Namespace,
    root: Path,
    challenge: dict[str, Any],
    state: dict[str, Any],
    plan: dict[str, Any],
    run_id: int,
    attempt: int,
    optimize_start: date,
    test_start: date,
    parameter_file: Path,
    output_dir: Path,
) -> tuple[str, int, int]:
    seen = set(str(item) for item in state.get("parameter_fingerprints", []))
    directive = str(plan.get("learning_directive") or "initial_broad_search")
    epochs = epochs_for_plan(challenge, plan, state)
    plan_salt = int(hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:8], 16)
    retries = int(challenge.get("duplicate_fingerprint_retries", 8))
    timerange = f"{optimize_start:%Y%m%d}-{test_start:%Y%m%d}"

    for duplicate_attempt in range(retries + 1):
        seed = (
            int(challenge["search_seed_base"])
            + run_id * 1009
            + attempt * 97
            + duplicate_attempt * 7919
            + plan_salt % 100000
        )
        command = [
            args.freqtrade,
            "hyperopt",
            "--config",
            str(root / "runtime/user_data/config-10day-research.json"),
            "--userdir",
            str(root / "runtime/user_data"),
            "--strategy-path",
            str(root / "runtime/user_data/strategies/candidates"),
            "--data-dir",
            str(args.data_dir),
            "--strategy",
            STRATEGY,
            "--hyperopt-loss",
            "TenDayChallengeLoss",
            "--timerange",
            timerange,
            "--epochs",
            str(epochs),
            "--spaces",
            *[str(item) for item in challenge["hyperopt_spaces"]],
            "--fee",
            str(challenge["effective_backtest_fee_per_side"]),
            "--random-state",
            str(seed),
            "--enable-protections",
            "--analyze-per-epoch",
        ]
        env = os.environ.copy()
        env["TEN_DAY_LEARNING_DIRECTIVE"] = directive
        env["TEN_DAY_ALLOWED_FAMILIES"] = ",".join(plan["allowed_families"])
        run_command(command, output_dir / f"raster-3-hyperopt-{duplicate_attempt:02d}.log", env=env)
        if not parameter_file.exists():
            raise RuntimeError("EvolutionResearchAgent produced no strategy parameter file")
        fingerprint = parameter_fingerprint(parameter_file)
        if fingerprint not in seen:
            return fingerprint, seed, epochs
    raise RuntimeError("EvolutionResearchAgent exhausted novelty retries without a new candidate")


def validate_candidate(
    *,
    state: dict[str, Any],
    plan: dict[str, Any],
    parameter_file: Path,
    fingerprint: str,
) -> str:
    if fingerprint in set(str(x) for x in state.get("parameter_fingerprints", [])):
        raise RuntimeError("BuildValidationAgent rejected duplicate parameter fingerprint")
    payload = load_json(parameter_file)
    selected = extract_selected_family(payload)
    if selected is None:
        raise RuntimeError("BuildValidationAgent could not identify selected strategy family")
    if selected not in set(plan["allowed_families"]):
        raise RuntimeError(
            f"BuildValidationAgent found family {selected!r} outside research plan {plan['allowed_families']!r}"
        )
    if bool(plan.get("blind_window_seen")):
        raise RuntimeError("BuildValidationAgent detected blind-window leakage in hypothesis")
    return selected


def initialize_state(council_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "run_count": 0,
        "hit_count": 0,
        "miss_count": 0,
        "best_final_balance": None,
        "best_run": None,
        "used_test_windows": [],
        "parameter_fingerprints": [],
        "learning_directive": "initial_broad_search",
        "current_raster": 1,
        "current_agent": "OpsWatchdog",
        "next_raster": 1,
        "supervisor": council_config["supervisor"]["name"],
    }


def execute_one_run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    args.data_dir = args.data_dir.resolve()
    research_root = root / "research/ten_day_challenge"
    challenge = load_json(research_root / "challenge.json")
    council_config = load_json(research_root / "agents.json")
    state_path = research_root / "walk-forward-state.json"
    state = load_json(state_path) if state_path.exists() else initialize_state(council_config)
    state["schema_version"] = max(2, int(state.get("schema_version") or 1))
    run_id = int(state.get("run_count") or 0) + 1
    test_start = choose_test_start(challenge, state, run_id)
    test_end = test_start + timedelta(days=int(challenge["window_days"]))
    history_start, optimize_start, history_end = training_bounds(challenge, test_start)

    results_root = research_root / "results/agentic-walk-forward"
    run_dir = results_root / f"run-{run_id:06d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    strategy_dir = root / "runtime/user_data/strategies/candidates"
    parameter_file = strategy_dir / f"{STRATEGY}.json"
    champion_dir = research_root / "agentic-champion"
    champion_dir.mkdir(parents=True, exist_ok=True)
    champion_file = champion_dir / f"{STRATEGY}.json"
    baseline_file = run_dir / "baseline-params.json"
    if parameter_file.exists() and not baseline_file.exists():
        shutil.copy2(parameter_file, baseline_file)

    memory_path = research_root / "research-memory.json"
    inbox_path = research_root / "research-inbox.json"
    memory = load_memory_json(memory_path, initial_memory())
    inbox = load_memory_json(inbox_path, {"schema_version": 1, "ideas": []})

    max_restarts = max(1, int(args.max_raster_restarts))
    for attempt in range(1, max_restarts + 1):
        restore_candidate(parameter_file, champion_file, baseline_file)
        failed_raster = 1
        try:
            # Raster 1: machinery and persisted state must be healthy.
            set_raster(state_path, state, run_id, 1)
            health_gate(
                python=args.python,
                freqtrade=args.freqtrade,
                root=root,
                data_dir=args.data_dir,
                output=run_dir / f"raster-1-health-attempt-{attempt:02d}.json",
            )
            pass_raster(state_path, state, run_id, 1, "technical health and checkpoints valid")

            # Raster 2: understand evidence/context without seeing the blind ten days.
            failed_raster = 2
            set_raster(state_path, state, run_id, 2)
            regime = classify_regime(
                args.data_dir,
                [str(x) for x in challenge["pairs"]],
                str(challenge["timeframe"]),
                history_start,
                history_end,
            )
            write_json(run_dir / "raster-2-evidence.json", regime)
            pass_raster(
                state_path,
                state,
                run_id,
                2,
                f"pre-window regime={regime['label']} cutoff={regime['evidence_cutoff']}",
            )

            # Raster 3: diagnose prior learning and create a genuinely different hypothesis.
            failed_raster = 3
            set_raster(state_path, state, run_id, 3)
            plan = plan_hypothesis(memory, state, regime, run_id, inbox)
            write_json(run_dir / "raster-3-hypothesis.json", plan)
            fingerprint, search_seed, epochs = run_hyperopt(
                args=args,
                root=root,
                challenge=challenge,
                state=state,
                plan=plan,
                run_id=run_id,
                attempt=attempt,
                optimize_start=optimize_start,
                test_start=test_start,
                parameter_file=parameter_file,
                output_dir=run_dir,
            )
            pass_raster(
                state_path,
                state,
                run_id,
                3,
                f"hypothesis={plan['hypothesis_id']} families={plan['allowed_families']} fingerprint={fingerprint[:12]}",
            )

            # Raster 4: candidate must be new, buildable and free of blind-window input.
            failed_raster = 4
            set_raster(state_path, state, run_id, 4)
            selected_family = validate_candidate(
                state=state,
                plan=plan,
                parameter_file=parameter_file,
                fingerprint=fingerprint,
            )
            pass_raster(
                state_path,
                state,
                run_id,
                4,
                f"candidate valid selected_family={selected_family}; blind window still sealed",
            )

            # Raster 5: only now reveal and execute the blind ten-day experiment.
            failed_raster = 5
            set_raster(state_path, state, run_id, 5)
            result = run_window(
                Window(test_start, test_end),
                freqtrade=args.freqtrade,
                config=root / "runtime/user_data/config-10day-research.json",
                userdir=root / "runtime/user_data",
                strategy_path=strategy_dir,
                data_dir=args.data_dir,
                strategy=STRATEGY,
                starting_balance=float(challenge["starting_balance"]),
                target_balance=float(challenge["target_balance"]),
                near_ruin_balance=float(challenge["near_ruin_balance"]),
                fee=float(challenge["effective_backtest_fee_per_side"]),
                detail_timeframe=str(challenge["detail_timeframe"]),
            )
            if result.error:
                raise RuntimeError(f"blind 10-day experiment failed technically: {result.error}")
            summary = summarize([result])
            critic = validation_review(summary, council_config)
            if bool(critic.get("veto")):
                raise RuntimeError(f"blind experiment validation veto: {critic.get('reason')}")
            risk = risk_review(summary, council_config)
            hit = bool(result.target_hit) or float(result.final_balance) >= float(challenge["target_balance"])
            pass_raster(
                state_path,
                state,
                run_id,
                5,
                f"{'HIT' if hit else 'MISS'} final={result.final_balance:.8f} trades={result.trades} family={selected_family}",
            )

            # Raster 6: judge outcome, update knowledge, then either stop on HIT or loop to raster 1.
            failed_raster = 6
            set_raster(state_path, state, run_id, 6)
            quant = quant_review(summary)
            council = assemble_council(quant, critic, risk, council_config)
            directive = learning_directive(result)
            best = state.get("best_final_balance")
            is_best = best is None or float(result.final_balance) > float(best)
            if is_best and parameter_file.exists():
                shutil.copy2(parameter_file, champion_file)
                state["best_final_balance"] = float(result.final_balance)
                state["best_run"] = run_id
            elif champion_file.exists():
                shutil.copy2(champion_file, parameter_file)

            record = {
                "run": run_id,
                "outcome": "HIT" if hit else "MISS",
                "starting_balance": float(challenge["starting_balance"]),
                "target_balance": float(challenge["target_balance"]),
                "final_balance": float(result.final_balance),
                "return_pct": float(result.return_pct),
                "target_hit_at": result.target_hit_at,
                "trades": int(result.trades),
                "max_drawdown_pct": result.max_drawdown_pct,
                "near_ruin": bool(result.near_ruin),
                "blind_test_start": test_start.isoformat(),
                "blind_test_end": test_end.isoformat(),
                "allowed_history_start": history_start.isoformat(),
                "allowed_history_end": history_end.isoformat(),
                "optimization_timerange_start": optimize_start.isoformat(),
                "market_regime": regime,
                "hypothesis": plan,
                "selected_family": selected_family,
                "parameter_fingerprint": fingerprint,
                "search_seed": search_seed,
                "hyperopt_epochs": epochs,
                "learning_directive_for_next_run": directive,
                "agent_council": council,
                "raster_restart_attempts": attempt - 1,
                "safety": {
                    "research_only": True,
                    "live_trading": False,
                    "exchange_secrets": False,
                    "blind_window_used_before_raster_5": False,
                },
                "completed_at_utc": datetime.now(UTC).isoformat(),
            }
            write_json(run_dir / "run.json", record)
            update_memory_after_completed_run(memory, plan, record)
            write_memory_json(memory_path, memory)

            state["run_count"] = run_id
            state["hit_count"] = int(state.get("hit_count") or 0) + (1 if hit else 0)
            state["miss_count"] = int(state.get("miss_count") or 0) + (0 if hit else 1)
            state["hit_rate"] = state["hit_count"] / state["run_count"]
            state.setdefault("used_test_windows", []).append(test_start.isoformat())
            state.setdefault("parameter_fingerprints", []).append(fingerprint)
            state["parameter_fingerprints"] = state["parameter_fingerprints"][-5000:]
            state["learning_directive"] = directive
            state["last_run"] = record
            state["last_failure"] = None
            state["last_completed_hypothesis"] = plan["hypothesis_id"]
            state["current_raster"] = 1
            state["current_agent"] = "OpsWatchdog"
            state["next_raster"] = 1
            state["raster_status"] = "target_reached" if hit else "ready_for_next_run"
            pass_raster(
                state_path,
                state,
                run_id,
                6,
                f"checkpointed {'HIT' if hit else 'MISS'}; {'stop target reached' if hit else 'full cycle restarts at raster 1'}",
            )
            state["current_raster"] = 1
            state["current_agent"] = "OpsWatchdog"
            state["next_raster"] = 1
            state["raster_status"] = "target_reached" if hit else "ready_for_next_run"
            persist_state(state_path, state)
            print(json.dumps(record, sort_keys=True))
            return record

        except Exception as exc:
            actions = repair(root, str(exc))
            incident = {
                "run": run_id,
                "attempt": attempt,
                "failed_raster": failed_raster,
                "failed_agent": RASTER_NAMES[failed_raster],
                "error": str(exc),
                "repair_actions": actions,
                "return_to_raster": 1,
                "at_utc": datetime.now(UTC).isoformat(),
            }
            write_json(run_dir / f"incident-attempt-{attempt:02d}.json", incident)
            state["last_failure"] = incident
            state["current_raster"] = 1
            state["current_agent"] = "OpsWatchdog"
            state["next_raster"] = 1
            state["raster_status"] = "repairing" if actions else "technical_retry"
            persist_state(state_path, state)
            if actions or attempt < 2:
                continue
            raise

    raise RuntimeError(f"run {run_id} exhausted raster-1 recovery attempts")


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
