"""Checkpointable champion/challenger loop for the ten-day challenge.

Every generation follows the ordered raster policy:
1 OpsWatchdog -> 2 ResearchAgent -> 3 QuantAgent -> 4 ValidationCritic ->
5 RiskAgent -> 6 TenDaySupervisor. A technical failure exits to the guarded
self-heal wrapper, which returns through raster 1 before retrying.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from council import evaluate_candidate


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    if completed.returncode != 0:
        tail = "\n".join(
            log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        )
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{tail}"
        )


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=int, default=180)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--mode", choices=("search", "finalize"), default="search")
    parser.add_argument("--python", default="python")
    parser.add_argument("--freqtrade", default="freqtrade")
    args = parser.parse_args()

    root = args.root.resolve()
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
            "schema_version": 2,
            "generation": 0,
            "best_score": None,
            "best_generation": None,
            "supervisor": council_config["supervisor"]["name"],
            "raster_policy": "1-ops 2-research 3-quant 4-validation 5-risk 6-supervisor",
        }
    )

    if args.mode == "finalize":
        health = raster_1_health_gate(
            args.python,
            args.freqtrade,
            root,
            args.data_dir,
            results_root,
            "finalize",
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
        final_council = evaluate_candidate(summary, council_config)
        (results_root / "final-full-year" / "agent-council.json").write_text(
            json.dumps(final_council, indent=2, sort_keys=True), encoding="utf-8"
        )
        state["final_full_year"] = summary
        state["final_agent_council"] = final_council
        state["finalized"] = True
        state["last_raster_trace"] = {
            "1": {"agent": "OpsWatchdog", "status": "passed", "health": health},
            "2": {"agent": "ResearchAgent", "status": "champion_frozen"},
            "3": {"agent": "QuantAgent", "status": "full_year_scored"},
            "4": {"agent": "ValidationCritic", "status": "reviewed"},
            "5": {"agent": "RiskAgent", "status": "reviewed"},
            "6": {"agent": "TenDaySupervisor", "status": "final_checkpoint"},
        }
        if champion.exists():
            payload = load_json(champion)
            if "strategy_name" in payload:
                payload["strategy_name"] = "TenDayMomentumPaperV1"
            (strategy_dir / "TenDayMomentumPaperV1.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps({"summary": summary, "council": final_council}, indent=2))
        return 0

    deadline = time.monotonic() + max(args.budget_minutes, 5) * 60
    best_score = (
        float(state["best_score"])
        if state.get("best_score") is not None
        else float("-inf")
    )
    generation = int(state.get("generation") or 0)
    while time.monotonic() < deadline - 600:
        generation += 1
        out = results_root / f"generation-{generation:04d}"
        out.mkdir(parents=True, exist_ok=True)

        health = raster_1_health_gate(
            args.python,
            args.freqtrade,
            root,
            args.data_dir,
            results_root,
            f"generation-{generation:04d}",
        )

        previous = out / "previous-params.json"
        if parameter_file.exists():
            shutil.copy2(parameter_file, previous)
        timerange = (
            f"{date.fromisoformat(challenge['dataset_start']):%Y%m%d}-"
            f"{date.fromisoformat(challenge['train_end']):%Y%m%d}"
        )
        command = [
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
        run(command, out / "hyperopt.log")

        summary = exact_validation(
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
        )
        council = evaluate_candidate(summary, council_config)
        score = float(council["council_score"])
        accepted = (
            bool(council["promotion_eligible"])
            and score > best_score
            and parameter_file.exists()
        )
        reviews = {review["agent"]: review for review in council["reviews"]}
        raster_trace = {
            "1": {"agent": "OpsWatchdog", "status": "passed", "health": health},
            "2": {"agent": "ResearchAgent", "status": "challenger_generated"},
            "3": {
                "agent": "QuantAgent",
                "status": "scored",
                "review": reviews.get("QuantAgent"),
            },
            "4": {
                "agent": "ValidationCritic",
                "status": "reviewed",
                "review": reviews.get("ValidationCritic"),
            },
            "5": {
                "agent": "RiskAgent",
                "status": "reviewed",
                "review": reviews.get("RiskAgent"),
            },
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
            "seed": 1000 + generation,
        }
        (out / "generation.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
        )
        if accepted:
            best_score = score
            shutil.copy2(parameter_file, champion_dir / "TenDayMomentumV1.json")
            (champion_dir / "summary.json").write_text(
                json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
            )
            state["best_generation"] = generation
        else:
            champion = champion_dir / "TenDayMomentumV1.json"
            if champion.exists():
                shutil.copy2(champion, parameter_file)
            elif previous.exists():
                shutil.copy2(previous, parameter_file)
        state.update(
            {
                "generation": generation,
                "best_score": None if best_score == float("-inf") else best_score,
                "supervisor": council_config["supervisor"]["name"],
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "last_raster_trace": raster_trace,
                "next_raster": 1,
            }
        )
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
