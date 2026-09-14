"""Hyperopt objective for repeatable 100-to-200 ten-day research.

The 200 target remains dominant, but catastrophic ten-day outcomes are explicit
negative evidence. This keeps the search aggressive without rewarding a policy
that reaches 200 rarely while destroying most starting wallets.
"""

from __future__ import annotations

import math
import os
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
        del config, processed, backtest_stats, starting_balance, kwargs
        if trade_count <= 0 or results.empty:
            return 1000.0

        leverage = max(1.0, float(os.getenv("TEN_DAY_RESEARCH_LEVERAGE", "1")))
        frame = results.loc[:, ["close_date", "profit_ratio"]].copy()
        frame["close_date"] = pd.to_datetime(frame["close_date"], utc=True, errors="coerce")
        frame["profit_ratio"] = pd.to_numeric(frame["profit_ratio"], errors="coerce")
        frame = frame.dropna()
        if frame.empty:
            return 1000.0

        # Training-side leverage proxy. Raster 5 still performs strict margin,
        # interest and intratrade-liquidation accounting on the blind window.
        frame["levered_profit_ratio"] = np.maximum(-1.0, frame["profit_ratio"] * leverage)
        frame["day"] = frame["close_date"].dt.floor("D")
        daily = frame.groupby("day")["levered_profit_ratio"].apply(
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

        hit_150 = float((returns >= 0.50).mean())
        hit_175 = float((returns >= 0.75).mean())
        hit_200 = float((returns >= 1.00).mean())
        hit_250 = float((returns >= 1.50).mean())
        collapse_50 = float((returns <= -0.50).mean())
        collapse_75 = float((returns <= -0.75).mean())
        total_loss = float((returns <= -0.95).mean())
        median_return = float(returns.median())
        mean_return = float(returns.mean())
        best_return = float(returns.max())

        # Hitting 200 is still by far the strongest term. Severe losses matter,
        # however, so a 5% hit-rate / 95% account-destruction policy cannot win.
        reward = (
            340.0 * hit_200
            + 40.0 * hit_250
            + 12.0 * hit_175
            + 5.0 * hit_150
            + 1.0 * max(-1.0, min(4.0, best_return))
            + 0.7 * max(-1.0, min(3.0, median_return))
            + 0.3 * max(-1.0, min(3.0, mean_return))
        )
        tail_penalty = 35.0 * collapse_50 + 80.0 * collapse_75 + 140.0 * total_loss

        # Selectivity is allowed. Only near-total inactivity is discouraged; the
        # optimizer is no longer forced toward 1-2 trades/day irrespective of setup quality.
        days = max((max_date - min_date).total_seconds() / 86400.0, 1.0)
        trades_per_day = trade_count / days
        inactivity_penalty = max(0.0, 0.20 - trades_per_day) * 25.0
        useful_activity_reward = min(1.0, trades_per_day) * 0.75

        loss = -reward + tail_penalty - useful_activity_reward + inactivity_penalty
        return float(loss) if math.isfinite(loss) else 1000.0
