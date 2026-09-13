"""V5.1 entrypoint: stronger evidence context and supervisor meta-learning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import agentic_walk_forward as base
import agentic_walk_forward_v4 as engine
from agent_quality import make_enriched_classifier, meta_learning_report
from evolution import classify_regime as original_classify_regime


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute_one_run(args: argparse.Namespace) -> dict:
    # Raster 2 and the pre-window leverage policy use the same enriched evidence.
    enriched = make_enriched_classifier(original_classify_regime)
    base.classify_regime = enriched
    engine.classify_regime = enriched

    record = engine.execute_one_run(args)

    # Raster 6 owns learning-progress/stagnation diagnosis across completed runs.
    root = args.root.resolve()
    research_root = root / "research" / "ten_day_challenge"
    memory_path = research_root / "research-memory.json"
    state_path = research_root / "walk-forward-state.json"
    memory = _load(memory_path)
    state = _load(state_path)
    report = meta_learning_report(memory, window=20)
    state["supervisor_meta_learning"] = report
    if report.get("directive"):
        state["learning_directive"] = report["directive"]
    state["agent_generation"] = "contextual-signal-v5.1"
    _write(state_path, state)

    record["supervisor_meta_learning"] = report
    record["agent_generation"] = "contextual-signal-v5.1"
    run_path = research_root / "results" / "agentic-walk-forward" / f"run-{int(record['run']):06d}" / "run.json"
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
