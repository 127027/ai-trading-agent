"""Dispatch the next bounded walk-forward segment while research should continue."""

from __future__ import annotations

import argparse
import base64
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

CONTROL_PATH = "research/ten_day_challenge/continuous-control.json"
STATE_PATH = "research/ten_day_challenge/walk-forward-state.json"
WORKFLOW_PATH = "walk-forward-research.yml"


def github_json(
    url: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ten-day-walk-forward-research-agent",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def fetch_repo_json(repository: str, ref: str, path: str, token: str) -> dict:
    url = (
        f"https://api.github.com/repos/{repository}/contents/{path}"
        f"?ref={quote(ref, safe='')}"
    )
    response = github_json(url, token)
    encoded = str(response.get("content") or "").replace("\n", "")
    if not encoded:
        raise RuntimeError(f"repository JSON content missing: {path}")
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


def load_state(repository: str, ref: str, token: str) -> dict:
    try:
        return fetch_repo_json(repository, ref, STATE_PATH, token)
    except HTTPError as exc:
        if exc.code == 404:
            return {}
        raise SystemExit(f"failed to read walk-forward state: HTTP {exc.code}") from exc
    except RuntimeError as exc:
        raise SystemExit(f"failed to read walk-forward state: {exc}") from exc


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

    try:
        control = fetch_repo_json(args.repository, args.ref, CONTROL_PATH, token)
    except (HTTPError, RuntimeError) as exc:
        raise SystemExit(f"failed to read continuous control: {exc}") from exc

    safe = bool(control.get("paper_only")) and not bool(
        control.get("live_trading_allowed")
    )
    enabled = bool(control.get("enabled")) and not bool(control.get("stop_requested"))
    if not safe:
        raise SystemExit("continuous control violated paper-only safety invariant")
    if not enabled:
        print(
            json.dumps(
                {"status": "stopped_by_control", "segment": args.current_segment}
            )
        )
        return 0

    state = load_state(args.repository, args.ref, token)
    run_count = int(state.get("run_count") or 0)
    max_total_runs = control.get("max_total_runs")
    if max_total_runs is not None and run_count >= max(1, int(max_total_runs)):
        print(
            json.dumps(
                {
                    "status": "max_total_runs_reached",
                    "run_count": run_count,
                    "max_total_runs": int(max_total_runs),
                    "continuous": False,
                },
                sort_keys=True,
            )
        )
        return 0

    if bool(control.get("stop_after_required_hits", True)):
        required_hits = max(1, int(control.get("required_hits") or 1))
        hit_count = int(state.get("hit_count") or 0)
        if hit_count >= required_hits:
            print(
                json.dumps(
                    {
                        "status": "research_goal_reached",
                        "hit_count": hit_count,
                        "required_hits": required_hits,
                        "continuous": False,
                    },
                    sort_keys=True,
                )
            )
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
        raise SystemExit(
            f"failed to dispatch next segment: HTTP {exc.code}"
        ) from exc

    print(
        json.dumps(
            {
                "status": "next_segment_dispatched",
                "current_segment": args.current_segment,
                "next_segment": next_segment,
                "run_count": run_count,
                "max_total_runs": max_total_runs,
                "continuous": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
