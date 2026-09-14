"""Freeze a blind research run at the first valid target-balance hit.

The binary challenge is complete as soon as simulated equity reaches the target.
Any trades exported after that point belong to the same blind market window but are
not part of the scored run and must not be allowed to give the target back.
"""

from __future__ import annotations

from typing import Any


def _drawdown_pct(starting_balance: float, evidence: list[dict[str, Any]]) -> float:
    peak = float(starting_balance)
    max_drawdown = 0.0
    for item in evidence:
        equity = float(item["equity_after"])
        peak = max(peak, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown * 100.0


def lock_first_target(
    result: Any,
    margin: dict[str, Any],
    *,
    starting_balance: float,
    target_balance: float,
    near_ruin_balance: float,
) -> tuple[Any, dict[str, Any]]:
    """Score the run only through the trade that first reaches the target."""

    hit_index = margin.get("target_hit_trade_index")
    evidence = list(margin.get("trade_evidence") or [])
    if hit_index is None:
        margin["target_locked"] = False
        margin["post_hit_trades_discarded"] = 0
        return result, margin

    index = int(hit_index)
    if index < 0 or index >= len(evidence):
        raise ValueError("target_hit_trade_index is outside trade_evidence")

    scored_evidence = evidence[: index + 1]
    final_balance = float(scored_evidence[-1]["equity_after"])
    if final_balance < float(target_balance):
        raise ValueError("target hit evidence does not reach target balance")

    original_count = len(evidence)
    total_interest = sum(float(item.get("interest_paid") or 0.0) for item in scored_evidence)
    lowest = min(
        [float(starting_balance)]
        + [float(item["equity_after"]) for item in scored_evidence]
    )
    max_drawdown = _drawdown_pct(float(starting_balance), scored_evidence)

    margin.update(
        {
            "final_balance": final_balance,
            "return_pct": (final_balance / float(starting_balance) - 1.0) * 100.0,
            "target_hit": True,
            "target_hit_trade_index": index,
            "near_ruin": lowest <= float(near_ruin_balance),
            "max_drawdown_pct": max_drawdown,
            "liquidated": False,
            "liquidation_trade_index": None,
            "borrow_interest_paid": total_interest,
            "trades_processed": index + 1,
            "trade_evidence": scored_evidence,
            "target_locked": True,
            "post_hit_trades_discarded": max(0, original_count - len(scored_evidence)),
        }
    )

    result.final_balance = final_balance
    result.return_pct = margin["return_pct"]
    result.target_hit = True
    result.trades = index + 1
    result.max_drawdown_pct = max_drawdown
    result.near_ruin = margin["near_ruin"]
    return result, margin
