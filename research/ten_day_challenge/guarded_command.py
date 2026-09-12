"""Run a research command with immediate whitelisted OpsWatchdog repairs."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from repair_known_failures import repair


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
        completed = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        output = completed.stdout or ""
        args.log.write_text(output, encoding="utf-8")
        print(output, end="")
        record: dict[str, object] = {
            "attempt": attempt,
            "returncode": completed.returncode,
            "repairs": [],
        }
        history.append(record)

        if completed.returncode == 0:
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
            return completed.returncode or 2

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
