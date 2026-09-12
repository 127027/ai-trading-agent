"""Run a research command with immediate whitelisted OpsWatchdog repairs."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=4)
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
        returncode = run_streamed(command, root, args.log)
        output = args.log.read_text(encoding="utf-8", errors="replace")
        record: dict[str, object] = {
            "attempt": attempt,
            "returncode": returncode,
            "repairs": [],
        }
        history.append(record)

        if returncode == 0:
            report = {
                "agent": "OpsWatchdog",
                "status": "healthy",
                "attempts": attempt,
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
                "history": history,
            }
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, sort_keys=True))
            return returncode or 2

        print(f"OpsWatchdog applied safe repairs: {actions}")

    report = {
        "agent": "OpsWatchdog",
        "status": "repair_limit_reached",
        "attempts": attempts,
        "history": history,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
