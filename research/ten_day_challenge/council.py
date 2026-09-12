"""Independent reviewer roles for ten-day strategy promotion.

These roles are deterministic and intentionally separated.  The Supervisor is
not allowed to override a veto.  This keeps strategy search, validation and
risk review from collapsing into one optimization objective.
"""

from __future__ import annotations

from typing import Any


def evaluate_candidate(summary: dict[str, Any], council_config: dict[str, Any]) -> dict[str, Any]:
    gates = council_config["gates"]
    completed = int(summary.get("windows_completed") or 0)
    failed = int(summary.get("windows_failed") or 0)
    valid = bool(summary.get("valid"))
    hit_rate = float(summary.get("target_hit_rate") or 0.0)
    median_return = float(summary.get("median_return_pct") or 0.0) / 100.0
    near_ruin_rate = float(summary.get("near_ruin_rate") or 0.0)
    median_dd_pct = float(summary.get("median_max_drawdown_pct") or 0.0)

    quant_score = 100.0 * hit_rate + 8.0 * median_return
    quant = {
        "agent": "QuantAgent",
        "score": quant_score,
        "veto": False,
        "reason": "Rewards repeatable 10-day target hits and median return.",
    }

    validation_reasons: list[str] = []
    if gates.get("require_all_windows_valid", True) and (not valid or failed > 0):
        validation_reasons.append("validation contains failed or invalid windows")
    if completed < int(gates.get("minimum_completed_windows", 1)):
        validation_reasons.append("too few completed validation windows")
    critic = {
        "agent": "ValidationCritic",
        "score": 0.0,
        "veto": bool(validation_reasons),
        "reason": "; ".join(validation_reasons) or "Validation evidence is complete enough to review.",
    }

    risk_reasons: list[str] = []
    max_near_ruin = float(gates.get("max_near_ruin_rate", 0.0))
    max_median_dd = float(gates.get("max_median_drawdown_pct", 100.0))
    if near_ruin_rate > max_near_ruin:
        risk_reasons.append(
            f"near-ruin rate {near_ruin_rate:.2%} exceeds {max_near_ruin:.2%}"
        )
    if median_dd_pct > max_median_dd:
        risk_reasons.append(
            f"median drawdown {median_dd_pct:.2f}% exceeds {max_median_dd:.2f}%"
        )
    risk_score = -35.0 * near_ruin_rate - 8.0 * (median_dd_pct / 100.0)
    risk = {
        "agent": "RiskAgent",
        "score": risk_score,
        "veto": bool(risk_reasons),
        "reason": "; ".join(risk_reasons) or "Risk gates passed.",
    }

    reviews = [quant, critic, risk]
    vetoes = [review["agent"] for review in reviews if review["veto"]]
    council_score = sum(float(review["score"]) for review in reviews)
    return {
        "supervisor": council_config["supervisor"]["name"],
        "reviews": reviews,
        "veto": bool(vetoes),
        "veto_agents": vetoes,
        "council_score": council_score,
        "promotion_eligible": not vetoes,
    }
