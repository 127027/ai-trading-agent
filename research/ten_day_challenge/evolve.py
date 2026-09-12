"""Checkpointable champion/challenger loop for the ten-day challenge."""

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


def exact_validation(
    python: str,
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
            "schema_version": 1,
            "generation": 0,
            "best_score": None,
            "best_generation": None,
            "supervisor": council_config["supervisor"]["name"],
        }
    )

    if args.mode == "finalize":
        champion = champion_dir / "TenDayMomentumV1.json"
        if champion.exists():
            shutil.copy2(champion, parameter_file)
        summary = exact_validation(
            args.python,
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
        ]
        run(command, out / "hyperopt.log")
        summary = exact_validation(
            args.python,
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
        record = {
            "generation": generation,
            "score": score,
            "accepted": accepted,
            "validation": summary,
            "agent_council": council,
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
            }
        )
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
