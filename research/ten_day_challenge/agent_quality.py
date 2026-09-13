"""V5.1 quality upgrades for Rasters 2, 4 and 6.

These helpers never inspect the current blind window. They enrich pre-window
market evidence, validate hypothesis/evidence integrity before Raster 5, and
measure learning progress only from already completed blind runs.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any


def enrich_regime(regime: dict[str, Any]) -> dict[str, Any]:
    """Add cross-asset breadth, dispersion and strength to Raster 2 evidence."""
    out = dict(regime)
    features = dict(regime.get("pair_features") or {})
    rows = list(features.values())
    if not rows:
        out["context_quality"] = {"pair_count": 0, "evidence_strength": 0.0}
        return out

    r30 = [float(x.get("return_30d") or 0.0) for x in rows]
    r90 = [float(x.get("return_90d") or 0.0) for x in rows]
    gaps = [float(x.get("trend_gap") or 0.0) for x in rows]
    vols = [float(x.get("annualized_vol_30d") or 0.0) for x in rows]
    n = len(rows)

    breadth30 = sum(v > 0 for v in r30) / n
    breadth90 = sum(v > 0 for v in r90) / n
    agreement = max(breadth30, 1.0 - breadth30)
    mean_r30 = sum(r30) / n
    dispersion = math.sqrt(sum((v - mean_r30) ** 2 for v in r30) / n)
    trend_persistence = (
        sum((a > 0) == (b > 0) for a, b in zip(r30, r90, strict=True)) / n
    )
    gap_agreement = max(
        sum(v > 0 for v in gaps) / n,
        sum(v <= 0 for v in gaps) / n,
    )
    vol_support = min(1.0, sum(vols) / n)
    raw_strength = (
        0.35 * agreement
        + 0.30 * trend_persistence
        + 0.20 * gap_agreement
        + 0.15 * vol_support
    )
    strength = max(0.0, min(1.0, raw_strength))

    out["context_quality"] = {
        "pair_count": n,
        "positive_breadth_30d": breadth30,
        "positive_breadth_90d": breadth90,
        "cross_asset_return_dispersion_30d": dispersion,
        "trend_direction_persistence": trend_persistence,
        "trend_gap_agreement": gap_agreement,
        "evidence_strength": strength,
    }
    return out


def make_enriched_classifier(
    original: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    def classify(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return enrich_regime(original(*args, **kwargs))

    return classify


def validate_research_plan(
    plan: dict[str, Any],
    regime: dict[str, Any],
    memory: dict[str, Any],
) -> None:
    """Raster 4 semantic checks beyond a parameter fingerprint."""
    if bool(plan.get("blind_window_seen")) or bool(regime.get("blind_window_seen")):
        raise RuntimeError(
            "BuildValidationAgent rejected pre-Raster-5 blind-window access"
        )
    if plan.get("regime") != regime.get("label"):
        raise RuntimeError("BuildValidationAgent rejected hypothesis/regime mismatch")

    families = list(plan.get("allowed_families") or [])
    if not families or len(set(families)) != len(families):
        raise RuntimeError("BuildValidationAgent rejected empty/duplicate family plan")

    for family, summary in (plan.get("signal_evidence") or {}).items():
        if family not in families:
            raise RuntimeError(
                "BuildValidationAgent rejected out-of-plan signal evidence"
            )
        trades = int((summary or {}).get("trades") or 0)
        persisted = 0
        family_data = (
            memory.get("signal_context_stats", {})
            .get(str(regime.get("label")), {})
            .get(family, {})
        )
        for pair_data in family_data.values():
            for item in pair_data.values():
                persisted += int(item.get("trades") or 0)
        if trades > persisted:
            raise RuntimeError(
                "BuildValidationAgent rejected signal evidence not backed by "
                "completed memory"
            )


def meta_learning_report(
    memory: dict[str, Any],
    window: int = 20,
) -> dict[str, Any]:
    """Raster 6 checks whether research is improving or cycling."""
    runs = list(memory.get("recent_completed_runs") or [])[-window:]
    if not runs:
        return {"runs": 0, "stagnating": False, "directive": None}

    finals = [float(r.get("final_balance") or 0.0) for r in runs]
    hits = sum(str(r.get("outcome")) == "HIT" for r in runs)
    half = max(1, len(finals) // 2)
    early = finals[:half]
    late = finals[-half:]
    early_avg = sum(early) / len(early)
    late_avg = sum(late) / len(late)
    unique_fingerprints = len(
        {str(r.get("parameter_fingerprint") or "") for r in runs}
    )
    repeated_zero = sum(int(r.get("trades") or 0) == 0 for r in runs)
    best = max(finals)
    stagnating = len(runs) >= 10 and hits == 0 and late_avg <= early_avg + 2.0
    directive = (
        "break_stagnation_force_materially_new_signal_hypothesis"
        if stagnating
        else None
    )
    return {
        "runs": len(runs),
        "hit_rate": hits / len(runs),
        "best_final_balance": best,
        "early_average_balance": early_avg,
        "late_average_balance": late_avg,
        "balance_improvement": late_avg - early_avg,
        "unique_fingerprints": unique_fingerprints,
        "zero_trade_runs": repeated_zero,
        "stagnating": stagnating,
        "directive": directive,
    }
