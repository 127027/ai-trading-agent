import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "research" / "ten_day_challenge"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import walk_forward  # noqa: E402


def challenge() -> dict:
    return json.loads((MODULE_DIR / "challenge.json").read_text(encoding="utf-8"))


def test_walk_forward_pool_supports_more_than_one_thousand_unique_daily_runs():
    starts = walk_forward.eligible_test_starts(challenge())
    assert len(starts) > 1000
    assert len(starts) == len(set(starts))


def test_each_run_has_exactly_one_year_of_allowed_history_and_ten_blind_days():
    config = challenge()
    test_start = date(2025, 4, 17)
    history_start, optimize_start, history_end = walk_forward.training_bounds(
        config, test_start
    )
    assert history_end == test_start
    assert (history_end - history_start).days == 365
    assert optimize_start > history_start
    assert optimize_start < test_start
    assert test_start + timedelta(days=config["window_days"]) <= date.fromisoformat(
        config["dataset_end"]
    )


def test_random_window_selection_never_reuses_a_seen_window():
    config = challenge()
    first = walk_forward.choose_test_start(config, {"used_test_windows": []}, 1)
    second = walk_forward.choose_test_start(
        config, {"used_test_windows": [first.isoformat()]}, 2
    )
    assert second != first


def test_parameter_fingerprint_is_stable_and_changes_with_parameters(tmp_path):
    path = tmp_path / "params.json"
    path.write_text('{"a": 1, "b": 2}', encoding="utf-8")
    first = walk_forward.parameter_fingerprint(path)
    path.write_text('{"b": 2, "a": 1}', encoding="utf-8")
    assert walk_forward.parameter_fingerprint(path) == first
    path.write_text('{"a": 1, "b": 3}', encoding="utf-8")
    assert walk_forward.parameter_fingerprint(path) != first


def test_learning_directive_distinguishes_inactive_miss_and_target_hit():
    class Result:
        target_balance = 200.0
        target_hit = False
        final_balance = 100.0
        trades = 0

    result = Result()
    assert walk_forward.learning_directive(result).startswith("increase_signal")
    result.trades = 12
    result.final_balance = 182.0
    assert walk_forward.learning_directive(result).startswith("near_target")
    result.target_hit = True
    result.final_balance = 205.0
    assert walk_forward.learning_directive(result).startswith("target_hit")
