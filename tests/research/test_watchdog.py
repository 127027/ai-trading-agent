import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "research" / "ten_day_challenge"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import watchdog  # noqa: E402


def _touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def test_run_two_does_not_require_optional_research_inbox(tmp_path, monkeypatch):
    required = [
        "research/ten_day_challenge/challenge.json",
        "research/ten_day_challenge/agents.json",
        "research/ten_day_challenge/agentic_walk_forward.py",
        "research/ten_day_challenge/evolution.py",
        "research/ten_day_challenge/rolling_windows.py",
        "research/ten_day_challenge/freqtrade_public.py",
        "runtime/user_data/config-10day-research.json",
        "runtime/user_data/strategies/candidates/TenDayAdaptiveV2.py",
        "runtime/user_data/hyperopts/TenDayChallengeLoss.py",
    ]
    for relative in required:
        _touch(tmp_path, relative)

    research = tmp_path / "research/ten_day_challenge"
    (research / "walk-forward-state.json").write_text(
        json.dumps({"run_count": 1}), encoding="utf-8"
    )
    (research / "research-memory.json").write_text("{}\n", encoding="utf-8")
    run = research / "results/agentic-walk-forward/run-000001/run.json"
    run.parent.mkdir(parents=True, exist_ok=True)
    run.write_text("{}\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sample.feather").write_bytes(b"data")
    python = tmp_path / "python"
    freqtrade = tmp_path / "freqtrade"
    python.write_text("", encoding="utf-8")
    freqtrade.write_text("", encoding="utf-8")
    output = tmp_path / "health.json"

    monkeypatch.setattr(watchdog, "install_public_freqtrade_launcher", lambda *args: None)
    monkeypatch.setattr(watchdog, "check_executable", lambda *args: None)
    monkeypatch.setattr(watchdog, "check_module", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "watchdog.py",
            "--root",
            str(tmp_path),
            "--data-dir",
            str(data_dir),
            "--python",
            str(python),
            "--freqtrade",
            str(freqtrade),
            "--output",
            str(output),
        ],
    )

    assert watchdog.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["healthy"] is True
    assert report["checkpoint"]["run_count"] == 1
    assert report["checkpoint"]["research_memory_present"] is True
    assert report["checkpoint"]["research_inbox_present"] is False
