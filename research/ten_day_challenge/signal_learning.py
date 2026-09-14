"""Contextual signal-memory helpers for completed blind experiments.

Only completed blind-window trade evidence is consumed here. The current blind
window is never inspected while a hypothesis is being designed.
"""

from __future__ import annotations

from typing import Any


def _bucket(
    memory: dict[str, Any],
    regime: str,
    family: str,
    pair: str,
    tag: str,
) -> dict[str, Any]:
    regimes = memory.setdefault("signal_context_stats", {})
    families = regimes.setdefault(regime, {})
    pairs = families.setdefault(family, {})
    tags = pairs.setdefault(pair, {})
    return tags.setdefault(
        tag,
        {
            "trades": 0,
            "profitable_trades": 0,
            "liquidations": 0,
            "sum_equity_change": 0.0,
            "sum_mae_pct": 0.0,
            "sum_mfe_pct": 0.0,
            "mfe_observations": 0,
            "sum_duration_minutes": 0.0,
            "exit_reasons": {},
        },
    )


def update_signal_memory(memory: dict[str, Any], record: dict[str, Any]) -> None:
    """Persist trade-level lessons from one completed blind run."""

    regime = str((record.get("market_regime") or {}).get("label") or "unknown")
    family = str(record.get("selected_family") or "unknown")
    evidence = (record.get("margin_model") or {}).get("trade_evidence") or []
    for trade in evidence:
        pair = str(trade.get("pair") or "unknown")
        tag = str(trade.get("enter_tag") or "unknown")
        item = _bucket(memory, regime, family, pair, tag)
        item["trades"] += 1
        item["profitable_trades"] += 1 if bool(trade.get("profitable")) else 0
        item["liquidations"] += 1 if bool(trade.get("liquidated")) else 0
        item["sum_equity_change"] += float(trade.get("equity_change") or 0.0)
        item["sum_mae_pct"] += float(trade.get("mae_pct") or 0.0)
        mfe = trade.get("mfe_pct")
        if mfe is not None:
            item["sum_mfe_pct"] += float(mfe)
            item["mfe_observations"] += 1
        item["sum_duration_minutes"] += float(trade.get("trade_duration_minutes") or 0.0)
        exit_reason = str(trade.get("exit_reason") or "unknown")
        reasons = item.setdefault("exit_reasons", {})
        reasons[exit_reason] = int(reasons.get(exit_reason) or 0) + 1

    recent = memory.setdefault("recent_signal_evidence", [])
    for trade in evidence:
        recent.append(
            {
                "run": int(record.get("run") or 0),
                "regime": regime,
                "family": family,
                "pair": str(trade.get("pair") or "unknown"),
                "enter_tag": str(trade.get("enter_tag") or "unknown"),
                "exit_reason": str(trade.get("exit_reason") or "unknown"),
                "profitable": bool(trade.get("profitable")),
                "liquidated": bool(trade.get("liquidated")),
                "equity_change": float(trade.get("equity_change") or 0.0),
                "mae_pct": float(trade.get("mae_pct") or 0.0),
                "mfe_pct": trade.get("mfe_pct"),
                "leverage": int(trade.get("leverage") or 0),
            }
        )
    memory["recent_signal_evidence"] = recent[-5000:]


def family_signal_score(memory: dict[str, Any], regime: str, family: str) -> float:
    """Return a bounded contextual bonus/penalty from completed trade evidence.

    A high win rate must not hide negative monetary expectancy. Once a family has
    enough observations, persistent negative average equity change receives an
    additional sample-weighted penalty. Sparse families stay explorable so a new
    high-upside hypothesis is not suppressed before there is evidence against it.
    """

    family_data = (
        memory.get("signal_context_stats", {}).get(regime, {}).get(family, {})
    )
    trades = 0
    profitable = 0
    liquidations = 0
    equity_change = 0.0
    mae = 0.0
    mfe = 0.0
    mfe_n = 0
    for pair_data in family_data.values():
        for item in pair_data.values():
            trades += int(item.get("trades") or 0)
            profitable += int(item.get("profitable_trades") or 0)
            liquidations += int(item.get("liquidations") or 0)
            equity_change += float(item.get("sum_equity_change") or 0.0)
            mae += float(item.get("sum_mae_pct") or 0.0)
            mfe += float(item.get("sum_mfe_pct") or 0.0)
            mfe_n += int(item.get("mfe_observations") or 0)
    if trades == 0:
        return 0.0
    win_rate = profitable / trades
    liquidation_rate = liquidations / trades
    avg_change = equity_change / trades
    avg_mae = mae / trades
    avg_mfe = mfe / mfe_n if mfe_n else 0.0

    # Keep early exploration intact. From 5 to 16 observations, progressively
    # trust negative expectancy more. Positive expectancy is never capped here.
    evidence_reliability = max(0.0, min(1.0, (trades - 4) / 12.0))
    negative_expectancy_penalty = 0.0
    if avg_change < 0.0:
        negative_expectancy_penalty = 2.0 * abs(avg_change) * evidence_reliability

    raw = (
        10.0 * (win_rate - 0.5)
        + 0.20 * avg_change
        + 0.08 * avg_mfe
        + 0.05 * avg_mae
        - 15.0 * liquidation_rate
        - negative_expectancy_penalty
    )
    return max(-20.0, min(20.0, raw))


def signal_summary(memory: dict[str, Any], regime: str, family: str) -> dict[str, Any]:
    """Compact explanation for Raster 3 hypothesis reasoning."""

    family_data = (
        memory.get("signal_context_stats", {}).get(regime, {}).get(family, {})
    )
    trades = profitable = liquidations = 0
    equity_change = 0.0
    for pair_data in family_data.values():
        for item in pair_data.values():
            trades += int(item.get("trades") or 0)
            profitable += int(item.get("profitable_trades") or 0)
            liquidations += int(item.get("liquidations") or 0)
            equity_change += float(item.get("sum_equity_change") or 0.0)
    return {
        "trades": trades,
        "win_rate": profitable / trades if trades else None,
        "liquidation_rate": liquidations / trades if trades else None,
        "average_equity_change": equity_change / trades if trades else None,
        "score": family_signal_score(memory, regime, family),
    }
