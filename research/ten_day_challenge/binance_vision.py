"""Keyless Binance Spot OHLCV downloader for Freqtrade research.

Uses Binance's public data archive instead of exchange credentials.  Monthly
kline ZIPs are normalized and stored through Freqtrade's own Feather handler.
"""

from __future__ import annotations

import argparse
import io
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
from freqtrade.data.history.datahandlers.featherdatahandler import FeatherDataHandler
from freqtrade.enums import CandleType

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]


def month_starts(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current < end:
        yield current
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )


def timestamp_unit(value: int) -> str:
    """Binance Spot archive switched to microseconds from 2025-01-01."""
    return "us" if abs(int(value)) >= 100_000_000_000_000 else "ms"


def download_month(symbol: str, timeframe: str, month: date) -> pd.DataFrame:
    stamp = month.strftime("%Y-%m")
    filename = f"{symbol}-{timeframe}-{stamp}.zip"
    url = (
        "https://data.binance.vision/data/spot/monthly/klines/"
        f"{symbol}/{timeframe}/{filename}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "ai-trading-agent/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return pd.DataFrame(columns=COLUMNS)
        raise

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"Expected one CSV in {filename}; found {names!r}")
        with archive.open(names[0]) as handle:
            return pd.read_csv(handle, header=None, names=COLUMNS)


def normalize(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    unit = timestamp_unit(int(frame.iloc[0]["open_time"]))
    result = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["open_time"], unit=unit, utc=True),
            "open": pd.to_numeric(frame["open"], errors="raise"),
            "high": pd.to_numeric(frame["high"], errors="raise"),
            "low": pd.to_numeric(frame["low"], errors="raise"),
            "close": pd.to_numeric(frame["close"], errors="raise"),
            "volume": pd.to_numeric(frame["volume"], errors="raise"),
        }
    )
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    result = result[(result["date"] >= start_ts) & (result["date"] < end_ts)]
    return result.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def download_pair(pair: str, timeframe: str, start: date, end: date, data_dir: Path) -> int:
    symbol = pair.replace("/", "")
    frames = [download_month(symbol, timeframe, month) for month in month_starts(start, end)]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise RuntimeError(f"No public Binance data found for {pair} {timeframe}")
    data = normalize(pd.concat(frames, ignore_index=True), start, end)
    if data.empty:
        raise RuntimeError(f"Empty normalized data for {pair} {timeframe}")
    data_dir.mkdir(parents=True, exist_ok=True)
    FeatherDataHandler(data_dir).ohlcv_store(pair, timeframe, data, CandleType.SPOT)
    return len(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", nargs="+", required=True)
    parser.add_argument("--timeframes", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    for pair in args.pairs:
        for timeframe in args.timeframes:
            count = download_pair(pair, timeframe, args.start, args.end, args.data_dir)
            print(f"stored {pair} {timeframe}: {count} candles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
