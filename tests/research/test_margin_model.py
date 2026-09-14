import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research" / "ten_day_challenge"
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

SPEC = spec_from_file_location("margin_model", RESEARCH / "margin_model.py")
assert SPEC and SPEC.loader
margin_model = module_from_spec(SPEC)
sys.modules[SPEC.name] = margin_model
SPEC.loader.exec_module(margin_model)

HIT_LOCK_SPEC = spec_from_file_location("hit_lock", RESEARCH / "hit_lock.py")
assert HIT_LOCK_SPEC and HIT_LOCK_SPEC.loader
hit_lock = module_from_spec(HIT_LOCK_SPEC)
sys.modules[HIT_LOCK_SPEC.name] = hit_lock
HIT_LOCK_SPEC.loader.exec_module(hit_lock)


def trade(
    profit_ratio: float,
    min_rate: float = 100.0,
    *,
    leverage_tag: int | None = None,
) -> dict:
    tag = "adaptive_breakout"
    if leverage_tag is not None:
        tag += f"|lev={leverage_tag}"
    return {
        "pair": "BTC/USDT",
        "enter_tag": tag,
        "exit_reason": "roi",
        "open_rate": 100.0,
        "close_rate": 100.0 * (1.0 + profit_ratio),
        "min_rate": min_rate,
        "max_rate": 112.0,
        "profit_ratio": profit_ratio,
        "trade_duration": 60,
        "open_date": "2025-01-01T00:00:00+00:00",
        "close_date": "2025-01-01T01:00:00+00:00",
    }


def spec(leverage: int = 10) -> object:
    levels = {3: 1.18, 5: 1.15, 10: 1.05}
    return margin_model.MarginSpec(
        leverage=leverage,
        liquidation_margin_level=levels[leverage],
        liquidation_fee_fraction=0.02,
        borrow_interest_apr=0.0,
    )


def test_exact_200_is_hit_under_10x_research_accounting():
    result = margin_model.apply_isolated_margin(
        [trade(0.10, leverage_tag=10)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["final_balance"] == 200.0
    assert result["target_hit"] is True


def test_199_99_is_still_miss():
    result = margin_model.apply_isolated_margin(
        [trade(0.09999, leverage_tag=10)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["final_balance"] < 200.0
    assert result["target_hit"] is False


def test_same_signal_profit_scales_with_entry_time_leverage():
    low = margin_model.apply_isolated_margin(
        [trade(0.05, leverage_tag=1)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    high = margin_model.apply_isolated_margin(
        [trade(0.05, leverage_tag=10)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert low["final_balance"] == pytest.approx(105.0)
    assert high["final_balance"] == pytest.approx(150.0)
    assert low["trade_evidence"][0]["leverage"] == 1
    assert high["trade_evidence"][0]["leverage"] == 10


def test_intermediate_entry_leverage_is_preserved():
    result = margin_model.apply_isolated_margin(
        [trade(0.05, leverage_tag=7)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["final_balance"] == pytest.approx(135.0)
    assert result["trade_evidence"][0]["leverage"] == 7
    assert result["leverage_counts"]["7"] == 1


def test_10x_adverse_excursion_triggers_liquidation_before_profitable_close():
    result = margin_model.apply_isolated_margin(
        [trade(0.20, min_rate=94.0, leverage_tag=10)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["liquidated"] is True
    assert result["target_hit"] is False
    assert result["final_balance"] < 100.0


def test_one_x_never_margin_liquidates_same_adverse_excursion():
    result = margin_model.apply_isolated_margin(
        [trade(-0.06, min_rate=94.0, leverage_tag=1)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["liquidated"] is False
    assert result["final_balance"] == pytest.approx(94.0)


def test_total_loss_is_valid_miss_not_success():
    result = margin_model.apply_isolated_margin(
        [trade(-0.50, min_rate=100.0, leverage_tag=10)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["final_balance"] == 0.0
    assert result["target_hit"] is False
    assert result["near_ruin"] is True


def test_trade_evidence_contains_context_for_future_learning():
    result = margin_model.apply_isolated_margin(
        [trade(0.05, min_rate=98.0, leverage_tag=5)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    evidence = result["trade_evidence"]
    assert len(evidence) == 1
    item = evidence[0]
    assert item["pair"] == "BTC/USDT"
    assert item["enter_tag"].endswith("lev=5")
    assert item["exit_reason"] == "roi"
    assert item["mae_pct"] == pytest.approx(-2.0)
    assert item["mfe_pct"] == pytest.approx(12.0)
    assert item["equity_change"] > 0.0
    assert item["profitable"] is True


def test_first_200_hit_is_locked_but_shadow_keeps_later_damage():
    evidence = [
        {"equity_after": 150.0, "interest_paid": 0.10},
        {"equity_after": 225.0, "interest_paid": 0.20},
        {"equity_after": 50.0, "interest_paid": 0.30},
    ]
    margin = {
        "final_balance": 50.0,
        "return_pct": -50.0,
        "target_hit": True,
        "target_hit_trade_index": 1,
        "near_ruin": False,
        "max_drawdown_pct": 77.78,
        "liquidated": False,
        "liquidation_trade_index": None,
        "borrow_interest_paid": 0.60,
        "trades_processed": 3,
        "trade_evidence": evidence,
    }
    result = SimpleNamespace(
        final_balance=50.0,
        return_pct=-50.0,
        target_hit=True,
        trades=3,
        max_drawdown_pct=77.78,
        near_ruin=False,
    )

    result, margin = hit_lock.lock_first_target(
        result,
        margin,
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
    )

    assert result.final_balance == 225.0
    assert result.return_pct == 125.0
    assert result.trades == 2
    assert margin["final_balance"] == 225.0
    assert margin["trades_processed"] == 2
    assert len(margin["trade_evidence"]) == 2
    assert margin["borrow_interest_paid"] == pytest.approx(0.30)
    assert margin["target_locked"] is True
    assert margin["post_hit_trades_discarded"] == 1
    assert margin["post_hit_shadow"]["full_window_final_balance"] == 50.0
    assert margin["post_hit_shadow"]["gave_back_below_target"] is True
    assert margin["post_hit_shadow"]["gave_back_below_start"] is True
