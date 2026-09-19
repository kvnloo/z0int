"""Scoring and aggregation for decision-capability-v1."""

from __future__ import annotations

import math
import statistics
from typing import Any

from .fixtures import BenchExample


def _pred_str(answer: dict[str, Any], example: BenchExample) -> str:
    val = answer.get("value")
    if example.question.type == "boolean":
        return "true" if val is True or val == "true" else "false"
    return str(val)


def score_example(
    example: BenchExample,
    *,
    probabilities: dict[str, float] | None,
    pred: str,
) -> dict[str, Any]:
    gold = example.gold
    abstain_id = example.abstain_option_id
    correct = pred == gold
    abstention_correct: bool | None = None
    if gold == abstain_id or (example.allow_abstain and gold == "abstain"):
        abstention_correct = pred == gold
    elif example.allow_abstain and abstain_id and pred == abstain_id:
        abstention_correct = pred != gold  # chose abstain when shouldn't (usually wrong)

    brier: float | None = None
    if probabilities:
        keys = list(probabilities.keys())
        if gold in probabilities:
            brier = sum((probabilities.get(k, 0.0) - (1.0 if k == gold else 0.0)) ** 2 for k in keys)
        elif example.question.type == "boolean" and gold in ("true", "false"):
            brier = sum((probabilities.get(k, 0.0) - (1.0 if k == gold else 0.0)) ** 2 for k in keys)

    dangerous = example.dangerous_prediction(pred)
    return {
        "verified_correct": correct,
        "brier": brier,
        "abstention_correct": abstention_correct,
        "dangerous_false": dangerous,
        "prediction": pred,
        "gold": gold,
    }


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "ok"]
    by_cap: dict[str, list[dict[str, Any]]] = {}
    for r in ok:
        by_cap.setdefault(str(r.get("capability")), []).append(r)

    strata: dict[str, Any] = {}
    for cap, cap_rows in sorted(by_cap.items()):
        n = len(cap_rows)
        acc = sum(1 for r in cap_rows if r.get("verified_correct")) / n if n else 0.0
        briers = [float(r["brier"]) for r in cap_rows if r.get("brier") is not None]
        abs_rows = [r for r in cap_rows if r.get("abstention_correct") is not None]
        abs_acc = (
            sum(1 for r in abs_rows if r.get("abstention_correct")) / len(abs_rows) if abs_rows else None
        )
        dangerous = [r for r in cap_rows if r.get("dangerous_false")]
        latencies = [float(r["latency_ms"]) for r in cap_rows if r.get("latency_ms") is not None]
        strata[cap] = {
            "denominator": n,
            "verified_accuracy": acc,
            "mean_brier": statistics.mean(briers) if briers else None,
            "abstention_accuracy": abs_acc,
            "dangerous_false_rate": len(dangerous) / n if n else None,
            "latency_ms_p50": percentile(latencies, 50),
            "latency_ms_p95": percentile(latencies, 95),
        }

    lat_all = [float(r["latency_ms"]) for r in ok if r.get("latency_ms") is not None]
    startup = [float(r["startup_ms"]) for r in ok if r.get("startup_ms") is not None]
    vram = [float(r["vram_mb"]) for r in ok if r.get("vram_mb") is not None]
    ram = [float(r["ram_mb"]) for r in ok if r.get("ram_mb") is not None]

    return {
        "examples_total": len(rows),
        "examples_ok": len(ok),
        "examples_unavailable": sum(1 for r in rows if r.get("status") == "unavailable"),
        "examples_error": sum(1 for r in rows if r.get("status") == "error"),
        "by_capability": strata,
        "latency_ms_p50": percentile(lat_all, 50),
        "latency_ms_p95": percentile(lat_all, 95),
        "startup_ms_p50": percentile(startup, 50),
        "throughput_rps": (len(ok) / (sum(lat_all) / 1000.0)) if lat_all and sum(lat_all) > 0 else None,
        "vram_mb_peak": max(vram) if vram else None,
        "ram_mb_peak": max(ram) if ram else None,
    }
