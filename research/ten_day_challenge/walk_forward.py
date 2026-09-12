"""Autonomous one-run/one-window walk-forward research loop.

One research run means exactly one blind 10-day backtest starting with 100 USDT.
Raster 2 may optimize only on the 365 calendar days immediately preceding the
randomly selected test start. Raster 3 then reveals exactly the following ten
days. A valid miss is learning evidence; a technical failure returns to raster 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from council import assemble_council, quant_review, risk_review, validation_review
from repair_known_failures import repair
from rolling_windows import Window, run_window, summarize

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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def persist_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at_utc"] = datetime.now(UTC).isoformat()
    write_json(path, state)


def set_raster(path: Path, state: dict[str, Any], run_id: int, raster: int, status: str = "running") -> None:
    state["run_in_progress"] = run_id
    state["current_raster"] = raster
    state["current_agent"] = RASTER_NAMES[raster]
    state["raster_status"] = status
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
    # Keep state compact even after thousands of runs.
    state["raster_history"] = state["raster_history"][-300:]
    state["raster_status"] = "passed"
    state["next_raster"] = 1 if raster == 6 else raster + 1
    persist_state(path, state)


def run_command(command: list[str], log_path: Path, *, env: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
            env=env,
        )
    if completed.returncode != 0:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:])
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{tail}")


def health_gate(
    *,
    python: str,
    freqtrade: str,
    root: Path,
    data_dir: Path,
    output: Path,
) -> dict[str, Any]:
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
        str(output),
    ]
    run_command(command, output.with_suffix(".log"))
    report = load_json(output)
    if not bool(report.get("healthy")):
        raise RuntimeError(f"raster 1 health gate failed: {report.get('failures', [])}")
    return report


def eligible_test_starts(challenge: dict[str, Any]) -> list[date]:
    dataset_start = date.fromisoformat(challenge["dataset_start"])
    dataset_end = date.fromisoformat(challenge["dataset_end"])
    pool_start = date.fromisoformat(challenge["test_pool_start"])
    pool_end = date.fromisoformat(challenge["test_pool_end"])
    history_days = int(challenge["history_days"])
    window_days = int(challenge["window_days"])
    starts: list[date] = []
    current = pool_start
    while current <= pool_end:
        if current - timedelta(days=history_days) >= dataset_start and current + timedelta(days=window_days) <= dataset_end:
            starts.append(current)
        current += timedelta(days=1)
    if not starts:
        raise RuntimeError("no eligible walk-forward test windows")
    return starts


def choose_test_start(challenge: dict[str, Any], state: dict[str, Any], run_id: int) -> date:
    starts = eligible_test_starts(challenge)
    used = set(str(item) for item in state.get("used_test_windows", []))
    available = [item for item in starts if item.isoformat() not in used]
    if not available:
        if bool(challenge.get("unique_test_windows_until_exhausted", True)):
            raise RuntimeError("unique blind 10-day window pool exhausted; expand historical dataset before repeating tests")
        available = starts
    rng = random.Random(int(challenge["random_window_seed"]) + run_id * 104729)
    return rng.choice(available)


def training_bounds(challenge: dict[str, Any], test_start: date) -> tuple[date, date, date]:
    history_start = test_start - timedelta(days=int(challenge["history_days"]))
    optimize_start = history_start + timedelta(days=int(challenge.get("history_warmup_days", 4)))
    return history_start, optimize_start, test_start


def parameter_fingerprint(path: Path) -> str:
    payload = load_json(path)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def learning_directive(result: Any) -> str:
    if bool(result.target_hit) or float(result.final_balance) >= float(result.target_balance):
        return "target_hit_preserve_and_explore_neighbor"
    if int(result.trades) == 0:
        return "increase_signal_recall_and_trade_activity"
    balance = float(result.final_balance)
    if balance < 50.0:
        return "large_loss_rework_entries_and_exit_damage"
    if balance < 100.0:
        return "negative_return_improve_entry_quality_without_becoming_passive"
    if balance < 150.0:
        return "positive_but_slow_increase_return_velocity"
    if balance < 175.0:
        return "strong_miss_seek_more_convexity_and_capture"
    return "near_target_refine_entries_exits_and_profit_capture"


def epochs_for_run(challenge: dict[str, Any], directive: str) -> int:
    base = int(challenge["hyperopt_epochs_per_run"])
    if directive.startswith("near_target"):
        return max(base, int(base * 1.5))
    if directive.startswith("increase_signal"):
        return max(base, int(base * 1.25))
    return base


def restore_candidate(parameter_file: Path, champion_file: Path, baseline_file: Path) -> None:
    if champion_file.exists():
        shutil.copy2(champion_file, parameter_file)
    elif baseline_file.exists():
        shutil.copy2(baseline_file, parameter_file)
    elif parameter_file.exists():
        parameter_file.unlink()


def run_hyperopt(
    *,
    args: argparse.Namespace,
    root: Path,
    challenge: dict[str, Any],
    state: dict[str, Any],
    run_id: int,
    attempt: int,
    optimize_start: date,
    test_start: date,
    parameter_file: Path,
    output_dir: Path,
) -> tuple[str, int, int]:
    seen = set(str(item) for item in state.get("parameter_fingerprints", []))
    directive = str(state.get("learning_directive") or "initial_broad_search")
    epochs = epochs_for_run(challenge, directive)
    directive_salt = int(hashlib.sha256(directive.encode("utf-8")).hexdigest()[:8], 16)
    retries = int(challenge.get("duplicate_fingerprint_retries", 8))
    timerange = f"{optimize_start:%Y%m%d}-{test_start:%Y%m%d}"

    for duplicate_attempt in range(retries + 1):
        seed = (
            int(challenge["search_seed_base"])
            + run_id * 1009
            + attempt * 97
            + duplicate_attempt * 7919
            + directive_salt % 100000
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
            "TenDayMomentumV1",
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
        run_command(command, output_dir / f"hyperopt-{duplicate_attempt:02d}.log", env=env)
        if not parameter_file.exists():
            raise RuntimeError("hyperopt completed without producing the strategy parameter file")
        fingerprint = parameter_fingerprint(parameter_file)
        if fingerprint not in seen:
            return fingerprint, seed, epochs
    raise RuntimeError("ResearchAgent exhausted duplicate-fingerprint retries without a materially new candidate")


def initialize_state(council_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
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
    run_id = int(state.get("run_count") or 0) + 1
    test_start = choose_test_start(challenge, state, run_id)
    test_end = test_start + timedelta(days=int(challenge["window_days"]))
    history_start, optimize_start, history_end = training_bounds(challenge, test_start)

    results_root = research_root / "results/walk-forward"
    run_dir = results_root / f"run-{run_id:06d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    strategy_dir = root / "runtime/user_data/strategies/candidates"
    parameter_file = strategy_dir / "TenDayMomentumV1.json"
    champion_dir = research_root / "walk-forward-champion"
    champion_dir.mkdir(parents=True, exist_ok=True)
    champion_file = champion_dir / "TenDayMomentumV1.json"
    baseline_file = run_dir / "baseline-params.json"
    if parameter_file.exists() and not baseline_file.exists():
        shutil.copy2(parameter_file, baseline_file)

    max_restarts = max(1, int(args.max_raster_restarts))
    for attempt in range(1, max_restarts + 1):
        restore_candidate(parameter_file, champion_file, baseline_file)
        failed_raster = 1
        try:
            set_raster(state_path, state, run_id, 1)
            health = health_gate(
                python=args.python,
                freqtrade=args.freqtrade,
                root=root,
                data_dir=args.data_dir,
                output=run_dir / f"raster-1-health-attempt-{attempt:02d}.json",
            )
            pass_raster(state_path, state, run_id, 1, "health and research memory valid")

            failed_raster = 2
            set_raster(state_path, state, run_id, 2)
            fingerprint, search_seed, epochs = run_hyperopt(
                args=args,
                root=root,
                challenge=challenge,
                state=state,
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
                2,
                f"trained only on {history_start.isoformat()}..{history_end.isoformat()} with fingerprint {fingerprint[:12]}",
            )

            failed_raster = 3
            set_raster(state_path, state, run_id, 3)
            window = Window(test_start, test_end)
            result = run_window(
                window,
                freqtrade=args.freqtrade,
                config=root / "runtime/user_data/config-10day-research.json",
                userdir=root / "runtime/user_data",
                strategy_path=strategy_dir,
                data_dir=args.data_dir,
                strategy="TenDayMomentumV1",
                starting_balance=float(challenge["starting_balance"]),
                target_balance=float(challenge["target_balance"]),
                near_ruin_balance=float(challenge["near_ruin_balance"]),
                fee=float(challenge["effective_backtest_fee_per_side"]),
                detail_timeframe=str(challenge["detail_timeframe"]),
            )
            if result.error:
                raise RuntimeError(f"blind 10-day backtest failed: {result.error}")
            summary = summarize([result])
            hit = bool(result.target_hit) or float(result.final_balance) >= float(challenge["target_balance"])
            pass_raster(
                state_path,
                state,
                run_id,
                3,
                f"{'HIT' if hit else 'MISS'} final={result.final_balance:.8f} trades={result.trades}",
            )

            failed_raster = 4
            set_raster(state_path, state, run_id, 4)
            critic = validation_review(summary, council_config)
            if bool(critic.get("veto")):
                raise RuntimeError(f"validation veto: {critic.get('reason')}")
            pass_raster(state_path, state, run_id, 4, "blind window complete and reproducible")

            failed_raster = 5
            set_raster(state_path, state, run_id, 5)
            risk = risk_review(summary, council_config)
            pass_raster(
                state_path,
                state,
                run_id,
                5,
                f"near_ruin={result.near_ruin} drawdown={result.max_drawdown_pct}",
            )

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
                    "blind_window_used_for_raster_2": False,
                },
                "completed_at_utc": datetime.now(UTC).isoformat(),
            }
            write_json(run_dir / "run.json", record)

            state["run_count"] = run_id
            state["hit_count"] = int(state.get("hit_count") or 0) + (1 if hit else 0)
            state["miss_count"] = int(state.get("miss_count") or 0) + (0 if hit else 1)
            state["hit_rate"] = state["hit_count"] / state["run_count"]
            state.setdefault("used_test_windows", []).append(test_start.isoformat())
            state.setdefault("parameter_fingerprints", []).append(fingerprint)
            state["learning_directive"] = directive
            state["last_run"] = record
            state["last_failure"] = None
            state["current_raster"] = 1
            state["current_agent"] = "OpsWatchdog"
            state["next_raster"] = 1
            state["raster_status"] = "run_complete"
            # 1100 unique daily windows fit comfortably; keep fingerprints bounded anyway.
            state["parameter_fingerprints"] = state["parameter_fingerprints"][-5000:]
            persist_state(state_path, state)
            pass_raster(state_path, state, run_id, 6, f"checkpointed {'HIT' if hit else 'MISS'}; next run starts at raster 1")
            state["current_raster"] = 1
            state["current_agent"] = "OpsWatchdog"
            state["next_raster"] = 1
            state["raster_status"] = "ready_for_next_run"
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
