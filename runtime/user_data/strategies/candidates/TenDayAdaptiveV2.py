"""Research-only multi-family strategy used by the agentic six-raster loop."""

from __future__ import annotations

import os
from typing import Any, ClassVar

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame


def _allowed_families() -> list[str]:
    supported = ["breakout", "trend_pullback", "mean_reversion", "volatility_expansion"]
    raw = os.environ.get("TEN_DAY_ALLOWED_FAMILIES", "").strip()
    if not raw:
        return supported
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    selected = [item for item in requested if item in supported]
    return selected or supported


class TenDayAdaptiveV2(IStrategy):
    """Adaptive research strategy whose family is chosen by raster-3 research."""

    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 420
    position_adjustment_enable = False
    max_entry_position_adjustment = 0

    family_mode = CategoricalParameter(_allowed_families(), default=_allowed_families()[0], space="buy")
    ema_fast = IntParameter(6, 48, default=18, space="buy")
    ema_slow = IntParameter(48, 220, default=120, space="buy")
    adx_min = IntParameter(5, 32, default=14, space="buy")
    volume_ratio = DecimalParameter(0.25, 1.50, default=0.70, decimals=2, space="buy")
    atr_floor = DecimalParameter(0.000, 0.012, default=0.001, decimals=3, space="buy")
    breakout_lookback = IntParameter(4, 72, default=24, space="buy")
    breakout_buffer = DecimalParameter(0.0, 0.006, default=0.0, decimals=3, space="buy")
    pullback_depth = DecimalParameter(0.002, 0.060, default=0.025, decimals=3, space="buy")
    rsi_entry = IntParameter(20, 70, default=55, space="buy")
    rsi_exit = IntParameter(55, 90, default=74, space="sell")
    exit_ema = IntParameter(6, 48, default=18, space="sell")

    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.08, "180": 0.04, "720": 0.0}
    stoploss = -0.12
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    @staticmethod
    def _runmode_value(config: dict[str, Any]) -> str:
        runmode = config.get("runmode", "")
        return str(getattr(runmode, "value", runmode)).lower()

    def bot_start(self, **kwargs: Any) -> None:
        del kwargs
        if self._runmode_value(self.config) in {"live", "dry_run"}:
            raise RuntimeError("TenDayAdaptiveV2 is research-only")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.ema_fast.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.ema_slow.value))
        dataframe["ema_exit"] = ta.EMA(dataframe, timeperiod=int(self.exit_ema.value))
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["atr_mean"] = dataframe["atr_pct"].shift(1).rolling(48, min_periods=48).mean()
        dataframe["volume_mean"] = dataframe["volume"].shift(1).rolling(32, min_periods=32).mean()
        dataframe["rolling_high"] = (
            dataframe["high"].shift(1).rolling(int(self.breakout_lookback.value), min_periods=4).max()
        )
        dataframe["rolling_low"] = dataframe["low"].shift(1).rolling(24, min_periods=12).min()
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bb["upperband"]
        dataframe["bb_middle"] = bb["middleband"]
        dataframe["bb_lower"] = bb["lowerband"]

        # Entry-time confidence uses only current/past indicators. High leverage
        # now requires genuinely exceptional agreement instead of a near-linear
        # mapping that promoted mediocre setups into 6x-8x exposure too easily.
        trend_gap = ((dataframe["ema_fast"] / dataframe["ema_slow"]) - 1.0).clip(-0.10, 0.10)
        trend_strength = (trend_gap.clip(lower=0.0) / 0.05).clip(0.0, 1.0)
        adx_strength = ((dataframe["adx"] - 10.0) / 30.0).clip(0.0, 1.0)
        volume_strength = (
            (dataframe["volume"] / dataframe["volume_mean"].replace(0.0, np.nan) - 0.6) / 1.4
        ).clip(0.0, 1.0)
        volatility_strength = (
            (dataframe["atr_pct"] / dataframe["atr_mean"].replace(0.0, np.nan) - 0.7) / 1.3
        ).clip(0.0, 1.0)
        rsi_quality = (1.0 - ((dataframe["rsi"] - 55.0).abs() / 35.0)).clip(0.0, 1.0)
        dataframe["entry_confidence"] = (
            0.30 * trend_strength.fillna(0.0)
            + 0.25 * adx_strength.fillna(0.0)
            + 0.20 * volume_strength.fillna(0.0)
            + 0.15 * volatility_strength.fillna(0.0)
            + 0.10 * rsi_quality.fillna(0.0)
        ).clip(0.0, 1.0)

        # Convex mapping: 0.50 confidence -> ~3x, 0.70 -> ~5x,
        # 0.85 -> ~7x, and only ~0.95+ approaches 9x-10x.
        leverage_score = dataframe["entry_confidence"].pow(2.2)
        dataframe["entry_leverage"] = (1.0 + 9.0 * leverage_score).round().clip(1, 10).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        family = str(self.family_mode.value)
        common = (
            (dataframe["volume"] > 0)
            & (dataframe["atr_pct"] >= float(self.atr_floor.value))
            & (dataframe["volume"] >= dataframe["volume_mean"] * float(self.volume_ratio.value))
        )

        if family == "breakout":
            signal = (
                common
                & (dataframe["close"] > dataframe["rolling_high"] * (1.0 + float(self.breakout_buffer.value)))
                & (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["adx"] >= int(self.adx_min.value))
            )
            base_tag = "adaptive_breakout"
        elif family == "trend_pullback":
            distance = (dataframe["close"] / dataframe["ema_fast"] - 1.0).abs()
            signal = (
                common
                & (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_slow"] > dataframe["ema_slow"].shift(8))
                & (distance <= float(self.pullback_depth.value))
                & (dataframe["rsi"] >= 32)
                & (dataframe["rsi"] <= int(self.rsi_entry.value) + 12)
            )
            base_tag = "adaptive_trend_pullback"
        elif family == "mean_reversion":
            signal = (
                common
                & (dataframe["close"] <= dataframe["bb_middle"])
                & (dataframe["rsi"] <= int(self.rsi_entry.value))
                & (dataframe["close"] > dataframe["rolling_low"] * 0.94)
            )
            base_tag = "adaptive_mean_reversion"
        else:
            signal = (
                common
                & (dataframe["atr_pct"] > dataframe["atr_mean"] * 1.02)
                & (dataframe["close"] > dataframe["rolling_high"] * 0.995)
                & (dataframe["close"] > dataframe["ema_fast"] * 0.997)
                & (dataframe["rsi"] >= 45)
            )
            base_tag = "adaptive_volatility_expansion"

        for leverage in range(1, 11):
            selected = signal & (dataframe["entry_leverage"] == leverage)
            dataframe.loc[selected, ["enter_long", "enter_tag"]] = (
                1,
                f"{base_tag}|lev={leverage}",
            )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        signal = (
            (
                (dataframe["close"] < dataframe["ema_exit"])
                | (dataframe["rsi"] >= int(self.rsi_exit.value))
                | (dataframe["close"] < dataframe["rolling_low"])
            )
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[signal, ["exit_long", "exit_tag"]] = (1, "adaptive_exit")
        return dataframe
