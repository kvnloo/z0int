"""Pareto dominance analysis per capability stratum."""

from __future__ import annotations

from typing import Any


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


def dominates(a: dict[str, Any], b: dict[str, Any], cap: str) -> bool:
    pa, pb = _point(a, cap), _point(b, cap)
    if pa["quality"] is None or pb["quality"] is None:
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
    ids = [str(b["candidate_id"]) for b in backends if (b.get("by_capability") or {}).get(cap)]
    frontier: list[str] = []
    for i, bid in enumerate(ids):
        dominated = False
        for j, other in enumerate(ids):
            if i == j:
                continue
            if dominates(backends[j], backends[i], cap):
                dominated = True
                break
        if not dominated:
            frontier.append(bid)
    return frontier


def dominated_by(backends: list[dict[str, Any]], cap: str) -> dict[str, list[str]]:
    ids = [str(b["candidate_id"]) for b in backends if (b.get("by_capability") or {}).get(cap)]
    out: dict[str, list[str]] = {i: [] for i in ids}
    for i, a_id in enumerate(ids):
        for j, b_id in enumerate(ids):
            if i == j:
                continue
            if dominates(backends[j], backends[i], cap):
                out[a_id].append(b_id)
    return {k: v for k, v in out.items() if v}


def build_pareto_report(
    *,
    contract: str,
    capabilities: list[str],
    backend_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    per_cap: dict[str, Any] = {}
    for cap in capabilities:
        per_cap[cap] = {
            "pareto_optimal": pareto_frontier(backend_summaries, cap),
            "dominated_by": dominated_by(backend_summaries, cap),
            "strata": {
                b["candidate_id"]: (b.get("by_capability") or {}).get(cap)
                for b in backend_summaries
                if (b.get("by_capability") or {}).get(cap)
            },
        }
    return {
        "schema": "z0int.backends_bench.pareto.v1",
        "contract": contract,
        "note": "No universal winner declared. Dominance is per-capability only.",
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
        optimal = block.get("pareto_optimal") or []
        lines.append(f"**Pareto-optimal:** {', '.join(optimal) if optimal else '(none with runnable results)'}")
        lines.append("")
        lines.append("| backend | accuracy | p50 ms | mean Brier | dangerous | denom |")
        lines.append("|---------|----------|--------|------------|-----------|-------|")
        for bid, stats in sorted((block.get("strata") or {}).items()):
            if not stats:
                continue
            lines.append(
                "| {bid} | {acc:.3f} | {p50} | {brier} | {dang} | {n} |".format(
                    bid=bid,
                    acc=float(stats.get("verified_accuracy") or 0),
                    p50=stats.get("latency_ms_p50"),
                    brier=("{:.4f}".format(stats["mean_brier"]) if stats.get("mean_brier") is not None else "-"),
                    dang=("{:.3f}".format(stats["dangerous_false_rate"]) if stats.get("dangerous_false_rate") is not None else "-"),
                    n=stats.get("denominator"),
                )
            )
        dom = block.get("dominated_by") or {}
        if dom:
            lines.append("")
            lines.append("**Dominated by:**")
            for bid, by in sorted(dom.items()):
                lines.append(f"- `{bid}` ← {', '.join(f'`{x}`' for x in by)}")
        lines.append("")
    return "\n".join(lines)
