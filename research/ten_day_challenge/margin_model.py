"""Research-only Binance isolated-margin accounting for blind backtests.

This module never talks to Binance and never places orders. It applies documented
isolated-margin leverage/liquidation rules to Freqtrade-exported trades so the
research loop cannot claim a leveraged HIT by merely multiplying a spot balance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarginSpec:
    leverage: int
    liquidation_margin_level: float
    liquidation_fee_fraction: float
    borrow_interest_apr: float
    product: str = "binance_isolated_margin"
    direction: str = "long"


def _float(trade: dict[str, Any], key: str) -> float:
    value = trade.get(key)
    if value is None:
        raise ValueError(f"leveraged research requires trade field {key!r}")
    return float(value)


def _duration_days(trade: dict[str, Any]) -> float:
    minutes = trade.get("trade_duration")
    if minutes is None:
        return 0.0
    return max(0.0, float(minutes)) / 1440.0


def apply_isolated_margin(
    trades: list[dict[str, Any]],
    *,
    starting_balance: float,
    target_balance: float,
    near_ruin_balance: float,
    spec: MarginSpec,
) -> dict[str, Any]:
    """Apply isolated-margin economics to sequential long trades.

    Freqtrade's ``profit_ratio`` already contains the configured round-trip fee
    proxy on the underlying trade. Multiplying that return by leverage therefore
    scales both market PnL and trading-cost drag with notional. Borrow interest is
    charged separately. Liquidation is checked with each trade's recorded
    ``min_rate`` so an adverse excursion cannot be hidden by a profitable close.
    """

    if spec.direction != "long":
        raise ValueError("only long isolated-margin research is implemented")
    if spec.leverage < 1:
        raise ValueError("leverage must be >= 1")
    if spec.leverage == 1:
        raise ValueError("margin model is only for leverage > 1")

    equity = float(starting_balance)
    peak = equity
    lowest = equity
    max_drawdown = 0.0
    hit_at_index: int | None = None
    liquidated = False
    liquidation_trade_index: int | None = None
    total_interest = 0.0
    trades_processed = 0

    # Asset value / debt <= margin level triggers liquidation. For a long opened
    # with equity E and leverage L: notional=L*E, debt=(L-1)*E.
    liquidation_price_ratio = (
        spec.liquidation_margin_level * (spec.leverage - 1) / spec.leverage
    )

    for index, trade in enumerate(trades):
        if equity <= 0.0:
            break
        open_rate = _float(trade, "open_rate")
        min_rate = _float(trade, "min_rate")
        if open_rate <= 0.0:
            raise ValueError("open_rate must be positive")

        debt = equity * (spec.leverage - 1)
        interest = debt * spec.borrow_interest_apr * _duration_days(trade) / 365.0
        total_interest += interest

        if min_rate / open_rate <= liquidation_price_ratio:
            # At the documented margin-level threshold, collateral value is
            # margin_level * debt. Repay principal, liquidation fee, and accrued
            # borrow interest; any residual remains as simulated account equity.
            residual = (
                spec.liquidation_margin_level * debt
                - debt
                - spec.liquidation_fee_fraction * debt
                - interest
            )
            equity = max(0.0, residual)
            liquidated = True
            liquidation_trade_index = index
            trades_processed += 1
            lowest = min(lowest, equity)
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
            # The original spot export no longer represents the post-liquidation
            # signal path, so continuing through later trades would fabricate data.
            break

        profit_ratio = _float(trade, "profit_ratio")
        equity = max(0.0, equity + equity * spec.leverage * profit_ratio - interest)
        trades_processed += 1
        lowest = min(lowest, equity)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        if hit_at_index is None and equity >= target_balance:
            hit_at_index = index

    return {
        "final_balance": equity,
        "return_pct": (equity / starting_balance - 1.0) * 100.0,
        "target_hit": hit_at_index is not None,
        "target_hit_trade_index": hit_at_index,
        "near_ruin": lowest <= near_ruin_balance,
        "max_drawdown_pct": max_drawdown * 100.0,
        "liquidated": liquidated,
        "liquidation_trade_index": liquidation_trade_index,
        "liquidation_price_ratio": liquidation_price_ratio,
        "borrow_interest_paid": total_interest,
        "trades_processed": trades_processed,
        "product": spec.product,
        "direction": spec.direction,
        "leverage": spec.leverage,
    }
