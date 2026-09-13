"""Research-only Binance isolated-margin accounting for blind backtests.

This module never talks to Binance and never places orders. It applies documented
isolated-margin leverage/liquidation rules to Freqtrade-exported trades so the
research loop cannot claim a leveraged HIT by merely multiplying a spot balance.
It also emits per-trade evidence for later runs. That evidence is written only
after the blind window has completed and is never used to redesign the current run.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rolling_windows import (
    Window,
    WindowResult,
    build_backtest_command,
    close_time,
    error_result,
    load_export,
    newest_export,
)


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


def _optional_float(trade: dict[str, Any], key: str) -> float | None:
    value = trade.get(key)
    return None if value is None else float(value)


def _duration_days(trade: dict[str, Any]) -> float:
    minutes = trade.get("trade_duration")
    if minutes is None:
        return 0.0
    return max(0.0, float(minutes)) / 1440.0


def _trade_evidence(
    trade: dict[str, Any],
    *,
    leverage: int,
    liquidated: bool,
    interest_paid: float,
    equity_before: float,
    equity_after: float,
) -> dict[str, Any]:
    open_rate = _float(trade, "open_rate")
    close_rate = _optional_float(trade, "close_rate")
    min_rate = _float(trade, "min_rate")
    max_rate = _optional_float(trade, "max_rate")
    profit_ratio = _optional_float(trade, "profit_ratio") or 0.0
    mae_pct = (min_rate / open_rate - 1.0) * 100.0 if open_rate else 0.0
    mfe_pct = None
    if max_rate is not None and open_rate:
        mfe_pct = (max_rate / open_rate - 1.0) * 100.0
    opened = trade.get("open_date") or trade.get("open_date_utc")
    closed = trade.get("close_date") or trade.get("close_date_utc")
    return {
        "pair": str(trade.get("pair") or "unknown"),
        "enter_tag": str(trade.get("enter_tag") or "unknown"),
        "exit_reason": str(trade.get("exit_reason") or "unknown"),
        "open_date": opened,
        "close_date": closed,
        "open_rate": open_rate,
        "close_rate": close_rate,
        "profit_ratio_spot": profit_ratio,
        "leveraged_profit_ratio_before_interest": profit_ratio * leverage,
        "mae_pct": mae_pct,
        "mfe_pct": mfe_pct,
        "trade_duration_minutes": float(trade.get("trade_duration") or 0.0),
        "leverage": leverage,
        "interest_paid": interest_paid,
        "equity_before": equity_before,
        "equity_after": equity_after,
        "equity_change": equity_after - equity_before,
        "profitable": equity_after > equity_before,
        "liquidated": liquidated,
    }


def apply_isolated_margin(
    trades: list[dict[str, Any]],
    *,
    starting_balance: float,
    target_balance: float,
    near_ruin_balance: float,
    spec: MarginSpec,
) -> dict[str, Any]:
    """Apply isolated-margin economics to sequential long trades."""

    if spec.direction != "long":
        raise ValueError("only long isolated-margin research is implemented")
    if spec.leverage <= 1:
        raise ValueError("margin model requires leverage > 1")

    equity = float(starting_balance)
    peak = equity
    lowest = equity
    max_drawdown = 0.0
    hit_at_index: int | None = None
    liquidated = False
    liquidation_trade_index: int | None = None
    total_interest = 0.0
    trades_processed = 0
    trade_evidence: list[dict[str, Any]] = []

    liquidation_price_ratio = (
        spec.liquidation_margin_level * (spec.leverage - 1) / spec.leverage
    )

    for index, trade in enumerate(trades):
        if equity <= 0.0:
            break
        equity_before = equity
        open_rate = _float(trade, "open_rate")
        min_rate = _float(trade, "min_rate")
        if open_rate <= 0.0:
            raise ValueError("open_rate must be positive")

        debt = equity * (spec.leverage - 1)
        interest = debt * spec.borrow_interest_apr * _duration_days(trade) / 365.0
        total_interest += interest

        if min_rate / open_rate <= liquidation_price_ratio:
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
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
            trade_evidence.append(
                _trade_evidence(
                    trade,
                    leverage=spec.leverage,
                    liquidated=True,
                    interest_paid=interest,
                    equity_before=equity_before,
                    equity_after=equity,
                )
            )
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
        trade_evidence.append(
            _trade_evidence(
                trade,
                leverage=spec.leverage,
                liquidated=False,
                interest_paid=interest,
                equity_before=equity_before,
                equity_after=equity,
            )
        )

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
        "trade_evidence": trade_evidence,
        "product": spec.product,
        "direction": spec.direction,
        "leverage": spec.leverage,
    }


def run_margin_window(
    window: Window,
    *,
    freqtrade: str,
    config: Path,
    userdir: Path,
    strategy_path: Path,
    data_dir: Path,
    strategy: str,
    starting_balance: float,
    target_balance: float,
    near_ruin_balance: float,
    fee: float,
    detail_timeframe: str | None,
    spec: MarginSpec,
) -> tuple[WindowResult, dict[str, Any]]:
    """Run the signal engine, then apply strict isolated-margin accounting."""

    with tempfile.TemporaryDirectory(prefix="ten-day-margin-window-") as temporary:
        export_directory = Path(temporary) / "exports"
        export_directory.mkdir(parents=True, exist_ok=True)
        command = build_backtest_command(
            freqtrade,
            config,
            userdir,
            strategy_path,
            data_dir,
            strategy,
            window,
            export_directory,
            starting_balance,
            fee,
            detail_timeframe,
        )
        timeout_seconds = int(os.environ.get("TEN_DAY_SUBPROCESS_TIMEOUT_SECONDS", "1800"))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            diagnostic = (
                "stalled subprocess watchdog timeout "
                f"after {timeout_seconds}s during blind margin backtest: {exc}"
            )
            return error_result(window, starting_balance, target_balance, diagnostic), {}
        diagnostic = "\n".join(
            (completed.stdout + "\n" + completed.stderr).splitlines()[-20:]
        )
        if completed.returncode != 0:
            return error_result(window, starting_balance, target_balance, diagnostic), {}

        export_path = newest_export(export_directory)
        if export_path is None:
            return (
                error_result(
                    window,
                    starting_balance,
                    target_balance,
                    f"Freqtrade produced no readable export.\n{diagnostic}",
                ),
                {},
            )

        try:
            payload = load_export(export_path)
            stats = payload.get("strategy", {}).get(strategy)
            if not isinstance(stats, dict):
                raise KeyError(f"Strategy {strategy!r} missing from export")
            trades = list(stats.get("trades", []))
            trades.sort(
                key=lambda item: close_time(item)
                or datetime.max.replace(tzinfo=UTC)
            )
            margin = apply_isolated_margin(
                trades,
                starting_balance=starting_balance,
                target_balance=target_balance,
                near_ruin_balance=near_ruin_balance,
                spec=spec,
            )
            hit_index = margin["target_hit_trade_index"]
            hit_at = None
            if hit_index is not None and hit_index < len(trades):
                when = close_time(trades[hit_index])
                hit_at = when.isoformat() if when else None
            result = WindowResult(
                start=window.start.isoformat(),
                end=window.end.isoformat(),
                timerange=window.timerange,
                starting_balance=starting_balance,
                target_balance=target_balance,
                final_balance=float(margin["final_balance"]),
                return_pct=float(margin["return_pct"]),
                target_hit=bool(margin["target_hit"]),
                target_hit_at=hit_at,
                trades=int(margin["trades_processed"]),
                profit_factor=None,
                max_drawdown_pct=float(margin["max_drawdown_pct"]),
                near_ruin=bool(margin["near_ruin"]),
            )
            return result, margin
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            message = (
                f"Unable to apply isolated-margin model to {export_path.name}: "
                f"{exc}\n{diagnostic}"
            )
            return (
                error_result(
                    window,
                    starting_balance,
                    target_balance,
                    message,
                ),
                {},
            )