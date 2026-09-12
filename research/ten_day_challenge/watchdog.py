"""Operational health checks for autonomous ten-day research.

This agent never scores or promotes trading strategies. It verifies that the
research machinery is runnable and that expected inputs/checkpoints exist.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def check_file(path: Path, failures: list[str]) -> None:
    if not path.is_file():
        failures.append(f"missing file: {path}")


def check_executable(path: Path, failures: list[str]) -> None:
    if not path.is_file():
        failures.append(f"missing executable: {path}")
        return
    completed = subprocess.run(
        [str(path), "--version"], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        failures.append(f"executable failed: {path}: {completed.stderr[-500:]}")


def check_module(name: str, failures: list[str]) -> None:
    if importlib.util.find_spec(name) is None:
        failures.append(f"missing Python module: {name}")


def inspect_data(data_dir: Path, failures: list[str]) -> dict[str, Any]:
    if not data_dir.is_dir():
        failures.append(f"missing data directory: {data_dir}")
        return {"files": 0, "bytes": 0}
    files = [item for item in data_dir.rglob("*") if item.is_file()]
    total_bytes = sum(item.stat().st_size for item in files)
    if not files:
        failures.append(f"data directory is empty: {data_dir}")
    return {"files": len(files), "bytes": total_bytes}


def inspect_checkpoint(root: Path) -> dict[str, Any]:
    state = root / "research/ten_day_challenge/state.json"
    champion = root / "research/ten_day_challenge/champion/TenDayMomentumV1.json"
    results = root / "research/ten_day_challenge/results"
    generations = sorted(results.glob("generation-*/generation.json")) if results.exists() else []
    return {
        "state_present": state.is_file(),
        "champion_present": champion.is_file(),
        "generation_records": len(generations),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--freqtrade", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[str] = []
    required = [
        root / "research/ten_day_challenge/challenge.json",
        root / "research/ten_day_challenge/agents.json",
        root / "research/ten_day_challenge/evolve.py",
        root / "research/ten_day_challenge/rolling_windows.py",
        root / "runtime/user_data/config-10day-research.json",
        root / "runtime/user_data/strategies/candidates/TenDayMomentumV1.py",
        root / "runtime/user_data/hyperopts/TenDayChallengeLoss.py",
    ]
    for path in required:
        check_file(path, failures)

    check_executable(args.python, failures)
    check_executable(args.freqtrade, failures)
    check_module("filelock", failures)
    check_module("cmaes", failures)

    data = inspect_data(args.data_dir.resolve(), failures)
    checkpoint = inspect_checkpoint(root)
    report = {
        "agent": "OpsWatchdog",
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "healthy": not failures,
        "failures": failures,
        "data": data,
        "checkpoint": checkpoint,
        "safety": {
            "live_trading_enabled": False,
            "exchange_secrets_required": False,
            "strategy_voting": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
