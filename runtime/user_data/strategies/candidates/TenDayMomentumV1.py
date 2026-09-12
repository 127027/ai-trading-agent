"""Research-only momentum candidate plus a separately guarded paper wrapper."""

from __future__ import annotations

from typing import Any, ClassVar

import talib.abstract as ta
from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame


class TenDayMomentumV1(IStrategy):
    """Closed-candle Binance Spot momentum hypothesis for backtest/Hyperopt only."""

    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 320
    position_adjustment_enable = False
    max_entry_position_adjustment = 0

    buy_breakout_lookback = IntParameter(16, 96, default=48, space="buy")
    buy_ema_fast = IntParameter(8, 48, default=20, space="buy")
    buy_ema_slow = IntParameter(80, 240, default=160, space="buy")
    buy_adx = IntParameter(14, 38, default=22, space="buy")
    buy_volume_ratio = DecimalParameter(0.90, 2.20, default=1.15, decimals=2, space="buy")
    buy_atr_min = DecimalParameter(0.001, 0.012, default=0.003, decimals=3, space="buy")
    buy_breakout_buffer = DecimalParameter(0.000, 0.008, default=0.001, decimals=3, space="buy")
    buy_rsi_floor = IntParameter(48, 62, default=52, space="buy")
    buy_rsi_ceiling = IntParameter(68, 84, default=78, space="buy")
    sell_channel = IntParameter(8, 56, default=20, space="sell")
    sell_ema = IntParameter(8, 48, default=20, space="sell")

    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.06, "180": 0.03, "720": 0.0}
    stoploss = -0.08
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
            raise RuntimeError(
                "TenDayMomentumV1 is research-only; create/use the guarded paper class instead."
            )

    @property
    def protections(self) -> list[dict[str, Any]]:
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 1},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,
                "trade_limit": 3,
                "stop_duration_candles": 16,
                "only_per_pair": False,
                "only_per_side": False,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_fast.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_slow.value))
        dataframe["ema_exit"] = ta.EMA(dataframe, timeperiod=int(self.sell_ema.value))
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["volume_mean"] = dataframe["volume"].shift(1).rolling(32, min_periods=32).mean()
        dataframe["breakout_high"] = (
            dataframe["high"]
            .shift(1)
            .rolling(
                int(self.buy_breakout_lookback.value),
                min_periods=int(self.buy_breakout_lookback.value),
            )
            .max()
        )
        dataframe["exit_low"] = (
            dataframe["low"]
            .shift(1)
            .rolling(int(self.sell_channel.value), min_periods=int(self.sell_channel.value))
            .min()
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        buffer = 1.0 + float(self.buy_breakout_buffer.value)
        dataframe.loc[
            (
                (dataframe["close"] > dataframe["breakout_high"] * buffer)
                & (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_slow"] > dataframe["ema_slow"].shift(16))
                & (dataframe["adx"] >= int(self.buy_adx.value))
                & (dataframe["rsi"] >= int(self.buy_rsi_floor.value))
                & (dataframe["rsi"] <= int(self.buy_rsi_ceiling.value))
                & (dataframe["atr_pct"] >= float(self.buy_atr_min.value))
                & (dataframe["atr_pct"] <= 0.04)
                & (
                    dataframe["volume"]
                    >= dataframe["volume_mean"] * float(self.buy_volume_ratio.value)
                )
                & (dataframe["close"] > dataframe["open"])
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "ten_day_momentum_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[
            (
                (
                    (dataframe["close"] < dataframe["exit_low"])
                    | (
                        (dataframe["close"] < dataframe["ema_exit"])
                        & (dataframe["close"].shift(1) >= dataframe["ema_exit"].shift(1))
                    )
                )
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "channel_or_ema_exit")
        return dataframe


class TenDayMomentumPaperV1(TenDayMomentumV1):
    """Same frozen logic with a fail-closed dry-run-only runtime contract."""

    MAX_CAPITAL_USDT = 100.0

    def bot_start(self, **kwargs: Any) -> None:
        del kwargs
        runmode = self._runmode_value(self.config)
        if runmode not in {"live", "dry_run"}:
            return
        exchange = self.config.get("exchange", {})
        safe = (
            runmode == "dry_run"
            and bool(self.config.get("dry_run", False))
            and str(self.config.get("trading_mode", "")).lower() == "spot"
            and str(self.config.get("stake_currency", "")).upper() == "USDT"
            and 0.0 < float(self.config.get("available_capital", 0.0)) <= self.MAX_CAPITAL_USDT
            and int(self.config.get("max_open_trades", 0)) == 1
            and self.position_adjustment_enable is False
            and self.can_short is False
            and isinstance(exchange, dict)
            and exchange.get("name") == "binance"
            and self.config.get("force_entry_enable") is False
        )
        if not safe:
            raise RuntimeError("TenDayMomentumPaperV1 safety contract failed; refusing startup")
