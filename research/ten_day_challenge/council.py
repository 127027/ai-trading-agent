"""Independent reviewer views mapped to the current six-raster architecture.

The primary research objective is the probability of turning 100 USDT into at
least 200 USDT inside an independent 10-day window. Drawdown and near-ruin are
reported as diagnostics but do not veto an otherwise valid research candidate.
"""

from __future__ import annotations

from typing import Any


def quant_review(summary: dict[str, Any]) -> dict[str, Any]:
    hit_200 = float(summary.get("target_hit_rate") or 0.0)
    hit_175 = float(summary.get("hit_rate_175") or 0.0)
    hit_150 = float(summary.get("hit_rate_150") or 0.0)
    hit_250 = float(summary.get("hit_rate_250") or 0.0)
    median_return = float(summary.get("median_return_pct") or 0.0) / 100.0
    score = (
        1000.0 * hit_200
        + 120.0 * hit_250
        + 40.0 * hit_175
        + 15.0 * hit_150
        + 2.0 * median_return
    )
    return {
        "agent": "QuantExperimentAgent",
        "review_role": "outcome_scoring",
        "score": score,
        "veto": False,
        "reason": (
            "Primary objective is repeatable >=200 USDT outcomes in 10 days; "
            "150/175/250 thresholds are secondary learning signals."
        ),
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
        "agent": "BuildValidationAgent",
        "review_role": "completed_experiment_validation",
        "score": 0.0,
        "veto": bool(reasons),
        "reason": "; ".join(reasons) or "Validation evidence is complete enough to review.",
    }


def risk_review(summary: dict[str, Any], council_config: dict[str, Any]) -> dict[str, Any]:
    del council_config
    near_ruin_rate = float(summary.get("near_ruin_rate") or 0.0)
    median_dd_pct = float(summary.get("median_max_drawdown_pct") or 0.0)
    return {
        "agent": "TenDaySupervisor",
        "review_role": "risk_diagnostic",
        "score": 0.0,
        "veto": False,
        "reason": (
            f"Research diagnostic only: near-ruin={near_ruin_rate:.2%}, "
            f"median drawdown={median_dd_pct:.2f}%. Aggressive valid candidates are not vetoed."
        ),
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
        "primary_objective": "maximize_hit_rate_200",
    }


def evaluate_candidate(summary: dict[str, Any], council_config: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper used by finalization and tests."""
    return assemble_council(
        quant_review(summary),
        validation_review(summary, council_config),
        risk_review(summary, council_config),
        council_config,
    )
