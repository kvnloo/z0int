"""Decision analytics reducer over Tokenomics bench events."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable

from tokenomics import TokenomicsEvent
from tokenomics.coverage import build_coverage_report, format_coverage_text

from .materialize import materialize_rows


def _percentile(values: list[float], pct: float) -> float | None:
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


def build_decision_analytics(events: Iterable[TokenomicsEvent]) -> dict[str, Any]:
    rows = [r for r in materialize_rows(events) if r.get("status") == "ok"]
    by_cap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_backend: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cap[str(row.get("capability"))].append(row)
        by_backend[str(row.get("candidate_id"))].append(row)

    def _cap_stats(cap_rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(cap_rows)
        correct = sum(1 for r in cap_rows if r.get("verified_correct"))
        dang = sum(1 for r in cap_rows if r.get("dangerous_false"))
        briers = [float(r["brier"]) for r in cap_rows if r.get("brier") is not None]
        lats = [float(r["latency_ms"]) for r in cap_rows if r.get("latency_ms") is not None]
        startups = [float(r["startup_ms"]) for r in cap_rows if r.get("startup_ms") is not None]
        return {
            "n": n,
            "correct": correct,
            "accuracy": correct / n if n else None,
            "dangerous_false_count": dang,
            "dangerous_false_rate": dang / n if n else None,
            "mean_brier": statistics.mean(briers) if briers else None,
            "latency_ms_p50": _percentile(lats, 50),
            "latency_ms_p95": _percentile(lats, 95),
            "startup_ms_p50": _percentile(startups, 50),
        }

    backend_sections = {
        bid: {
            "overall": _cap_stats(brows),
            "by_capability": {cap: _cap_stats([r for r in brows if r.get("capability") == cap]) for cap in sorted({r.get("capability") for r in brows})},
        }
        for bid, brows in sorted(by_backend.items())
    }

    return {
        "schema": "z0int.backends_bench.analytics.v1",
        "quality": {
            "by_capability": {cap: _cap_stats(crows) for cap, crows in sorted(by_cap.items())},
        },
        "safety": {
            "by_capability": {
                cap: {
                    "dangerous_false_count": sum(1 for r in crows if r.get("dangerous_false")),
                    "dangerous_false_rate": sum(1 for r in crows if r.get("dangerous_false")) / len(crows) if crows else None,
                }
                for cap, crows in sorted(by_cap.items())
            }
        },
        "latency": backend_sections,
        "reliability": {
            "rows_total": len(materialize_rows(events)),
            "rows_ok": len(rows),
            "rows_unavailable": sum(1 for r in materialize_rows(events) if r.get("status") == "unavailable"),
            "rows_error": sum(1 for r in materialize_rows(events) if r.get("status") == "error"),
        },
    }


def build_paired_comparisons(events: Iterable[TokenomicsEvent]) -> dict[str, Any]:
    rows = [r for r in materialize_rows(events) if r.get("status") == "ok"]
    by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_pair[(str(row.get("capability")), str(row.get("fixture_id")))].append(row)

    comparisons: list[dict[str, Any]] = []
    backend_ids = sorted({str(r.get("candidate_id")) for r in rows})
    for i, a in enumerate(backend_ids):
        for b in backend_ids[i + 1 :]:
            both_correct = a_only = b_only = both_wrong = 0
            lat_ratio: list[float] = []
            for (_cap, _fid), group in by_pair.items():
                by_id = {str(r.get("candidate_id")): r for r in group}
                if a not in by_id or b not in by_id:
                    continue
                ra, rb = by_id[a], by_id[b]
                ca = bool(ra.get("verified_correct"))
                cb = bool(rb.get("verified_correct"))
                if ca and cb:
                    both_correct += 1
                elif ca and not cb:
                    a_only += 1
                elif cb and not ca:
                    b_only += 1
                else:
                    both_wrong += 1
                la, lb = ra.get("latency_ms"), rb.get("latency_ms")
                if la and lb and float(lb) > 0:
                    lat_ratio.append(float(la) / float(lb))
            comparisons.append(
                {
                    "a": a,
                    "b": b,
                    "paired_fixtures": both_correct + a_only + b_only + both_wrong,
                    "both_correct": both_correct,
                    "a_only_correct": a_only,
                    "b_only_correct": b_only,
                    "both_wrong": both_wrong,
                    "median_latency_ratio_a_over_b": statistics.median(lat_ratio) if lat_ratio else None,
                }
            )
    return {"schema": "z0int.backends_bench.paired.v1", "comparisons": comparisons}


def build_coverage_section(events: Iterable[TokenomicsEvent]) -> dict[str, Any]:
    ev_list = list(events)
    report = build_coverage_report(ev_list, range_spec="7d")
    return report


def render_analytics_md(analytics: dict[str, Any], *, coverage_text: str | None = None) -> str:
    lines = ["# Decision bench analytics", ""]
    rel = analytics.get("reliability") or {}
    lines.append("## Reliability")
    lines.append("")
    lines.append(f"- rows total: {rel.get('rows_total')}")
    lines.append(f"- rows ok: {rel.get('rows_ok')}")
    lines.append(f"- rows unavailable: {rel.get('rows_unavailable')}")
    lines.append(f"- rows error: {rel.get('rows_error')}")
    lines.append("")
    lines.append("## Quality by capability")
    lines.append("")
    for cap, stats in sorted((analytics.get("quality") or {}).get("by_capability", {}).items()):
        lines.append(f"### {cap}")
        lines.append(f"- n={stats.get('n')} accuracy={stats.get('accuracy')} dangerous={stats.get('dangerous_false_rate')}")
        lines.append("")
    if coverage_text:
        lines.append("## Measurement coverage")
        lines.append("")
        lines.append("```")
        lines.append(coverage_text.rstrip())
        lines.append("```")
    return "\n".join(lines) + "\n"
