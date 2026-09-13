import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research" / "ten_day_challenge"
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

SPEC = spec_from_file_location("signal_learning", RESEARCH / "signal_learning.py")
assert SPEC and SPEC.loader
signal_learning = module_from_spec(SPEC)
sys.modules[SPEC.name] = signal_learning
SPEC.loader.exec_module(signal_learning)


def record(equity_change: float, profitable: bool) -> dict:
    return {
        "run": 1,
        "selected_family": "breakout",
        "market_regime": {"label": "bull_trend"},
        "margin_model": {
            "trade_evidence": [
                {
                    "pair": "BTC/USDT",
                    "enter_tag": "adaptive_breakout",
                    "exit_reason": "roi",
                    "profitable": profitable,
                    "liquidated": False,
                    "equity_change": equity_change,
                    "mae_pct": -1.0,
                    "mfe_pct": 4.0,
                    "trade_duration_minutes": 60.0,
                    "leverage": 5,
                }
            ]
        },
    }


def test_completed_trade_evidence_is_persisted_by_context():
    memory = {}
    signal_learning.update_signal_memory(memory, record(12.0, True))
    item = memory["signal_context_stats"]["bull_trend"]["breakout"]["BTC/USDT"]["adaptive_breakout"]
    assert item["trades"] == 1
    assert item["profitable_trades"] == 1
    assert item["sum_equity_change"] == 12.0
    assert memory["recent_signal_evidence"][0]["pair"] == "BTC/USDT"


def test_positive_context_scores_above_equivalent_negative_context():
    positive = {}
    negative = {}
    signal_learning.update_signal_memory(positive, record(12.0, True))
    signal_learning.update_signal_memory(negative, record(-12.0, False))
    good = signal_learning.family_signal_score(positive, "bull_trend", "breakout")
    bad = signal_learning.family_signal_score(negative, "bull_trend", "breakout")
    assert good > bad


def test_unknown_current_window_has_no_signal_bonus():
    assert signal_learning.family_signal_score({}, "bull_trend", "breakout") == 0.0
