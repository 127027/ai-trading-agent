"""Dispatch the next bounded research segment while continuous mode remains enabled."""

from __future__ import annotations

import argparse
import base64
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

CONTROL_PATH = "research/ten_day_challenge/continuous-control.json"
WORKFLOW_PATH = "ten-day-research.yml"


def github_json(url: str, token: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ten-day-research-agent",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--current-segment", choices=("1", "2"), required=True)
    parser.add_argument("--workflow", default=WORKFLOW_PATH)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")

    control_url = (
        f"https://api.github.com/repos/{args.repository}/contents/{CONTROL_PATH}"
        f"?ref={quote(args.ref, safe='')}"
    )
    try:
        response = github_json(control_url, token)
    except HTTPError as exc:
        raise SystemExit(f"failed to read continuous control: HTTP {exc.code}") from exc

    encoded = str(response.get("content") or "").replace("\n", "")
    if not encoded:
        raise SystemExit("continuous control content missing")
    control = json.loads(base64.b64decode(encoded).decode("utf-8"))

    safe = bool(control.get("paper_only")) and not bool(control.get("live_trading_allowed"))
    enabled = bool(control.get("enabled")) and not bool(control.get("stop_requested"))
    if not safe:
        raise SystemExit("continuous control violated paper-only safety invariant")
    if not enabled:
        print(json.dumps({"status": "stopped_by_control", "segment": args.current_segment}))
        return 0

    key = f"next_after_segment_{args.current_segment}"
    next_segment = str(control.get(key) or "")
    if next_segment not in {"1", "2"}:
        raise SystemExit(f"invalid next segment in control: {next_segment!r}")

    dispatch_url = (
        f"https://api.github.com/repos/{args.repository}/actions/workflows/"
        f"{quote(args.workflow, safe='')}/dispatches"
    )
    try:
        github_json(
            dispatch_url,
            token,
            method="POST",
            payload={"ref": args.ref, "inputs": {"segment": next_segment}},
        )
    except HTTPError as exc:
        raise SystemExit(f"failed to dispatch next segment: HTTP {exc.code}") from exc

    print(
        json.dumps(
            {
                "status": "next_segment_dispatched",
                "current_segment": args.current_segment,
                "next_segment": next_segment,
                "continuous": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
