"""Hyperopt objective for repeatable 100-to-200 ten-day research.

The 200 target remains dominant, catastrophic ten-day outcomes are explicit negative
evidence, and training uses the same per-entry 1x..10x leverage encoded at signal time.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from freqtrade.optimize.hyperopt import IHyperOptLoss


def _tag_leverage(value: Any) -> float:
    match = re.search(r"(?:^|\|)lev=(10|[1-9])(?:\||$)", str(value or ""))
    return float(match.group(1)) if match else 1.0


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

        columns = ["close_date", "profit_ratio"]
        if "enter_tag" in results.columns:
            columns.append("enter_tag")
        frame = results.loc[:, columns].copy()
        frame["close_date"] = pd.to_datetime(frame["close_date"], utc=True, errors="coerce")
        frame["profit_ratio"] = pd.to_numeric(frame["profit_ratio"], errors="coerce")
        if "enter_tag" not in frame.columns:
            frame["enter_tag"] = ""
        frame = frame.dropna(subset=["close_date", "profit_ratio"])
        if frame.empty:
            return 1000.0

        # Training-side leverage proxy mirrors the leverage encoded at entry time.
        # Raster 5 still performs strict borrow-interest and intratrade liquidation.
        frame["entry_leverage"] = frame["enter_tag"].map(_tag_leverage)
        frame["levered_profit_ratio"] = np.maximum(
            -1.0,
            frame["profit_ratio"] * frame["entry_leverage"],
        )
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

        # Selectivity is allowed. Only near-total inactivity is discouraged.
        days = max((max_date - min_date).total_seconds() / 86400.0, 1.0)
        trades_per_day = trade_count / days
        inactivity_penalty = max(0.0, 0.20 - trades_per_day) * 25.0
        useful_activity_reward = min(1.0, trades_per_day) * 0.75

        loss = -reward + tail_penalty - useful_activity_reward + inactivity_penalty
        return float(loss) if math.isfinite(loss) else 1000.0
