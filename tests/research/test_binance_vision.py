import sys
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "research" / "ten_day_challenge" / "binance_vision.py"
SPEC = spec_from_file_location("binance_vision", MODULE_PATH)
assert SPEC and SPEC.loader
binance_vision = module_from_spec(SPEC)
sys.modules[SPEC.name] = binance_vision
SPEC.loader.exec_module(binance_vision)


def test_mixed_binance_timestamp_units_are_normalized_per_row():
    frame = pd.DataFrame(
        {
            "open_time": [
                1735689540000,
                1735689600000000,
            ],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1.0, 1.0],
        }
    )
    result = binance_vision.normalize(frame, date(2024, 12, 31), date(2025, 1, 2))
    assert list(result["date"].dt.strftime("%Y-%m-%d %H:%M:%S")) == [
        "2024-12-31 23:59:00",
        "2025-01-01 00:00:00",
    ]


def test_coverage_rejects_silently_truncated_archive():
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2022-09-01T00:00:00Z", "2024-12-31T23:45:00Z"], utc=True
            )
        }
    )
    try:
        binance_vision.validate_coverage(
            data,
            date(2022, 9, 1),
            date(2026, 9, 1),
            "BTC/USDT 15m",
        )
    except RuntimeError as exc:
        assert "Incomplete public Binance history" in str(exc)
    else:
        raise AssertionError("truncated archive must fail closed")
