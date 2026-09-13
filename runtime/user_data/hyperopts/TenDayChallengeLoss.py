"""Aggressive Hyperopt objective for the 100-to-200 ten-day research challenge."""

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

        # Training-side leverage proxy: blind Raster 5 performs the strict margin,
        # borrow-interest and intratrade liquidation accounting. Hyperopt must still
        # search for signals with enough return velocity for the intended leverage.
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
        median_return = float(returns.median())
        mean_return = float(returns.mean())

        # Binary mission dominates: >=200 is the only success state. Intermediate
        # thresholds only provide gradient before the first true hit.
        reward = (
            240.0 * hit_200
            + 24.0 * hit_250
            + 6.0 * hit_175
            + 2.0 * hit_150
            + 0.4 * max(-1.0, min(3.0, median_return))
            + 0.1 * max(-1.0, min(3.0, mean_return))
        )

        # A strategy that rarely trades is strongly disfavored for a 10-day mission.
        # Drawdown/near-ruin are deliberately not optimization vetoes.
        days = max((max_date - min_date).total_seconds() / 86400.0, 1.0)
        trades_per_day = trade_count / days
        inactivity_penalty = max(0.0, 0.30 - trades_per_day) * 80.0

        loss = -reward + inactivity_penalty
        return float(loss) if math.isfinite(loss) else 1000.0
