"""Exact rolling 10-day verifier using independent Freqtrade backtests.

Every window gets a fresh 100-USDT simulated wallet. This intentionally avoids
letting gains from an early period compound into later windows.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    @property
    def timerange(self) -> str:
        return f"{self.start:%Y%m%d}-{self.end:%Y%m%d}"


@dataclass
class WindowResult:
    start: str
    end: str
    timerange: str
    starting_balance: float
    target_balance: float
    final_balance: float
    return_pct: float
    target_hit: bool
    target_hit_at: str | None
    trades: int
    profit_factor: float | None
    max_drawdown_pct: float | None
    near_ruin: bool
    error: str | None = None


def iter_windows(
    start: date, end: date, window_days: int = 10, step_days: int = 1
) -> Iterable[Window]:
    if window_days < 1 or step_days < 1:
        raise ValueError("window_days and step_days must be positive")
    current = start
    width = timedelta(days=window_days)
    step = timedelta(days=step_days)
    while current + width <= end:
        yield Window(current, current + width)
        current += step


def load_export(path: Path) -> dict[str, Any]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".json"):
                    continue
                with archive.open(name) as handle:
                    payload = json.loads(handle.read().decode("utf-8"))
                if isinstance(payload, dict) and "strategy" in payload:
                    return payload
        raise ValueError(f"No Freqtrade strategy JSON in {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def newest_export(directory: Path) -> Path | None:
    """Return the newest Freqtrade result produced in an isolated directory."""
    zip_files = [item for item in directory.glob("*.zip") if item.is_file()]
    if zip_files:
        return max(zip_files, key=lambda item: item.stat().st_mtime_ns)
    json_files = [
        item
        for item in directory.glob("*.json")
        if item.is_file() and not item.name.endswith(".meta.json")
    ]
    if json_files:
        return max(json_files, key=lambda item: item.stat().st_mtime_ns)
    return None


def close_time(trade: dict[str, Any]) -> datetime | None:
    timestamp = trade.get("close_timestamp")
    if timestamp is not None:
        value = float(timestamp)
        if value > 10_000_000_000_000:
            value /= 1_000_000.0
        elif value > 10_000_000_000:
            value /= 1_000.0
        return datetime.fromtimestamp(value, tz=UTC)
    text = trade.get("close_date") or trade.get("close_date_utc")
    if not text:
        return None
    parsed = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_result(
    path: Path,
    strategy_name: str,
    starting_balance: float,
    target_balance: float,
    near_ruin_balance: float,
    window: Window,
) -> WindowResult:
    payload = load_export(path)
    stats = payload.get("strategy", {}).get(strategy_name)
    if not isinstance(stats, dict):
        raise KeyError(f"Strategy {strategy_name!r} missing from export")
    trades = list(stats.get("trades", []))
    trades.sort(key=lambda item: close_time(item) or datetime.max.replace(tzinfo=UTC))

    realized = starting_balance
    lowest = realized
    hit_at: datetime | None = None
    for trade in trades:
        realized += float(trade.get("profit_abs") or 0.0)
        lowest = min(lowest, realized)
        if hit_at is None and realized >= target_balance:
            hit_at = close_time(trade)

    final_balance = float(stats.get("final_balance", realized))
    drawdown = stats.get("max_drawdown_account")
    if drawdown is None:
        drawdown = stats.get("max_drawdown")
    pf = stats.get("profit_factor")
    return WindowResult(
        start=window.start.isoformat(),
        end=window.end.isoformat(),
        timerange=window.timerange,
        starting_balance=starting_balance,
        target_balance=target_balance,
        final_balance=final_balance,
        return_pct=(final_balance / starting_balance - 1.0) * 100.0,
        target_hit=hit_at is not None,
        target_hit_at=hit_at.isoformat() if hit_at else None,
        trades=len(trades),
        profit_factor=float(pf) if pf is not None else None,
        max_drawdown_pct=abs(float(drawdown)) * 100.0 if drawdown is not None else None,
        near_ruin=lowest <= near_ruin_balance,
    )


def build_backtest_command(
    freqtrade: str,
    config: Path,
    userdir: Path,
    strategy_path: Path,
    data_dir: Path,
    strategy: str,
    window: Window,
    export_directory: Path,
    starting_balance: float,
    fee: float,
    detail_timeframe: str | None,
) -> list[str]:
    command = [
        freqtrade,
        "backtesting",
        "--config",
        str(config),
        "--userdir",
        str(userdir),
        "--strategy-path",
        str(strategy_path),
        "--data-dir",
        str(data_dir),
        "--strategy",
        strategy,
        "--timerange",
        window.timerange,
        "--dry-run-wallet",
        str(starting_balance),
        "--fee",
        str(fee),
        "--cache",
        "none",
        "--export",
        "trades",
        "--backtest-directory",
        str(export_directory),
        "--enable-protections",
    ]
    if detail_timeframe:
        command.extend(["--timeframe-detail", detail_timeframe])
    return command


def error_result(
    window: Window,
    starting_balance: float,
    target_balance: float,
    diagnostic: str,
) -> WindowResult:
    return WindowResult(
        start=window.start.isoformat(),
        end=window.end.isoformat(),
        timerange=window.timerange,
        starting_balance=starting_balance,
        target_balance=target_balance,
        final_balance=starting_balance,
        return_pct=0.0,
        target_hit=False,
        target_hit_at=None,
        trades=0,
        profit_factor=None,
        max_drawdown_pct=None,
        near_ruin=False,
        error=diagnostic,
    )


def run_window(
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
) -> WindowResult:
    with tempfile.TemporaryDirectory(prefix="ten-day-window-") as temporary:
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
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        diagnostic = "\n".join(
            (completed.stdout + "\n" + completed.stderr).splitlines()[-20:]
        )
        if completed.returncode != 0:
            return error_result(window, starting_balance, target_balance, diagnostic)

        export_path = newest_export(export_directory)
        if export_path is None:
            files = sorted(item.name for item in export_directory.iterdir())
            diagnostic = (
                f"Freqtrade exited successfully but produced no readable backtest export. "
                f"Directory contents: {files}\n{diagnostic}"
            )
            return error_result(window, starting_balance, target_balance, diagnostic)
        try:
            return parse_result(
                export_path,
                strategy,
                starting_balance,
                target_balance,
                near_ruin_balance,
                window,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return error_result(
                window,
                starting_balance,
                target_balance,
                f"Unable to parse {export_path.name}: {exc}\n{diagnostic}",
            )


def summarize(results: list[WindowResult]) -> dict[str, Any]:
    ok = [item for item in results if item.error is None]
    failed = [item for item in results if item.error is not None]
    balances = [item.final_balance for item in ok]
    returns = [item.return_pct for item in ok]
    drawdowns = [
        item.max_drawdown_pct for item in ok if item.max_drawdown_pct is not None
    ]
    hits = sum(item.target_hit for item in ok)
    near_ruin = sum(item.near_ruin for item in ok)
    return {
        "windows_requested": len(results),
        "windows_completed": len(ok),
        "windows_failed": len(failed),
        "target_hit_count": hits,
        "target_hit_rate": hits / len(ok) if ok else 0.0,
        "near_ruin_count": near_ruin,
        "near_ruin_rate": near_ruin / len(ok) if ok else 0.0,
        "mean_final_balance": statistics.fmean(balances) if balances else None,
        "median_final_balance": statistics.median(balances) if balances else None,
        "min_final_balance": min(balances) if balances else None,
        "max_final_balance": max(balances) if balances else None,
        "mean_return_pct": statistics.fmean(returns) if returns else None,
        "median_return_pct": statistics.median(returns) if returns else None,
        "median_max_drawdown_pct": statistics.median(drawdowns) if drawdowns else None,
        "valid": bool(ok) and not failed,
    }


def write_reports(
    results: list[WindowResult], output_dir: Path, metadata: dict[str, Any]
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(result) for result in results]
    summary = summarize(results)
    report = {"metadata": metadata, "summary": summary, "windows": rows}
    (output_dir / "rolling-windows.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    if rows:
        with (output_dir / "rolling-windows.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    text = [
        "# Rolling 10-day verification",
        "",
        f"- Windows: **{summary['windows_completed']} / {summary['windows_requested']}**",
        f"- Target hits: **{summary['target_hit_count']}**",
        f"- Target-hit rate: **{summary['target_hit_rate']:.2%}**",
        f"- Median final balance: **{summary['median_final_balance']}**",
        f"- Worst final balance: **{summary['min_final_balance']}**",
        f"- Best final balance: **{summary['max_final_balance']}**",
        f"- Near-ruin rate: **{summary['near_ruin_rate']:.2%}**",
        "",
        "A hit counts only after closed trades raise realized capital to the target.",
    ]
    (output_dir / "rolling-windows.md").write_text(
        "\n".join(text) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freqtrade", default="freqtrade")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--userdir", type=Path, required=True)
    parser.add_argument("--strategy-path", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--window-days", type=int, default=10)
    parser.add_argument("--step-days", type=int, default=1)
    parser.add_argument("--starting-balance", type=float, default=100.0)
    parser.add_argument("--target-balance", type=float, default=200.0)
    parser.add_argument("--near-ruin-balance", type=float, default=10.0)
    parser.add_argument("--fee", type=float, default=0.0015)
    parser.add_argument("--detail-timeframe", default="5m")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    windows = list(iter_windows(args.start, args.end, args.window_days, args.step_days))
    kwargs = {
        "freqtrade": args.freqtrade,
        "config": args.config,
        "userdir": args.userdir,
        "strategy_path": args.strategy_path,
        "data_dir": args.data_dir,
        "strategy": args.strategy,
        "starting_balance": args.starting_balance,
        "target_balance": args.target_balance,
        "near_ruin_balance": args.near_ruin_balance,
        "fee": args.fee,
        "detail_timeframe": args.detail_timeframe or None,
    }
    results: list[WindowResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(run_window, window, **kwargs) for window in windows]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "HIT" if result.target_hit else ("ERROR" if result.error else "MISS")
            print(f"{result.timerange}: {status} final={result.final_balance:.2f}")
            if result.error:
                print(f"{result.timerange} diagnostic:\n{result.error}")
    results.sort(key=lambda item: item.start)
    summary = write_reports(
        results,
        args.output_dir,
        {
            "strategy": args.strategy,
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "window_days": args.window_days,
            "step_days": args.step_days,
            "starting_balance": args.starting_balance,
            "target_balance": args.target_balance,
            "fee_per_side": args.fee,
            "detail_timeframe": args.detail_timeframe,
        },
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
