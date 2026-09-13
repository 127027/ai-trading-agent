import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "research" / "ten_day_challenge"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import evolution  # noqa: E402


def test_six_rasters_have_distinct_development_responsibilities():
    config = json.loads((MODULE_DIR / "agents.json").read_text(encoding="utf-8"))
    rasters = config["raster_policy"]["ordered_rasters"]
    assert [item["raster"] for item in rasters] == [1, 2, 3, 4, 5, 6]
    assert [item["agent"] for item in rasters] == [
        "OpsWatchdog",
        "EvidenceRegimeAgent",
        "EvolutionResearchAgent",
        "BuildValidationAgent",
        "QuantExperimentAgent",
        "TenDaySupervisor",
    ]
    assert config["self_development"]["owner_raster"] == 3
    assert config["objective"]["stop_after_first_valid_hit"] is True


def test_research_plan_changes_with_regime_specific_evidence():
    memory = evolution.initial_memory()
    memory["family_regime_stats"] = {
        "bull_trend": {
            "breakout": {
                "attempts": 8,
                "hits": 0,
                "sum_final_balance": 720.0,
                "best_final_balance": 98.0,
                "zero_trade_runs": 2,
            },
            "trend_pullback": {
                "attempts": 5,
                "hits": 0,
                "sum_final_balance": 590.0,
                "best_final_balance": 132.0,
                "zero_trade_runs": 0,
            },
        }
    }
    state = {
        "learning_directive": "positive_but_slow_increase_return_velocity",
        "last_run": {"trades": 3, "final_balance": 118.0},
    }
    plan = evolution.plan_hypothesis(
        memory,
        state,
        {"label": "bull_trend"},
        run_id=40,
        inbox={"ideas": []},
    )
    assert plan["allowed_families"][0] == "trend_pullback"
    assert plan["blind_window_seen"] is False


def test_zero_trade_failure_pushes_research_toward_signal_producing_families():
    plan = evolution.plan_hypothesis(
        evolution.initial_memory(),
        {
            "learning_directive": "increase_signal_recall_and_trade_activity",
            "last_run": {"trades": 0, "final_balance": 100.0},
        },
        {"label": "sideways_low_vol"},
        run_id=2,
        inbox={"ideas": []},
    )
    assert plan["allowed_families"][0] in {
        "mean_reversion",
        "trend_pullback",
        "volatility_expansion",
    }
    assert any("zero trades" in reason for reason in plan["reasons"])


def test_completed_result_is_learned_per_regime_and_family():
    memory = evolution.initial_memory()
    plan = {
        "hypothesis_id": "abc123",
        "regime": "sideways_high_vol",
        "allowed_families": ["mean_reversion", "volatility_expansion"],
        "external_research_id": None,
    }
    record = {
        "run": 7,
        "outcome": "MISS",
        "final_balance": 123.4,
        "trades": 6,
        "selected_family": "mean_reversion",
        "parameter_fingerprint": "fingerprint-7",
    }
    evolution.update_memory_after_completed_run(memory, plan, record)
    stats = memory["family_regime_stats"]["sideways_high_vol"]["mean_reversion"]
    assert stats["attempts"] == 1
    assert stats["sum_final_balance"] == 123.4
    assert stats["best_final_balance"] == 123.4
    assert memory["hypothesis_history"][-1]["selected_family"] == "mean_reversion"


def test_extract_selected_family_from_freqtrade_style_parameter_payload():
    payload = {"strategy_name": "TenDayAdaptiveV2", "params": {"buy": {"family_mode": "breakout"}}}
    assert evolution.extract_selected_family(payload) == "breakout"
