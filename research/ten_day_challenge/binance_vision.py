"""Keyless Binance Spot OHLCV downloader for Freqtrade research.

Uses Binance's public data archive instead of exchange credentials. Monthly
kline ZIPs are normalized and stored through Freqtrade's own Feather handler.
The Binance archive contains millisecond timestamps before 2025 and microsecond
timestamps from 2025 onward, so mixed multi-year downloads must normalize each
row independently.
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
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]
MICROSECOND_THRESHOLD = 100_000_000_000_000


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
    """Return the Binance archive unit for one raw timestamp."""
    return "us" if abs(int(value)) >= MICROSECOND_THRESHOLD else "ms"


def normalize_open_times(values: pd.Series) -> pd.Series:
    """Normalize a Series that may mix millisecond and microsecond epochs."""
    numeric = pd.to_numeric(values, errors="raise").astype("int64")
    micro_mask = numeric.abs() >= MICROSECOND_THRESHOLD
    result = pd.Series(pd.NaT, index=numeric.index, dtype="datetime64[ns, UTC]")
    if (~micro_mask).any():
        result.loc[~micro_mask] = pd.to_datetime(
            numeric.loc[~micro_mask], unit="ms", utc=True
        )
    if micro_mask.any():
        result.loc[micro_mask] = pd.to_datetime(
            numeric.loc[micro_mask], unit="us", utc=True
        )
    return result


def download_month(symbol: str, timeframe: str, month: date) -> pd.DataFrame:
    stamp = month.strftime("%Y-%m")
    filename = f"{symbol}-{timeframe}-{stamp}.zip"
    url = (
        "https://data.binance.vision/data/spot/monthly/klines/"
        f"{symbol}/{timeframe}/{filename}"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "ai-trading-agent/1.0"}
    )
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
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume"]
        )
    result = pd.DataFrame(
        {
            "date": normalize_open_times(frame["open_time"]),
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
    return (
        result.drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def validate_coverage(data: pd.DataFrame, start: date, end: date, pair: str) -> None:
    """Fail closed when a supposedly multi-year archive is silently truncated."""
    first = data["date"].min()
    last = data["date"].max()
    latest_required = pd.Timestamp(end, tz="UTC") - pd.Timedelta(days=1)
    earliest_allowed = pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=1)
    if first > earliest_allowed or last < latest_required:
        raise RuntimeError(
            f"Incomplete public Binance history for {pair}: "
            f"first={first}, last={last}, requested={start}..{end}"
        )


def download_pair(
    pair: str,
    timeframe: str,
    start: date,
    end: date,
    data_dir: Path,
) -> int:
    symbol = pair.replace("/", "")
    frames = [
        download_month(symbol, timeframe, month)
        for month in month_starts(start, end)
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise RuntimeError(f"No public Binance data found for {pair} {timeframe}")
    data = normalize(pd.concat(frames, ignore_index=True), start, end)
    if data.empty:
        raise RuntimeError(f"Empty normalized data for {pair} {timeframe}")
    validate_coverage(data, start, end, f"{pair} {timeframe}")
    data_dir.mkdir(parents=True, exist_ok=True)
    FeatherDataHandler(data_dir).ohlcv_store(
        pair, timeframe, data, CandleType.SPOT
    )
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
            count = download_pair(
                pair, timeframe, args.start, args.end, args.data_dir
            )
            print(f"stored {pair} {timeframe}: {count} candles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
