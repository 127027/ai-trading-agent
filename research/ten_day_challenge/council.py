"""Independent reviewer roles for ten-day strategy promotion.

Each reviewer is exposed separately so the raster controller can persist exactly
which stage is active. The Supervisor may never override a veto.
"""

from __future__ import annotations

from typing import Any


def quant_review(summary: dict[str, Any]) -> dict[str, Any]:
    hit_rate = float(summary.get("target_hit_rate") or 0.0)
    median_return = float(summary.get("median_return_pct") or 0.0) / 100.0
    return {
        "agent": "QuantAgent",
        "score": 100.0 * hit_rate + 8.0 * median_return,
        "veto": False,
        "reason": "Rewards repeatable 10-day target hits and median return.",
    }


def validation_review(
    summary: dict[str, Any], council_config: dict[str, Any]
) -> dict[str, Any]:
    gates = council_config["gates"]
    completed = int(summary.get("windows_completed") or 0)
    failed = int(summary.get("windows_failed") or 0)
    valid = bool(summary.get("valid"))
    reasons: list[str] = []
    if gates.get("require_all_windows_valid", True) and (not valid or failed > 0):
        reasons.append("validation contains failed or invalid windows")
    if completed < int(gates.get("minimum_completed_windows", 1)):
        reasons.append("too few completed validation windows")
    return {
        "agent": "ValidationCritic",
        "score": 0.0,
        "veto": bool(reasons),
        "reason": "; ".join(reasons) or "Validation evidence is complete enough to review.",
    }


def risk_review(summary: dict[str, Any], council_config: dict[str, Any]) -> dict[str, Any]:
    gates = council_config["gates"]
    near_ruin_rate = float(summary.get("near_ruin_rate") or 0.0)
    median_dd_pct = float(summary.get("median_max_drawdown_pct") or 0.0)
    max_near_ruin = float(gates.get("max_near_ruin_rate", 0.0))
    max_median_dd = float(gates.get("max_median_drawdown_pct", 100.0))
    reasons: list[str] = []
    if near_ruin_rate > max_near_ruin:
        reasons.append(f"near-ruin rate {near_ruin_rate:.2%} exceeds {max_near_ruin:.2%}")
    if median_dd_pct > max_median_dd:
        reasons.append(
            f"median drawdown {median_dd_pct:.2f}% exceeds {max_median_dd:.2f}%"
        )
    return {
        "agent": "RiskAgent",
        "score": -35.0 * near_ruin_rate - 8.0 * (median_dd_pct / 100.0),
        "veto": bool(reasons),
        "reason": "; ".join(reasons) or "Risk gates passed.",
    }


def assemble_council(
    quant: dict[str, Any],
    critic: dict[str, Any],
    risk: dict[str, Any],
    council_config: dict[str, Any],
) -> dict[str, Any]:
    reviews = [quant, critic, risk]
    vetoes = [review["agent"] for review in reviews if review["veto"]]
    return {
        "supervisor": council_config["supervisor"]["name"],
        "reviews": reviews,
        "veto": bool(vetoes),
        "veto_agents": vetoes,
        "council_score": sum(float(review["score"]) for review in reviews),
        "promotion_eligible": not vetoes,
    }


def evaluate_candidate(summary: dict[str, Any], council_config: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper used by finalization and tests."""
    return assemble_council(
        quant_review(summary),
        validation_review(summary, council_config),
        risk_review(summary, council_config),
        council_config,
    )
