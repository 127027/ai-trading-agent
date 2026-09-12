import sys
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "research" / "ten_day_challenge" / "rolling_windows.py"
SPEC = spec_from_file_location("rolling_windows", MODULE_PATH)
assert SPEC and SPEC.loader
rolling = module_from_spec(SPEC)
sys.modules[SPEC.name] = rolling
SPEC.loader.exec_module(rolling)


def test_full_year_has_356_overlapping_ten_day_windows():
    windows = list(rolling.iter_windows(date(2025, 9, 1), date(2026, 9, 1), 10, 1))
    assert len(windows) == 356
    assert windows[0].timerange == "20250901-20250911"
    assert windows[-1].timerange == "20260822-20260901"


def test_validation_step_is_search_acceleration_only():
    windows = list(rolling.iter_windows(date(2026, 5, 1), date(2026, 7, 1), 10, 2))
    assert windows[0].start == date(2026, 5, 1)
    assert all((b.start - a.start).days == 2 for a, b in pairwise(windows))


def test_backtest_command_resets_wallet_and_disables_cache(tmp_path):
    window = rolling.Window(date(2025, 9, 1), date(2025, 9, 11))
    command = rolling.build_backtest_command(
        "freqtrade", tmp_path / "config.json", tmp_path / "user_data",
        tmp_path / "strategies", tmp_path / "data", "TenDayMomentumV1",
        window, tmp_path / "result.zip", 100.0, 0.0015, "5m",
    )
    assert command[0:2] == ["freqtrade", "backtesting"]
    assert command[command.index("--dry-run-wallet") + 1] == "100.0"
    assert command[command.index("--timerange") + 1] == "20250901-20250911"
    assert command[command.index("--fee") + 1] == "0.0015"
    assert command[command.index("--cache") + 1] == "none"
    assert "--enable-protections" in command
    assert command[command.index("--timeframe-detail") + 1] == "5m"
