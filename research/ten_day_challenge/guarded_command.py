"""Run a research command with immediate whitelisted OpsWatchdog repairs.

Raster 1 (OpsWatchdog) is mandatory before every guarded attempt. If a later
raster fails and a whitelisted repair is applied, execution loops back through
Raster 1 before retrying the failed command.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from repair_known_failures import repair


def run_streamed(command: list[str], cwd: Path, log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        return process.wait()


def run_raster_1_health_gate(
    root: Path,
    data_dir: Path,
    python_executable: Path,
    freqtrade_executable: Path,
    output: Path,
) -> tuple[int, str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(python_executable),
        str(root / "research/ten_day_challenge/watchdog.py"),
        "--root",
        str(root),
        "--data-dir",
        str(data_dir),
        "--python",
        str(python_executable),
        "--freqtrade",
        str(freqtrade_executable),
        "--output",
        str(output),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    text = completed.stdout or ""
    print(text, end="")
    return completed.returncode, text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--health-data-dir", type=Path, required=True)
    parser.add_argument("--health-python", type=Path, required=True)
    parser.add_argument("--health-freqtrade", type=Path, required=True)
    parser.add_argument("--health-output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("missing guarded command")

    root = args.root.resolve()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, object]] = []
    attempts = max(1, args.attempts)

    for attempt in range(1, attempts + 1):
        health_code, health_text = run_raster_1_health_gate(
            root,
            args.health_data_dir.resolve(),
            args.health_python,
            args.health_freqtrade,
            args.health_output,
        )
        record: dict[str, object] = {
            "attempt": attempt,
            "raster_1_health_returncode": health_code,
            "returncode": None,
            "repairs": [],
        }
        history.append(record)

        if health_code != 0:
            actions = repair(root, health_text)
            record["repairs"] = actions
            if actions:
                print(f"Raster 1 applied safe repairs: {actions}; restarting at raster 1")
                continue
            report = {
                "agent": "OpsWatchdog",
                "status": "raster_1_blocker",
                "attempts": attempt,
                "history": history,
            }
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, sort_keys=True))
            return health_code or 2

        returncode = run_streamed(command, root, args.log)
        record["returncode"] = returncode
        output = args.log.read_text(encoding="utf-8", errors="replace")

        if returncode == 0:
            report = {
                "agent": "OpsWatchdog",
                "status": "healthy",
                "attempts": attempt,
                "raster_policy": "raster_1_before_every_attempt",
                "history": history,
            }
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, sort_keys=True))
            return 0

        actions = repair(root, output)
        record["repairs"] = actions
        if not actions:
            report = {
                "agent": "OpsWatchdog",
                "status": "unknown_blocker",
                "attempts": attempt,
                "raster_policy": "return_to_raster_1_on_failure",
                "history": history,
            }
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, sort_keys=True))
            return returncode or 2

        print(
            f"OpsWatchdog applied safe repairs: {actions}. "
            "Returning to raster 1 before retry."
        )

    report = {
        "agent": "OpsWatchdog",
        "status": "repair_limit_reached",
        "attempts": attempts,
        "raster_policy": "return_to_raster_1_on_failure",
        "history": history,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
