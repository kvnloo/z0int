"""Bootstrap uncertainty for decision-capability Pareto and safety metrics.

All statistics are pure reducers over materialized compatibility rows
(which themselves derive from Tokenomics events).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from .eligibility import (
    DEFAULT_COMPETENCE_MARGIN,
    DEFAULT_VALIDATED_MIN_EXAMPLES,
    enrich_backend_summaries,
)
from .fixtures import BenchExample
from .metrics import percentile
from .pareto import pareto_frontier


def wilson_interval(successes: int, n: int, *, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return None, None
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt((p * (1 - p) / n) + (z2 / (4 * n * n)))
    return max(0.0, center - half), min(1.0, center + half)


def dangerous_false_upper_bound(count: int, n: int, *, confidence: float = 0.95) -> float | None:
    """One-sided upper bound on dangerous-false rate.

    Uses the rule of three when count==0 (approx 95%): 3/n.
    Otherwise a simple Clopper-Pearson-ish beta quantile via Wilson upper.
    """
    if n <= 0:
        return None
    if count <= 0:
        # Rule of three at ~95%; scale slightly for other confidence levels.
        scale = math.log(1.0 - confidence) / math.log(0.05) if confidence != 0.95 else 1.0
        return min(1.0, (3.0 * scale) / n)
    _lo, hi = wilson_interval(count, n)
    return hi


def _cap_stats_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    ok = [r for r in rows if r.get("status") == "ok"]
    if not ok:
        return None
    n = len(ok)
    correct = sum(1 for r in ok if r.get("verified_correct"))
    dang = sum(1 for r in ok if r.get("dangerous_false"))
    briers = [float(r["brier"]) for r in ok if r.get("brier") is not None]
    lats = [float(r["latency_ms"]) for r in ok if r.get("latency_ms") is not None]
    return {
        "denominator": n,
        "verified_accuracy": correct / n,
        "dangerous_false_rate": dang / n,
        "dangerous_false_count": dang,
        "mean_brier": (sum(briers) / len(briers)) if briers else None,
        "latency_ms_p50": percentile(lats, 50),
        "latency_ms_p95": percentile(lats, 95),
        "correct": correct,
    }


def build_backend_summaries_from_rows(
    rows: list[dict[str, Any]],
    *,
    candidate_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rebuild thin backend summaries from materialized rows (bootstrap reducer)."""
    by_backend: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_backend[str(row.get("candidate_id"))].append(row)

    summaries: list[dict[str, Any]] = []
    for cid, brows in sorted(by_backend.items()):
        meta = (candidate_meta or {}).get(cid) or {}
        by_cap: dict[str, Any] = {}
        for cap in sorted({str(r.get("capability")) for r in brows}):
            stats = _cap_stats_from_rows([r for r in brows if r.get("capability") == cap])
            if stats:
                by_cap[cap] = stats
        summaries.append(
            {
                "candidate_id": cid,
                "status": meta.get("status", "available"),
                "commercial_use": meta.get("commercial_use"),
                "platforms": list(meta.get("platforms") or []),
                "backend_impl": meta.get("backend_impl"),
                "by_capability": by_cap,
            }
        )
    return summaries


def quality_uncertainty(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy CIs and dangerous-false upper bounds per backend×capability."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("status") != "ok":
            continue
        by[(str(row.get("candidate_id")), str(row.get("capability")))].append(row)

    out: dict[str, Any] = {}
    for (cid, cap), group in sorted(by.items()):
        n = len(group)
        correct = sum(1 for r in group if r.get("verified_correct"))
        dang = sum(1 for r in group if r.get("dangerous_false"))
        lo, hi = wilson_interval(correct, n)
        out.setdefault(cid, {})[cap] = {
            "n": n,
            "accuracy": correct / n if n else None,
            "accuracy_ci95": [lo, hi],
            "dangerous_false_count": dang,
            "dangerous_false_rate": dang / n if n else None,
            "dangerous_false_upper_95": dangerous_false_upper_bound(dang, n),
            "note": (
                "Zero observed dangerous failures does not imply true rate is 0; "
                f"upper bound ≈ {dangerous_false_upper_bound(dang, n)}"
                if dang == 0 and n > 0
                else None
            ),
        }
    return {
        "schema": "z0int.backends_bench.uncertainty.v1",
        "by_backend": out,
    }


def bootstrap_pareto_inclusion(
    rows: list[dict[str, Any]],
    *,
    examples: list[BenchExample],
    capabilities: list[str],
    backend_summaries: list[dict[str, Any]] | None = None,
    n_boot: int = 500,
    seed: int = 0,
    competence_margin: float = DEFAULT_COMPETENCE_MARGIN,
    validated_min: int = DEFAULT_VALIDATED_MIN_EXAMPLES,
) -> dict[str, Any]:
    """Resample fixtures and estimate Pareto inclusion probability per backend.

    Resampling is stratified by capability: for each capability, draw fixtures
    with replacement from that capability's fixture set, then rebuild summaries
    and recompute the eligible Pareto frontier.
    """
    rng = random.Random(seed)
    meta = {
        s["candidate_id"]: {
            "status": s.get("status"),
            "commercial_use": s.get("commercial_use"),
            "platforms": s.get("platforms"),
            "backend_impl": s.get("backend_impl"),
        }
        for s in (backend_summaries or [])
    }

    # Index ok rows by (capability, fixture_id, candidate_id)
    by_cap_fix: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    backends = sorted({str(r.get("candidate_id")) for r in rows})
    for row in rows:
        if row.get("status") != "ok":
            continue
        by_cap_fix[str(row.get("capability"))][str(row.get("fixture_id"))].append(row)

    inclusion: dict[str, dict[str, int]] = {
        cap: {bid: 0 for bid in backends} for cap in capabilities
    }
    eligible_counts: dict[str, dict[str, int]] = {
        cap: {bid: 0 for bid in backends} for cap in capabilities
    }
    valid_draws = 0

    for _ in range(n_boot):
        sampled: list[dict[str, Any]] = []
        for cap in capabilities:
            fixtures = sorted(by_cap_fix[cap].keys())
            if not fixtures:
                continue
            draws = [rng.choice(fixtures) for _ in fixtures]
            for fid in draws:
                sampled.extend(by_cap_fix[cap][fid])

        if not sampled:
            continue
        valid_draws += 1
        thin = build_backend_summaries_from_rows(sampled, candidate_meta=meta)
        enriched = enrich_backend_summaries(
            thin,
            examples,
            capabilities,
            margin=competence_margin,
            validated_min=validated_min,
        )
        for cap in capabilities:
            for b in enriched:
                bid = b["candidate_id"]
                stats = (b.get("by_capability") or {}).get(cap) or {}
                if stats.get("pareto_eligible"):
                    eligible_counts[cap][bid] = eligible_counts[cap].get(bid, 0) + 1
            frontier = set(pareto_frontier(enriched, cap))
            for bid in frontier:
                inclusion[cap][bid] = inclusion[cap].get(bid, 0) + 1

    by_capability: dict[str, Any] = {}
    for cap in capabilities:
        den = valid_draws or 1
        by_capability[cap] = {
            "n_bootstrap": valid_draws,
            "inclusion_probability": {
                bid: inclusion[cap].get(bid, 0) / den for bid in sorted(inclusion[cap])
            },
            "eligible_probability": {
                bid: eligible_counts[cap].get(bid, 0) / den for bid in sorted(eligible_counts[cap])
            },
        }

    return {
        "schema": "z0int.backends_bench.bootstrap_pareto.v1",
        "n_bootstrap": n_boot,
        "seed": seed,
        "valid_draws": valid_draws,
        "note": (
            "Inclusion probability is the fraction of fixture-resampled datasets "
            "in which a backend remained on the eligible Pareto frontier. "
            "At small n this can be unstable — treat provisional evidence seriously."
        ),
        "by_capability": by_capability,
    }


def render_bootstrap_md(report: dict[str, Any], uncertainty: dict[str, Any] | None = None) -> str:
    lines = [
        "# Bootstrap Pareto stability",
        "",
        report.get("note", ""),
        "",
        f"Bootstrap draws: {report.get('valid_draws')} / {report.get('n_bootstrap')} (seed={report.get('seed')})",
        "",
    ]
    for cap, block in sorted((report.get("by_capability") or {}).items()):
        lines.append(f"## {cap}")
        lines.append("")
        lines.append("| backend | P(Pareto) | P(eligible) |")
        lines.append("|---------|-----------|-------------|")
        inc = block.get("inclusion_probability") or {}
        elig = block.get("eligible_probability") or {}
        for bid in sorted(inc):
            lines.append(
                f"| {bid} | {inc[bid]:.3f} | {elig.get(bid, 0.0):.3f} |"
            )
        lines.append("")

    if uncertainty:
        lines.append("# Measurement uncertainty")
        lines.append("")
        for bid, caps in sorted((uncertainty.get("by_backend") or {}).items()):
            lines.append(f"## {bid}")
            lines.append("")
            for cap, stats in sorted(caps.items()):
                ci = stats.get("accuracy_ci95") or [None, None]
                lines.append(
                    f"- `{cap}`: n={stats.get('n')} acc={stats.get('accuracy')} "
                    f"CI95=[{ci[0]}, {ci[1]}] "
                    f"dangerous_false={stats.get('dangerous_false_rate')} "
                    f"upper95={stats.get('dangerous_false_upper_95')}"
                )
                if stats.get("note"):
                    lines.append(f"  - {stats['note']}")
            lines.append("")
    return "\n".join(lines) + "\n"
