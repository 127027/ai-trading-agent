"""Operational health checks for the autonomous six-raster research loop."""

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


def install_public_freqtrade_launcher(
    root: Path, python_executable: Path, freqtrade_executable: Path
) -> None:
    adapter = root / "research/ten_day_challenge/freqtrade_public.py"
    if not adapter.is_file() or not freqtrade_executable.is_file():
        return
    python_path = python_executable if python_executable.is_absolute() else root / python_executable
    python_path = python_path.absolute()
    launcher = (
        f"#!{python_path}\n"
        "import runpy\n"
        f"runpy.run_path({str(adapter)!r}, run_name='__main__')\n"
    )
    freqtrade_executable.write_text(launcher, encoding="utf-8")
    freqtrade_executable.chmod(0o755)


def check_executable(path: Path, failures: list[str]) -> None:
    if not path.is_file():
        failures.append(f"missing executable: {path}")
        return
    completed = subprocess.run([str(path), "--version"], capture_output=True, text=True, check=False)
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


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def inspect_checkpoint(root: Path) -> dict[str, Any]:
    research = root / "research/ten_day_challenge"
    state = research / "walk-forward-state.json"
    memory = research / "research-memory.json"
    inbox = research / "research-inbox.json"
    champion = research / "agentic-champion/TenDayAdaptiveV2.json"
    results = research / "results/agentic-walk-forward"
    runs = sorted(results.glob("run-*/run.json")) if results.exists() else []
    state_payload = load_state(state)
    run_count = int(state_payload.get("run_count") or 0)
    clean_start = run_count == 0 and len(runs) == 0
    return {
        "state_present": state.is_file(),
        "research_memory_present": memory.is_file(),
        "research_inbox_present": inbox.is_file(),
        "champion_present": champion.is_file(),
        "agentic_run_records": len(runs),
        "run_count": run_count,
        "clean_start": clean_start,
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
    research = root / "research/ten_day_challenge"
    required = [
        research / "challenge.json",
        research / "agents.json",
        research / "agentic_walk_forward.py",
        research / "evolution.py",
        research / "rolling_windows.py",
        research / "freqtrade_public.py",
        root / "runtime/user_data/config-10day-research.json",
        root / "runtime/user_data/strategies/candidates/TenDayAdaptiveV2.py",
        root / "runtime/user_data/hyperopts/TenDayChallengeLoss.py",
    ]
    for path in required:
        check_file(path, failures)

    checkpoint = inspect_checkpoint(root)
    if not checkpoint["clean_start"]:
        check_file(research / "research-memory.json", failures)
        check_file(research / "research-inbox.json", failures)

    install_public_freqtrade_launcher(root, args.python, args.freqtrade)
    check_executable(args.python, failures)
    check_executable(args.freqtrade, failures)
    for module in ("filelock", "cmaes", "pandas", "pyarrow"):
        check_module(module, failures)

    data = inspect_data(args.data_dir.resolve(), failures)
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
            "public_market_metadata_only": True,
            "trading_idea_selection": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
