"""Pareto dominance analysis per capability stratum (eligible candidates only)."""

from __future__ import annotations

from typing import Any

from .eligibility import capability_baselines


def _point(row: dict[str, Any], cap: str) -> dict[str, float | bool | None]:
    cap_stats = (row.get("by_capability") or {}).get(cap) or {}
    return {
        "quality": cap_stats.get("verified_accuracy"),
        "latency_p50": cap_stats.get("latency_ms_p50"),
        "memory_vram": row.get("vram_mb_peak"),
        "commercial_eligible": row.get("commercial_use"),
    }


def _better(a: float | None, b: float | None, *, higher_is_better: bool) -> bool | None:
    if a is None or b is None:
        return None
    if a == b:
        return None
    return a > b if higher_is_better else a < b


def _pareto_eligible(stats: dict[str, Any] | None) -> bool:
    """Eligible only after pre-Pareto gates (unsafe, competence, evidence strength)."""
    if not stats:
        return False
    if stats.get("pareto_eligible") is not None:
        return bool(stats.get("pareto_eligible"))
    # Legacy summaries without enrichment: unsafe-only fallback.
    dang = stats.get("dangerous_false_rate")
    if dang is not None and float(dang) > 0:
        return False
    return True


def dominates(a: dict[str, Any], b: dict[str, Any], cap: str) -> bool:
    pa, pb = _point(a, cap), _point(b, cap)
    if pa["quality"] is None or pb["quality"] is None:
        return False
    a_stats = (a.get("by_capability") or {}).get(cap) or {}
    b_stats = (b.get("by_capability") or {}).get(cap) or {}
    if not _pareto_eligible(a_stats) or not _pareto_eligible(b_stats):
        return False
    checks = [
        _better(pa["quality"], pb["quality"], higher_is_better=True),
        _better(pa["latency_p50"], pb["latency_p50"], higher_is_better=False),
        _better(pa["memory_vram"], pb["memory_vram"], higher_is_better=False),
    ]
    if pa["commercial_eligible"] is False and pb["commercial_eligible"] is True:
        return False
    if pa["commercial_eligible"] is True and pb["commercial_eligible"] is False:
        checks.append(True)
    usable = [c for c in checks if c is not None]
    if not usable or not any(c is True for c in usable):
        return False
    return all(c is not False for c in usable) and any(c is True for c in usable)


def pareto_frontier(backends: list[dict[str, Any]], cap: str) -> list[str]:
    eligible = [
        b
        for b in backends
        if _pareto_eligible((b.get("by_capability") or {}).get(cap))
    ]
    ids = [str(b["candidate_id"]) for b in eligible]
    frontier: list[str] = []
    for i, bid in enumerate(ids):
        dominated = False
        for j, _other in enumerate(ids):
            if i == j:
                continue
            if dominates(eligible[j], eligible[i], cap):
                dominated = True
                break
        if not dominated:
            frontier.append(bid)
    return frontier


def dominated_by(backends: list[dict[str, Any]], cap: str) -> dict[str, list[str]]:
    eligible = [
        b
        for b in backends
        if _pareto_eligible((b.get("by_capability") or {}).get(cap))
    ]
    ids = [str(b["candidate_id"]) for b in eligible]
    out: dict[str, list[str]] = {i: [] for i in ids}
    for i, a_id in enumerate(ids):
        for j, _b_id in enumerate(ids):
            if i == j:
                continue
            if dominates(eligible[j], eligible[i], cap):
                out[a_id].append(ids[j])
    return {k: v for k, v in out.items() if v}


def build_pareto_report(
    *,
    contract: str,
    capabilities: list[str],
    backend_summaries: list[dict[str, Any]],
    examples: list | None = None,
) -> dict[str, Any]:
    per_cap: dict[str, Any] = {}
    cap_baselines = capability_baselines(examples or [], capabilities) if examples else {}

    for cap in capabilities:
        strata = {
            b["candidate_id"]: (b.get("by_capability") or {}).get(cap)
            for b in backend_summaries
            if (b.get("by_capability") or {}).get(cap)
        }
        eligibility_rows = {
            bid: (b.get("eligibility_by_capability") or {}).get(cap)
            for b in backend_summaries
            for bid in [b["candidate_id"]]
            if (b.get("eligibility_by_capability") or {}).get(cap)
        }
        excluded_unsafe = [
            bid
            for bid, stats in strata.items()
            if stats and (stats.get("eligibility_status") == "excluded_unsafe" or (
                stats.get("dangerous_false_rate") is not None and float(stats["dangerous_false_rate"]) > 0
            ))
        ]
        ineligible = [
            bid
            for bid, stats in strata.items()
            if stats
            and stats.get("eligibility_status") == "measured_but_ineligible"
            and bid not in excluded_unsafe
        ]
        per_cap[cap] = {
            "pareto_optimal": pareto_frontier(backend_summaries, cap),
            "dominated_by": dominated_by(backend_summaries, cap),
            "excluded_unsafe": excluded_unsafe,
            "measured_but_ineligible": ineligible,
            "capability_baselines": cap_baselines.get(cap),
            "strata": strata,
            "eligibility": eligibility_rows,
        }
    return {
        "schema": "z0int.backends_bench.pareto.v2",
        "contract": contract,
        "note": (
            "No universal winner declared. Dominance is per-capability only. "
            "Pareto runs over pareto_eligible candidates (safe + competent + VALIDATED evidence)."
        ),
        "by_capability": per_cap,
    }


def render_pareto_md(report: dict[str, Any]) -> str:
    lines = [
        "# Decision backend Pareto analysis",
        "",
        f"Contract: `{report.get('contract')}`",
        "",
        report.get("note", ""),
        "",
    ]
    for cap, block in (report.get("by_capability") or {}).items():
        lines.append(f"## {cap}")
        lines.append("")
        base = block.get("capability_baselines") or {}
        if base.get("trivial_baseline") is not None:
            lines.append(
                f"**Capability baselines:** trivial={base['trivial_baseline']:.3f}, "
                f"competence threshold={base.get('competence_threshold'):.3f} "
                f"(margin={base.get('competence_margin')}, n_fixtures={base.get('fixture_count')}, "
                f"validated_min={base.get('validated_min_examples')})"
            )
            lines.append("")
        optimal = block.get("pareto_optimal") or []
        lines.append(
            f"**Pareto-optimal (eligible only):** {', '.join(optimal) if optimal else '(empty — no eligible candidates)'}"
        )
        excluded = block.get("excluded_unsafe") or []
        if excluded:
            lines.append(f"**Excluded (dangerous false > 0):** {', '.join(excluded)}")
        ineligible = block.get("measured_but_ineligible") or []
        if ineligible:
            lines.append(f"**Measured but ineligible:** {', '.join(ineligible)}")
        lines.append("")
        lines.append(
            "| backend | n | acc | baseline | threshold | dang | evidence | eligibility | p50 ms | Brier | Pareto |"
        )
        lines.append(
            "|---------|---|-----|----------|-----------|------|----------|-------------|--------|-------|--------|"
        )
        for bid, stats in sorted((block.get("strata") or {}).items()):
            if not stats:
                continue
            elig = stats.get("eligibility_status") or "-"
            reason = stats.get("ineligibility_reason")
            if reason and elig != "pareto_eligible":
                elig = f"{elig} ({reason})"
            pareto_status = stats.get("pareto_status") or "-"
            if bid in optimal:
                pareto_status = "optimal"
            lines.append(
                "| {bid} | {n} | {acc:.3f} | {base:.3f} | {thr} | {dang} | {ev} | {elig} | {p50} | {brier} | {pareto} |".format(
                    bid=bid,
                    n=stats.get("n") or stats.get("denominator"),
                    acc=float(stats.get("verified_accuracy") or 0),
                    base=float(stats.get("trivial_baseline") or 0),
                    thr=(
                        f"{stats['competence_threshold']:.3f}"
                        if stats.get("competence_threshold") is not None
                        else "-"
                    ),
                    dang=(
                        f"{stats['dangerous_false_rate']:.3f}"
                        if stats.get("dangerous_false_rate") is not None
                        else "-"
                    ),
                    ev=stats.get("evidence_state") or "-",
                    elig=elig,
                    p50=stats.get("latency_ms_p50"),
                    brier=(
                        f"{stats['mean_brier']:.4f}"
                        if stats.get("mean_brier") is not None
                        else "-"
                    ),
                    pareto=pareto_status,
                )
            )
        dom = block.get("dominated_by") or {}
        if dom:
            lines.append("")
            lines.append("**Dominated by (among eligible):**")
            for bid, by in sorted(dom.items()):
                lines.append(f"- `{bid}` ← {', '.join(f'`{x}`' for x in by)}")
        lines.append("")
    return "\n".join(lines)
