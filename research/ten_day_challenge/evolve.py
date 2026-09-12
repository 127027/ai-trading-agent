"""Checkpointable champion/challenger loop for the ten-day challenge.

Strict raster state machine:
1 OpsWatchdog -> 2 ResearchAgent -> 3 QuantAgent -> 4 ValidationCritic ->
5 RiskAgent -> 6 TenDaySupervisor.

Any technical failure in rasters 2-6 is handed back to raster 1. Raster 1
records the incident, applies only whitelisted infrastructure repairs, rechecks
health, and restarts the same generation from raster 2. A generation only
commits after raster 6 completes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from council import assemble_council, quant_review, risk_review, validation_review
from repair_known_failures import repair

T = TypeVar("T")

RASTER_NAMES = {
    1: "OpsWatchdog",
    2: "ResearchAgent",
    3: "QuantAgent",
    4: "ValidationCritic",
    5: "RiskAgent",
    6: "TenDaySupervisor",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    if completed.returncode != 0:
        tail = "\n".join(
            log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        )
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{tail}"
        )


def persist_state(state_path: Path, state: dict[str, Any]) -> None:
    state["updated_at_utc"] = datetime.now(UTC).isoformat()
    write_json(state_path, state)


def set_raster(
    state_path: Path,
    state: dict[str, Any],
    raster: int,
    generation: int,
    status: str = "running",
) -> None:
    state["generation_in_progress"] = generation
    state["current_raster"] = raster
    state["current_agent"] = RASTER_NAMES[raster]
    state["raster_status"] = status
    state["next_raster"] = raster
    persist_state(state_path, state)


def raster_1_health_gate(
    python: str,
    freqtrade: str,
    root: Path,
    data_dir: Path,
    output_dir: Path,
    label: str,
) -> dict[str, Any]:
    report_path = output_dir / "raster-1-health" / f"{label}.json"
    log_path = output_dir / "raster-1-health" / f"{label}.log"
    command = [
        python,
        str(root / "research/ten_day_challenge/watchdog.py"),
        "--root",
        str(root),
        "--data-dir",
        str(data_dir),
        "--python",
        python,
        "--freqtrade",
        freqtrade,
        "--output",
        str(report_path),
    ]
    run(command, log_path)
    report = load_json(report_path)
    if not bool(report.get("healthy")):
        raise RuntimeError(f"raster 1 health gate failed: {report.get('failures', [])}")
    return report


def exact_validation(
    python: str,
    freqtrade: str,
    root: Path,
    data_dir: Path,
    start: str,
    end: str,
    step_days: int,
    output_dir: Path,
    workers: int,
    challenge: dict[str, Any],
) -> dict[str, Any]:
    command = [
        python,
        str(root / "research/ten_day_challenge/rolling_windows.py"),
        "--freqtrade",
        freqtrade,
        "--config",
        str(root / "runtime/user_data/config-10day-research.json"),
        "--userdir",
        str(root / "runtime/user_data"),
        "--strategy-path",
        str(root / "runtime/user_data/strategies/candidates"),
        "--data-dir",
        str(data_dir),
        "--strategy",
        "TenDayMomentumV1",
        "--start",
        start,
        "--end",
        end,
        "--window-days",
        str(challenge["window_days"]),
        "--step-days",
        str(step_days),
        "--starting-balance",
        str(challenge["starting_balance"]),
        "--target-balance",
        str(challenge["target_balance"]),
        "--near-ruin-balance",
        str(challenge["near_ruin_balance"]),
        "--fee",
        str(challenge["effective_backtest_fee_per_side"]),
        "--detail-timeframe",
        str(challenge["detail_timeframe"]),
        "--workers",
        str(workers),
        "--output-dir",
        str(output_dir),
    ]
    run(command, output_dir / "validator.log")
    return load_json(output_dir / "rolling-windows.json")["summary"]


def restore_generation_baseline(
    parameter_file: Path,
    champion_file: Path,
    baseline_file: Path,
    baseline_existed: bool,
) -> None:
    if champion_file.exists():
        shutil.copy2(champion_file, parameter_file)
    elif baseline_existed and baseline_file.exists():
        shutil.copy2(baseline_file, parameter_file)
    elif parameter_file.exists():
        parameter_file.unlink()


def record_incident(
    results_root: Path,
    state_path: Path,
    state: dict[str, Any],
    generation: int,
    failed_raster: int,
    attempt: int,
    error: Exception,
    actions: list[str],
) -> None:
    incident = {
        "generation": generation,
        "failed_raster": failed_raster,
        "failed_agent": RASTER_NAMES[failed_raster],
        "attempt": attempt,
        "error": str(error),
        "repair_actions": actions,
        "return_to_raster": 1,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "safety": {
            "live_trading_enabled": False,
            "exchange_secrets_added": False,
            "trading_logic_repaired_by_raster_1": False,
        },
    }
    incident_path = (
        results_root
        / "raster-1-incidents"
        / f"generation-{generation:04d}-attempt-{attempt:02d}.json"
    )
    write_json(incident_path, incident)
    state["last_failure"] = incident
    state["current_raster"] = 1
    state["current_agent"] = "OpsWatchdog"
    state["raster_status"] = "repairing" if actions else "diagnosing"
    state["next_raster"] = 1
    persist_state(state_path, state)


def run_raster(
    state_path: Path,
    state: dict[str, Any],
    generation: int,
    raster: int,
    callback: Callable[[], T],
) -> T:
    set_raster(state_path, state, raster, generation)
    result = callback()
    state.setdefault("raster_history", []).append(
        {
            "generation": generation,
            "raster": raster,
            "agent": RASTER_NAMES[raster],
            "status": "passed",
            "at_utc": datetime.now(UTC).isoformat(),
        }
    )
    state["raster_status"] = "passed"
    state["next_raster"] = 1 if raster == 6 else raster + 1
    persist_state(state_path, state)
    return result


def finalize(
    args: argparse.Namespace,
    root: Path,
    challenge: dict[str, Any],
    council_config: dict[str, Any],
    results_root: Path,
    champion_dir: Path,
    parameter_file: Path,
    state_path: Path,
    state: dict[str, Any],
) -> int:
    generation = int(state.get("generation") or 0)
    health = run_raster(
        state_path,
        state,
        generation,
        1,
        lambda: raster_1_health_gate(
            args.python,
            args.freqtrade,
            root,
            args.data_dir,
            results_root,
            "finalize",
        ),
    )
    champion = champion_dir / "TenDayMomentumV1.json"
    if champion.exists():
        shutil.copy2(champion, parameter_file)

    summary = exact_validation(
        args.python,
        args.freqtrade,
        root,
        args.data_dir,
        challenge["dataset_start"],
        challenge["dataset_end"],
        int(challenge["exact_step_days_for_final"]),
        results_root / "final-full-year",
        args.workers,
        challenge,
    )
    quant = quant_review(summary)
    critic = validation_review(summary, council_config)
    risk = risk_review(summary, council_config)
    final_council = assemble_council(quant, critic, risk, council_config)
    write_json(results_root / "final-full-year" / "agent-council.json", final_council)

    state["final_full_year"] = summary
    state["final_agent_council"] = final_council
    state["finalized"] = True
    state["last_raster_trace"] = {
        "1": {"agent": "OpsWatchdog", "status": "passed", "health": health},
        "2": {"agent": "ResearchAgent", "status": "champion_frozen"},
        "3": {"agent": "QuantAgent", "status": "full_year_scored", "review": quant},
        "4": {"agent": "ValidationCritic", "status": "reviewed", "review": critic},
        "5": {"agent": "RiskAgent", "status": "reviewed", "review": risk},
        "6": {"agent": "TenDaySupervisor", "status": "final_checkpoint"},
    }
    state["current_raster"] = 1
    state["current_agent"] = "OpsWatchdog"
    state["next_raster"] = 1
    state["raster_status"] = "cycle_complete"
    persist_state(state_path, state)

    if champion.exists():
        payload = load_json(champion)
        if "strategy_name" in payload:
            payload["strategy_name"] = "TenDayMomentumPaperV1"
        write_json(parameter_file.parent / "TenDayMomentumPaperV1.json", payload)

    print(json.dumps({"summary": summary, "council": final_council}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=int, default=180)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--mode", choices=("search", "finalize"), default="search")
    parser.add_argument("--python", default="python")
    parser.add_argument("--freqtrade", default="freqtrade")
    parser.add_argument("--max-raster-restarts", type=int, default=8)
    args = parser.parse_args()

    root = args.root.resolve()
    args.data_dir = args.data_dir.resolve()
    challenge = load_json(root / "research/ten_day_challenge/challenge.json")
    council_config = load_json(root / "research/ten_day_challenge/agents.json")
    strategy_dir = root / "runtime/user_data/strategies/candidates"
    parameter_file = strategy_dir / "TenDayMomentumV1.json"
    research_root = root / "research/ten_day_challenge"
    results_root = research_root / "results"
    champion_dir = research_root / "champion"
    champion_dir.mkdir(parents=True, exist_ok=True)
    state_path = research_root / "state.json"
    state = (
        load_json(state_path)
        if state_path.exists()
        else {
            "schema_version": 3,
            "generation": 0,
            "best_score": None,
            "best_generation": None,
            "supervisor": council_config["supervisor"]["name"],
            "raster_policy": "1-ops 2-research 3-quant 4-validation 5-risk 6-supervisor",
            "next_raster": 1,
        }
    )

    if args.mode == "finalize":
        return finalize(
            args,
            root,
            challenge,
            council_config,
            results_root,
            champion_dir,
            parameter_file,
            state_path,
            state,
        )

    deadline = time.monotonic() + max(args.budget_minutes, 5) * 60
    best_score = (
        float(state["best_score"])
        if state.get("best_score") is not None
        else float("-inf")
    )
    generation = int(state.get("generation") or 0)
    champion_file = champion_dir / "TenDayMomentumV1.json"

    while time.monotonic() < deadline - 600:
        generation += 1
        out = results_root / f"generation-{generation:04d}"
        out.mkdir(parents=True, exist_ok=True)
        baseline_file = out / "baseline-params.json"
        baseline_existed = parameter_file.exists()
        if baseline_existed and not baseline_file.exists():
            shutil.copy2(parameter_file, baseline_file)

        completed = False
        restart_attempt = 0
        while not completed:
            restart_attempt += 1
            if restart_attempt > max(1, args.max_raster_restarts):
                state["raster_status"] = "restart_limit_reached"
                state["next_raster"] = 1
                persist_state(state_path, state)
                raise RuntimeError(
                    f"raster recovery limit reached for generation {generation}"
                )

            restore_generation_baseline(
                parameter_file,
                champion_file,
                baseline_file,
                baseline_existed,
            )
            failed_raster = 1
            try:
                health = run_raster(
                    state_path,
                    state,
                    generation,
                    1,
                    lambda: raster_1_health_gate(
                        args.python,
                        args.freqtrade,
                        root,
                        args.data_dir,
                        results_root,
                        f"generation-{generation:04d}-attempt-{restart_attempt:02d}",
                    ),
                )

                failed_raster = 2
                previous = out / "previous-params.json"
                if parameter_file.exists():
                    shutil.copy2(parameter_file, previous)
                timerange = (
                    f"{date.fromisoformat(challenge['dataset_start']):%Y%m%d}-"
                    f"{date.fromisoformat(challenge['train_end']):%Y%m%d}"
                )
                hyperopt_command = [
                    args.freqtrade,
                    "hyperopt",
                    "--config",
                    str(root / "runtime/user_data/config-10day-research.json"),
                    "--userdir",
                    str(root / "runtime/user_data"),
                    "--strategy-path",
                    str(strategy_dir),
                    "--data-dir",
                    str(args.data_dir),
                    "--strategy",
                    "TenDayMomentumV1",
                    "--hyperopt-loss",
                    "TenDayChallengeLoss",
                    "--timerange",
                    timerange,
                    "--epochs",
                    str(challenge["hyperopt_epochs_per_generation"]),
                    "--spaces",
                    *[str(item) for item in challenge["hyperopt_spaces"]],
                    "--fee",
                    str(challenge["effective_backtest_fee_per_side"]),
                    "--random-state",
                    str(1000 + generation),
                    "--enable-protections",
                    "--analyze-per-epoch",
                ]
                run_raster(
                    state_path,
                    state,
                    generation,
                    2,
                    lambda: run(hyperopt_command, out / "hyperopt.log"),
                )

                failed_raster = 3
                summary = run_raster(
                    state_path,
                    state,
                    generation,
                    3,
                    lambda: exact_validation(
                        args.python,
                        args.freqtrade,
                        root,
                        args.data_dir,
                        challenge["train_end"],
                        challenge["validation_end"],
                        int(challenge["validation_step_days_during_search"]),
                        out / "validation",
                        args.workers,
                        challenge,
                    ),
                )
                quant = quant_review(summary)
                state["last_quant_review"] = quant
                persist_state(state_path, state)

                failed_raster = 4
                critic = run_raster(
                    state_path,
                    state,
                    generation,
                    4,
                    lambda: validation_review(summary, council_config),
                )

                failed_raster = 5
                risk = run_raster(
                    state_path,
                    state,
                    generation,
                    5,
                    lambda: risk_review(summary, council_config),
                )

                failed_raster = 6
                council = run_raster(
                    state_path,
                    state,
                    generation,
                    6,
                    lambda: assemble_council(quant, critic, risk, council_config),
                )
                score = float(council["council_score"])
                accepted = (
                    bool(council["promotion_eligible"])
                    and score > best_score
                    and parameter_file.exists()
                )
                raster_trace = {
                    "1": {"agent": "OpsWatchdog", "status": "passed", "health": health},
                    "2": {"agent": "ResearchAgent", "status": "challenger_generated"},
                    "3": {"agent": "QuantAgent", "status": "scored", "review": quant},
                    "4": {
                        "agent": "ValidationCritic",
                        "status": "reviewed",
                        "review": critic,
                    },
                    "5": {"agent": "RiskAgent", "status": "reviewed", "review": risk},
                    "6": {
                        "agent": "TenDaySupervisor",
                        "status": "promoted" if accepted else "rejected",
                    },
                }
                record = {
                    "generation": generation,
                    "score": score,
                    "accepted": accepted,
                    "validation": summary,
                    "agent_council": council,
                    "raster_trace": raster_trace,
                    "raster_restart_attempts": restart_attempt - 1,
                    "seed": 1000 + generation,
                }
                write_json(out / "generation.json", record)

                if accepted:
                    best_score = score
                    shutil.copy2(parameter_file, champion_file)
                    write_json(champion_dir / "summary.json", record)
                    state["best_generation"] = generation
                else:
                    restore_generation_baseline(
                        parameter_file,
                        champion_file,
                        baseline_file,
                        baseline_existed,
                    )

                state.update(
                    {
                        "generation": generation,
                        "best_score": None if best_score == float("-inf") else best_score,
                        "supervisor": council_config["supervisor"]["name"],
                        "last_raster_trace": raster_trace,
                        "current_raster": 1,
                        "current_agent": "OpsWatchdog",
                        "raster_status": "generation_complete",
                        "next_raster": 1,
                        "last_failure": None,
                    }
                )
                persist_state(state_path, state)
                print(json.dumps(record, sort_keys=True))
                completed = True

            except Exception as error:
                actions = repair(root, str(error))
                record_incident(
                    results_root,
                    state_path,
                    state,
                    generation,
                    failed_raster,
                    restart_attempt,
                    error,
                    actions,
                )
                restore_generation_baseline(
                    parameter_file,
                    champion_file,
                    baseline_file,
                    baseline_existed,
                )
                if actions:
                    continue

                # Unknown failures still return through raster 1 once more in case the
                # failure was transient. Persistent unknown defects are escalated to
                # the external watchdog, which can modify code without user input.
                if restart_attempt < 2:
                    state["raster_status"] = "transient_retry_via_raster_1"
                    persist_state(state_path, state)
                    continue
                raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
