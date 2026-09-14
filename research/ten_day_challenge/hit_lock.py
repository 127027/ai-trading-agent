"""Freeze scored success at the first target hit while preserving shadow diagnostics.

The challenge is passed as soon as simulated equity first reaches the target. Later
trades therefore cannot revoke the HIT. For live-readiness learning, however, the
full-window outcome is retained as shadow evidence so strategies that would give
all gains back after the hit remain visible to the research loop.
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
    """Score only through first target hit, but retain full-window shadow outcome."""

    hit_index = margin.get("target_hit_trade_index")
    evidence = list(margin.get("trade_evidence") or [])
    if hit_index is None:
        margin["target_locked"] = False
        margin["post_hit_trades_discarded"] = 0
        margin["post_hit_shadow"] = None
        return result, margin

    index = int(hit_index)
    if index < 0 or index >= len(evidence):
        raise ValueError("target_hit_trade_index is outside trade_evidence")

    scored_evidence = evidence[: index + 1]
    final_balance = float(scored_evidence[-1]["equity_after"])
    if final_balance < float(target_balance):
        raise ValueError("target hit evidence does not reach target balance")

    original_count = len(evidence)
    shadow = {
        "full_window_final_balance": float(margin.get("final_balance") or 0.0),
        "full_window_return_pct": float(margin.get("return_pct") or 0.0),
        "full_window_max_drawdown_pct": float(margin.get("max_drawdown_pct") or 0.0),
        "full_window_liquidated": bool(margin.get("liquidated")),
        "full_window_liquidation_trade_index": margin.get("liquidation_trade_index"),
        "full_window_trades_processed": int(margin.get("trades_processed") or original_count),
        "post_hit_trade_count": max(0, original_count - len(scored_evidence)),
        "gave_back_below_target": float(margin.get("final_balance") or 0.0) < float(target_balance),
        "gave_back_below_start": float(margin.get("final_balance") or 0.0) < float(starting_balance),
    }

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
            "post_hit_shadow": shadow,
        }
    )

    result.final_balance = final_balance
    result.return_pct = margin["return_pct"]
    result.target_hit = True
    result.trades = index + 1
    result.max_drawdown_pct = max_drawdown
    result.near_ruin = margin["near_ruin"]
    return result, margin
