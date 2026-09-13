import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "research" / "ten_day_challenge"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from agent_quality import (  # noqa: E402
    enrich_regime,
    meta_learning_report,
    validate_research_plan,
)


def test_raster2_enriches_cross_asset_context_without_blind_data():
    regime = {
        "label": "bull_trend",
        "blind_window_seen": False,
        "pair_features": {
            "BTC/USDT": {
                "return_30d": 0.10,
                "return_90d": 0.20,
                "trend_gap": 0.03,
                "annualized_vol_30d": 0.6,
            },
            "ETH/USDT": {
                "return_30d": 0.08,
                "return_90d": 0.15,
                "trend_gap": 0.02,
                "annualized_vol_30d": 0.7,
            },
        },
    }
    out = enrich_regime(regime)
    assert out["blind_window_seen"] is False
    assert out["context_quality"]["positive_breadth_30d"] == 1.0
    assert 0.0 <= out["context_quality"]["evidence_strength"] <= 1.0


def test_raster4_rejects_signal_evidence_not_backed_by_completed_memory():
    plan = {
        "regime": "bull_trend",
        "blind_window_seen": False,
        "allowed_families": ["breakout"],
        "signal_evidence": {"breakout": {"trades": 4}},
    }
    try:
        validate_research_plan(
            plan,
            {"label": "bull_trend", "blind_window_seen": False},
            {},
        )
    except RuntimeError as exc:
        assert "not backed" in str(exc)
    else:
        raise AssertionError("unbacked signal evidence must be rejected")


def test_raster6_detects_stagnation_and_requests_material_change():
    memory = {"recent_completed_runs": []}
    for i in range(20):
        memory["recent_completed_runs"].append(
            {
                "run": i + 1,
                "outcome": "MISS",
                "final_balance": 100.0 - i * 0.2,
                "trades": 5,
                "parameter_fingerprint": f"fp-{i}",
            }
        )
    report = meta_learning_report(memory)
    assert report["stagnating"] is True
    assert report["directive"] == (
        "break_stagnation_force_materially_new_signal_hypothesis"
    )
    assert report["unique_fingerprints"] == 20
