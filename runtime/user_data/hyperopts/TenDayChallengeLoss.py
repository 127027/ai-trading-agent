"""Hyperopt objective aimed at repeatable ten-day performance, not headline annual PnL."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from freqtrade.optimize.hyperopt import IHyperOptLoss


class TenDayChallengeLoss(IHyperOptLoss):
    @staticmethod
    def hyperopt_loss_function(
        *,
        results: pd.DataFrame,
        trade_count: int,
        min_date: datetime,
        max_date: datetime,
        config: dict[str, Any],
        processed: dict[str, pd.DataFrame],
        backtest_stats: dict[str, Any],
        starting_balance: float,
        **kwargs: Any,
    ) -> float:
        del config, processed, starting_balance, kwargs
        if trade_count <= 0 or results.empty:
            return 1000.0
        frame = results.loc[:, ["close_date", "profit_ratio"]].copy()
        frame["close_date"] = pd.to_datetime(frame["close_date"], utc=True, errors="coerce")
        frame["profit_ratio"] = pd.to_numeric(frame["profit_ratio"], errors="coerce")
        frame = frame.dropna()
        if frame.empty:
            return 1000.0
        frame["day"] = frame["close_date"].dt.floor("D")
        daily = frame.groupby("day")["profit_ratio"].apply(
            lambda values: float(np.prod(1.0 + values) - 1.0)
        )
        start = pd.Timestamp(min_date)
        end = pd.Timestamp(max_date)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        calendar = pd.date_range(start.floor("D"), end.ceil("D"), inclusive="left", freq="D")
        daily = daily.reindex(calendar, fill_value=0.0)
        if len(daily) < 10:
            return 500.0
        returns = (1.0 + daily).rolling(10, min_periods=10).apply(np.prod, raw=True) - 1.0
        returns = returns.dropna()
        if returns.empty:
            return 500.0
        success_rate = float((returns >= 1.0).mean())
        median_return = float(returns.median())
        p10_return = float(returns.quantile(0.10))
        drawdown = abs(float(backtest_stats.get("max_drawdown_account") or 0.0))
        days = max((max_date - min_date).total_seconds() / 86400.0, 1.0)
        trades_per_day = trade_count / days
        reward = (
            8.0 * success_rate
            + 1.5 * max(-1.0, min(2.0, median_return))
            + 0.8 * max(-1.0, min(2.0, p10_return))
        )
        sparse_penalty = max(0.0, 0.25 - trades_per_day) * 4.0
        overtrade_penalty = max(0.0, trades_per_day - 8.0) * 0.03
        loss = -reward + 3.0 * drawdown + sparse_penalty + overtrade_penalty
        return float(loss) if math.isfinite(loss) else 1000.0
