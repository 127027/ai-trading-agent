"""V6-clean entrypoint: isolated state plus strengthened six-agent research."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import agentic_walk_forward as base
import agentic_walk_forward_v4 as engine
from agent_quality import (
    make_enriched_classifier,
    meta_learning_report,
    validate_research_plan,
)
from evolution import classify_regime as original_classify_regime

GENERATION = "contextual-signal-v6-clean"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _reset_old_generation(root: Path) -> None:
    """Remove persisted V4/V5/V5.1 research evidence before V6 Run 1."""
    research_root = root / "research" / "ten_day_challenge"
    state_path = research_root / "walk-forward-state.json"
    state = _load(state_path)
    if state.get("agent_generation") == GENERATION:
        return

    for path in (
        state_path,
        research_root / "research-memory.json",
        research_root / "latest-margin-result.json",
        root / "runtime/user_data/strategies/candidates/TenDayAdaptiveV2.json",
    ):
        path.unlink(missing_ok=True)

    for directory in (
        research_root / "results" / "agentic-walk-forward",
        research_root / "agentic-champion",
    ):
        if directory.exists():
            shutil.rmtree(directory)


def execute_one_run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    research_root = root / "research" / "ten_day_challenge"
    _reset_old_generation(root)

    enriched = make_enriched_classifier(original_classify_regime)
    base.classify_regime = enriched
    engine.classify_regime = enriched

    original_validate = base.validate_candidate

    def strengthened_validate_candidate(**kwargs: Any) -> str:
        selected = original_validate(**kwargs)
        plan = kwargs["plan"]
        memory = _load(research_root / "research-memory.json")
        validate_research_plan(
            plan,
            {"label": plan.get("regime"), "blind_window_seen": False},
            memory,
        )
        return selected

    base.validate_candidate = strengthened_validate_candidate
    record = engine.execute_one_run(args)

    memory_path = research_root / "research-memory.json"
    state_path = research_root / "walk-forward-state.json"
    memory = _load(memory_path)
    state = _load(state_path)
    report = meta_learning_report(memory, window=20)
    state["supervisor_meta_learning"] = report
    if report.get("directive"):
        state["learning_directive"] = report["directive"]
    state["agent_generation"] = GENERATION
    state["clean_generation_started_at_run"] = 1
    state["inherited_run_state"] = False
    state["inherited_research_memory"] = False
    _write(state_path, state)

    record["supervisor_meta_learning"] = report
    record["agent_generation"] = GENERATION
    record["inherited_run_state"] = False
    record["inherited_research_memory"] = False
    run_path = (
        research_root
        / "results"
        / "agentic-walk-forward"
        / f"run-{int(record['run']):06d}"
        / "run.json"
    )
    _write(run_path, record)
    return record


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
