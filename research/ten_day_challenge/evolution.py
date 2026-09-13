"""Persistent evidence and hypothesis engine for the autonomous six-raster loop.

Raster 2 classifies the market context using only information available before the
blind window. Raster 3 turns that evidence plus prior completed runs into a new,
non-duplicate research hypothesis. Blind-window outcomes are written back only
after raster 6, so the current test window can never leak into candidate design.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from freqtrade.data.history.datahandlers.featherdatahandler import FeatherDataHandler
from freqtrade.enums import CandleType
from freqtrade.configuration.timerange import TimeRange

IMPLEMENTED_FAMILIES = (
    "breakout",
    "trend_pullback",
    "mean_reversion",
    "volatility_expansion",
)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at_utc"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def initial_memory() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "family_regime_stats": {},
        "hypothesis_history": [],
        "recent_completed_runs": [],
        "external_research_consumed": [],
    }


def _pair_features(frame: pd.DataFrame, history_end: date) -> dict[str, float] | None:
    if frame.empty or len(frame) < 96 * 35:
        return None
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], utc=True)
    end_ts = pd.Timestamp(history_end, tz="UTC")
    work = work[work["date"] < end_ts]
    if work.empty:
        return None
    daily = work.set_index("date")["close"].resample("1D").last().dropna()
    if len(daily) < 35:
        return None
    last = float(daily.iloc[-1])
    p30 = float(daily.iloc[max(0, len(daily) - 31)])
    p90 = float(daily.iloc[max(0, len(daily) - 91)])
    ret30 = last / p30 - 1.0 if p30 else 0.0
    ret90 = last / p90 - 1.0 if p90 else 0.0
    daily_ret = daily.pct_change().dropna().tail(30)
    ann_vol = float(daily_ret.std() * math.sqrt(365)) if len(daily_ret) > 2 else 0.0
    ema_fast = float(daily.ewm(span=10, adjust=False).mean().iloc[-1])
    ema_slow = float(daily.ewm(span=30, adjust=False).mean().iloc[-1])
    trend_gap = (ema_fast / ema_slow - 1.0) if ema_slow else 0.0
    return {
        "return_30d": ret30,
        "return_90d": ret90,
        "annualized_vol_30d": ann_vol,
        "trend_gap": trend_gap,
    }


def classify_regime(
    data_dir: Path,
    pairs: list[str],
    timeframe: str,
    history_start: date,
    history_end: date,
) -> dict[str, Any]:
    handler = FeatherDataHandler(data_dir)
    timerange = TimeRange.parse_timerange(f"{history_start:%Y%m%d}-{history_end:%Y%m%d}")
    features: dict[str, dict[str, float]] = {}
    for pair in pairs:
        frame = handler.ohlcv_load(
            pair=pair,
            timeframe=timeframe,
            timerange=timerange,
            fill_missing=False,
            drop_incomplete=True,
            candle_type=CandleType.SPOT,
        )
        item = _pair_features(frame, history_end)
        if item is not None:
            features[pair] = item
    if not features:
        raise RuntimeError("EvidenceAgent could not derive regime features from pre-window data")

    ret30 = float(pd.Series([x["return_30d"] for x in features.values()]).median())
    ret90 = float(pd.Series([x["return_90d"] for x in features.values()]).median())
    vol = float(pd.Series([x["annualized_vol_30d"] for x in features.values()]).median())
    gap = float(pd.Series([x["trend_gap"] for x in features.values()]).median())

    if ret30 * ret90 < 0 and abs(ret30) > 0.04:
        label = "transition"
    elif ret30 >= 0.08 and gap > 0:
        label = "bull_trend_high_vol" if vol >= 0.65 else "bull_trend"
    elif ret30 <= -0.08 and gap < 0:
        label = "bear_trend_high_vol" if vol >= 0.65 else "bear_trend"
    elif vol >= 0.65:
        label = "sideways_high_vol"
    else:
        label = "sideways_low_vol"

    return {
        "label": label,
        "median_return_30d": ret30,
        "median_return_90d": ret90,
        "median_annualized_vol_30d": vol,
        "median_trend_gap": gap,
        "pair_features": features,
        "evidence_cutoff": history_end.isoformat(),
        "blind_window_seen": False,
    }


def _stats(memory: dict[str, Any], regime: str, family: str) -> dict[str, Any]:
    by_regime = memory.setdefault("family_regime_stats", {}).setdefault(regime, {})
    return by_regime.setdefault(
        family,
        {
            "attempts": 0,
            "hits": 0,
            "sum_final_balance": 0.0,
            "best_final_balance": None,
            "zero_trade_runs": 0,
        },
    )


def _family_score(memory: dict[str, Any], regime: str, family: str, total: int) -> float:
    item = _stats(memory, regime, family)
    attempts = int(item["attempts"])
    if attempts == 0:
        # Exploration matters, but an untested family must not automatically outrank
        # a family with materially positive blind evidence in the same regime.
        return 12.0 * math.sqrt(math.log(total + 2.0))
    avg_balance = float(item["sum_final_balance"]) / attempts
    hit_bonus = 150.0 * (float(item["hits"]) / attempts)
    exploration = 12.0 * math.sqrt(math.log(total + 2.0) / attempts)
    inactivity_penalty = 3.0 * (float(item["zero_trade_runs"]) / attempts)
    return (avg_balance - 100.0) + hit_bonus + exploration - inactivity_penalty


def _regime_priors(regime: str) -> list[str]:
    if regime.startswith("bull_trend"):
        return ["breakout", "trend_pullback", "volatility_expansion", "mean_reversion"]
    if regime.startswith("bear_trend"):
        # Spot-only research cannot short yet; favor rebound/mean-reversion hypotheses.
        return ["mean_reversion", "volatility_expansion", "trend_pullback", "breakout"]
    if regime == "sideways_high_vol":
        return ["mean_reversion", "volatility_expansion", "breakout", "trend_pullback"]
    if regime == "sideways_low_vol":
        return ["mean_reversion", "trend_pullback", "volatility_expansion", "breakout"]
    return ["volatility_expansion", "trend_pullback", "mean_reversion", "breakout"]


def plan_hypothesis(
    memory: dict[str, Any],
    state: dict[str, Any],
    regime: dict[str, Any],
    run_id: int,
    inbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label = str(regime["label"])
    total = sum(int(_stats(memory, label, family)["attempts"]) for family in IMPLEMENTED_FAMILIES)
    priors = _regime_priors(label)
    ranked = sorted(
        IMPLEMENTED_FAMILIES,
        key=lambda family: (
            _family_score(memory, label, family, total),
            -priors.index(family),
        ),
        reverse=True,
    )

    reasons = [
        f"regime={label}",
        "binary objective: >=200 is HIT; every lower final balance is MISS learning evidence",
        "choose by regime-specific evidence plus exploration without discarding materially positive evidence",
    ]
    last = state.get("last_run") or {}
    directive = str(state.get("learning_directive") or "initial_broad_search")
    if int(last.get("trades") or 0) == 0:
        reasons.append("previous run had zero trades; widen signal-producing families")
        ranked = [f for f in ranked if f in {"mean_reversion", "trend_pullback", "volatility_expansion"}] + [
            f for f in ranked if f not in {"mean_reversion", "trend_pullback", "volatility_expansion"}
        ]
    elif float(last.get("final_balance") or 100.0) > 110.0:
        reasons.append("previous MISS had useful positive evidence; preserve one nearby family while exploring")

    external_id = None
    if inbox:
        consumed = set(str(x) for x in memory.get("external_research_consumed", []))
        for idea in inbox.get("ideas", []):
            idea_id = str(idea.get("id") or "")
            family = str(idea.get("implemented_family") or "")
            if idea_id and idea_id not in consumed and family in IMPLEMENTED_FAMILIES:
                ranked = [family] + [x for x in ranked if x != family]
                external_id = idea_id
                reasons.append(f"consume external research idea {idea_id}")
                break

    allowed = ranked[:2]
    canonical = json.dumps(
        {
            "run": run_id,
            "regime": label,
            "allowed_families": allowed,
            "directive": directive,
            "external_id": external_id,
        },
        sort_keys=True,
    )
    hypothesis_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return {
        "hypothesis_id": hypothesis_id,
        "regime": label,
        "allowed_families": allowed,
        "learning_directive": directive,
        "external_research_id": external_id,
        "reasons": reasons,
        "blind_window_seen": False,
    }


def extract_selected_family(parameter_payload: dict[str, Any]) -> str | None:
    stack: list[Any] = [parameter_payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            value = current.get("family_mode")
            if isinstance(value, str):
                return value
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return None


def update_memory_after_completed_run(
    memory: dict[str, Any],
    plan: dict[str, Any],
    record: dict[str, Any],
) -> None:
    regime = str(plan["regime"])
    family = str(record.get("selected_family") or plan["allowed_families"][0])
    item = _stats(memory, regime, family)
    item["attempts"] = int(item["attempts"]) + 1
    item["hits"] = int(item["hits"]) + (1 if record["outcome"] == "HIT" else 0)
    item["sum_final_balance"] = float(item["sum_final_balance"]) + float(record["final_balance"])
    if int(record.get("trades") or 0) == 0:
        item["zero_trade_runs"] = int(item["zero_trade_runs"]) + 1
    best = item.get("best_final_balance")
    if best is None or float(record["final_balance"]) > float(best):
        item["best_final_balance"] = float(record["final_balance"])

    memory.setdefault("hypothesis_history", []).append(
        {
            "hypothesis_id": plan["hypothesis_id"],
            "run": record["run"],
            "regime": regime,
            "selected_family": family,
            "outcome": record["outcome"],
            "final_balance": record["final_balance"],
            "parameter_fingerprint": record["parameter_fingerprint"],
        }
    )
    memory["hypothesis_history"] = memory["hypothesis_history"][-5000:]
    memory.setdefault("recent_completed_runs", []).append(record)
    memory["recent_completed_runs"] = memory["recent_completed_runs"][-200:]
    external_id = plan.get("external_research_id")
    if external_id:
        memory.setdefault("external_research_consumed", []).append(external_id)
        memory["external_research_consumed"] = memory["external_research_consumed"][-1000:]
