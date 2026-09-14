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


def trade(profit_ratio: float, min_rate: float = 100.0) -> dict:
    return {
        "pair": "BTC/USDT",
        "enter_tag": "adaptive_breakout",
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
        [trade(0.10)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["final_balance"] == 200.0
    assert result["target_hit"] is True


def test_199_99_is_still_miss():
    result = margin_model.apply_isolated_margin(
        [trade(0.09999)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["final_balance"] < 200.0
    assert result["target_hit"] is False


def test_10x_adverse_excursion_triggers_liquidation_before_profitable_close():
    result = margin_model.apply_isolated_margin(
        [trade(0.20, min_rate=94.0)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(10),
    )
    assert result["liquidated"] is True
    assert result["target_hit"] is False
    assert result["final_balance"] < 100.0


def test_total_loss_is_valid_miss_not_success():
    result = margin_model.apply_isolated_margin(
        [trade(-0.50, min_rate=100.0)],
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
        [trade(0.05, min_rate=98.0)],
        starting_balance=100.0,
        target_balance=200.0,
        near_ruin_balance=10.0,
        spec=spec(5),
    )
    evidence = result["trade_evidence"]
    assert len(evidence) == 1
    item = evidence[0]
    assert item["pair"] == "BTC/USDT"
    assert item["enter_tag"] == "adaptive_breakout"
    assert item["exit_reason"] == "roi"
    assert item["mae_pct"] == pytest.approx(-2.0)
    assert item["mfe_pct"] == pytest.approx(12.0)
    assert item["equity_change"] > 0.0
    assert item["profitable"] is True


def test_first_200_hit_is_locked_and_later_losses_are_discarded():
    evidence = [
        {
            "equity_after": 150.0,
            "interest_paid": 0.10,
        },
        {
            "equity_after": 225.0,
            "interest_paid": 0.20,
        },
        {
            "equity_after": 50.0,
            "interest_paid": 0.30,
        },
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
