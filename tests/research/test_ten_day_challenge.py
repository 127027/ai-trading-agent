import json
import sys
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "research" / "ten_day_challenge" / "rolling_windows.py"
SPEC = spec_from_file_location("rolling_windows", MODULE_PATH)
assert SPEC and SPEC.loader
rolling = module_from_spec(SPEC)
sys.modules[SPEC.name] = rolling
SPEC.loader.exec_module(rolling)

COUNCIL_PATH = ROOT / "research" / "ten_day_challenge" / "council.py"
COUNCIL_SPEC = spec_from_file_location("ten_day_council", COUNCIL_PATH)
assert COUNCIL_SPEC and COUNCIL_SPEC.loader
council = module_from_spec(COUNCIL_SPEC)
COUNCIL_SPEC.loader.exec_module(council)
AGENTS = json.loads(
    (ROOT / "research" / "ten_day_challenge" / "agents.json").read_text(encoding="utf-8")
)


def test_full_year_has_356_overlapping_ten_day_windows():
    windows = list(rolling.iter_windows(date(2025, 9, 1), date(2026, 9, 1), 10, 1))
    assert len(windows) == 356
    assert windows[0].timerange == "20250901-20250911"
    assert windows[-1].timerange == "20260822-20260901"


def test_validation_step_is_search_acceleration_only():
    windows = list(rolling.iter_windows(date(2026, 5, 1), date(2026, 7, 1), 10, 2))
    assert windows[0].start == date(2026, 5, 1)
    assert all((b.start - a.start).days == 2 for a, b in pairwise(windows))


def test_backtest_command_resets_wallet_and_uses_isolated_export_directory(tmp_path):
    window = rolling.Window(date(2025, 9, 1), date(2025, 9, 11))
    export_directory = tmp_path / "exports"
    command = rolling.build_backtest_command(
        "freqtrade",
        tmp_path / "config.json",
        tmp_path / "user_data",
        tmp_path / "strategies",
        tmp_path / "data",
        "TenDayMomentumV1",
        window,
        export_directory,
        100.0,
        0.0015,
        "5m",
    )
    assert command[0:2] == ["freqtrade", "backtesting"]
    assert command[command.index("--dry-run-wallet") + 1] == "100.0"
    assert command[command.index("--timerange") + 1] == "20250901-20250911"
    assert command[command.index("--fee") + 1] == "0.0015"
    assert command[command.index("--cache") + 1] == "none"
    assert command[command.index("--backtest-directory") + 1] == str(export_directory)
    assert "--backtest-filename" not in command
    assert "--enable-protections" in command
    assert command[command.index("--timeframe-detail") + 1] == "5m"


def test_newest_export_prefers_zip_and_ignores_meta_json(tmp_path):
    (tmp_path / "backtest-result.meta.json").write_text("{}", encoding="utf-8")
    plain = tmp_path / "backtest-result.json"
    plain.write_text("{}", encoding="utf-8")
    assert rolling.newest_export(tmp_path) == plain
    zipped = tmp_path / "backtest-result.zip"
    zipped.write_bytes(b"not-a-real-zip")
    assert rolling.newest_export(tmp_path) == zipped


def test_six_research_roles_are_explicit():
    names = {item["agent"] for item in AGENTS["raster_policy"]["ordered_rasters"]}
    assert names == {
        "OpsWatchdog",
        "EvidenceRegimeAgent",
        "EvolutionResearchAgent",
        "BuildValidationAgent",
        "QuantExperimentAgent",
        "TenDaySupervisor",
    }


def test_raster_order_uses_ops_as_central_recovery_owner():
    policy = AGENTS["raster_policy"]
    rasters = policy["ordered_rasters"]
    assert [item["raster"] for item in rasters] == [1, 2, 3, 4, 5, 6]
    assert [item["agent"] for item in rasters] == [
        "OpsWatchdog",
        "EvidenceRegimeAgent",
        "EvolutionResearchAgent",
        "BuildValidationAgent",
        "QuantExperimentAgent",
        "TenDaySupervisor",
    ]
    assert policy["on_any_raster_rejection"] == "return_same_run_to_raster_1"
    assert policy["on_technical_failure"] == "return_same_run_to_raster_1"
    assert policy["run_completes_only_after_raster"] == 6
    assert policy["on_target_miss_at_raster_6"] == "checkpoint_learning_then_new_full_cycle_at_raster_1"
    ops = AGENTS["operations_agent"]
    assert ops["owns_all_failure_and_rejection_handoffs"] is True
    assert ops["restart_same_run_after_rejection"] is True


def test_agent_council_allows_complete_low_risk_candidate():
    review = council.evaluate_candidate(
        {
            "valid": True,
            "windows_completed": 26,
            "windows_failed": 0,
            "target_hit_rate": 0.10,
            "median_return_pct": 4.0,
            "near_ruin_rate": 0.0,
            "median_max_drawdown_pct": 12.0,
        },
        AGENTS,
    )
    assert review["supervisor"] == "TenDaySupervisor"
    assert review["promotion_eligible"] is True
    assert review["veto_agents"] == []


def test_reviewer_rasters_are_callable_independently():
    summary = {
        "valid": True,
        "windows_completed": 26,
        "windows_failed": 0,
        "target_hit_rate": 0.25,
        "median_return_pct": 8.0,
        "near_ruin_rate": 0.0,
        "median_max_drawdown_pct": 10.0,
    }
    assert council.quant_review(summary)["agent"] == "QuantExperimentAgent"
    assert council.validation_review(summary, AGENTS)["agent"] == "BuildValidationAgent"
    assert council.risk_review(summary, AGENTS)["agent"] == "TenDaySupervisor"


def test_aggressive_target_candidate_is_not_vetoed_only_for_near_ruin_or_drawdown():
    review = council.evaluate_candidate(
        {
            "valid": True,
            "windows_completed": 26,
            "windows_failed": 0,
            "target_hit_rate": 0.80,
            "median_return_pct": 70.0,
            "near_ruin_rate": 0.04,
            "median_max_drawdown_pct": 20.0,
        },
        AGENTS,
    )
    assert review["veto"] is False
    assert "TenDaySupervisor" not in review["veto_agents"]
    assert review["promotion_eligible"] is True
