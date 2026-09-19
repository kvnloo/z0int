"""Pre-Pareto capability eligibility: competence gate + evidence strength."""

from __future__ import annotations

from typing import Any, Literal

from .fixtures import BenchExample

ELIGIBILITY_SCHEMA = "z0int.backends_bench.eligibility.v1"

DEFAULT_COMPETENCE_MARGIN = 0.05
DEFAULT_VALIDATED_MIN_EXAMPLES = 50

PRODUCTION_MIN_ACCURACY: dict[str, float] = {
    "rlm.worker_needed": 0.60,
    "retry_or_escalate": 0.50,
    "verification_needed": 0.55,
}

EvidenceState = Literal["PROVISIONAL", "VALIDATED"]
EligibilityStatus = Literal["pareto_eligible", "measured_but_ineligible", "excluded_unsafe"]


def option_count(example: BenchExample) -> int:
    q = example.question
    if q.type == "boolean":
        return 2
    if q.type == "choice":
        return len(q.options)
    return len(q.levels)


def trivial_baseline_for_capability(examples: list[BenchExample], capability: str) -> dict[str, Any]:
    cap_rows = [e for e in examples if e.capability == capability]
    if not cap_rows:
        return {
            "capability": capability,
            "fixture_count": 0,
            "trivial_baseline": None,
            "per_fixture_baselines": [],
        }
    per = [1.0 / option_count(e) for e in cap_rows]
    return {
        "capability": capability,
        "fixture_count": len(cap_rows),
        "trivial_baseline": sum(per) / len(per),
        "per_fixture_baselines": [
            {"fixture_id": e.id, "option_count": option_count(e), "baseline": 1.0 / option_count(e)}
            for e in cap_rows
        ],
    }


def competence_threshold_for_capability(
    capability: str,
    *,
    trivial_baseline: float | None,
    margin: float = DEFAULT_COMPETENCE_MARGIN,
    production_min: dict[str, float] | None = None,
) -> float | None:
    if trivial_baseline is None:
        return None
    floor = float(trivial_baseline) + float(margin)
    prod = (production_min or PRODUCTION_MIN_ACCURACY).get(capability)
    if prod is not None:
        floor = max(floor, float(prod))
    return floor


def evidence_state(n: int, *, validated_min: int = DEFAULT_VALIDATED_MIN_EXAMPLES) -> EvidenceState:
    return "VALIDATED" if int(n) >= int(validated_min) else "PROVISIONAL"


def assess_capability_stratum(
    stats: dict[str, Any] | None,
    *,
    capability: str,
    trivial_baseline: float | None,
    competence_threshold: float | None,
    validated_min: int = DEFAULT_VALIDATED_MIN_EXAMPLES,
    competence_margin: float = DEFAULT_COMPETENCE_MARGIN,
) -> dict[str, Any]:
    if not stats:
        return {
            "capability": capability,
            "eligibility_status": "measured_but_ineligible",
            "ineligibility_reason": "no_measurements",
            "pareto_eligible": False,
            "evidence_state": evidence_state(0, validated_min=validated_min),
            "trivial_baseline": trivial_baseline,
            "competence_margin": competence_margin,
            "competence_threshold": competence_threshold,
            "pareto_status": "not_eligible",
        }

    n = int(stats.get("denominator") or 0)
    acc = stats.get("verified_accuracy")
    dang = stats.get("dangerous_false_rate")
    ev = evidence_state(n, validated_min=validated_min)

    overlay: dict[str, Any] = {
        "capability": capability,
        "n": n,
        "verified_accuracy": acc,
        "trivial_baseline": trivial_baseline,
        "competence_margin": competence_margin,
        "competence_threshold": competence_threshold,
        "dangerous_false_rate": dang,
        "mean_brier": stats.get("mean_brier"),
        "latency_ms_p50": stats.get("latency_ms_p50"),
        "latency_ms_p95": stats.get("latency_ms_p95"),
        "evidence_state": ev,
        "eligibility_status": "measured_but_ineligible",
        "ineligibility_reason": None,
        "pareto_eligible": False,
        "pareto_status": "not_eligible",
    }

    if dang is not None and float(dang) > 0:
        overlay["eligibility_status"] = "excluded_unsafe"
        overlay["ineligibility_reason"] = "dangerous_false"
        overlay["pareto_status"] = "excluded_unsafe"
        return overlay

    if acc is None or competence_threshold is None:
        overlay["ineligibility_reason"] = "insufficient_metrics"
        overlay["pareto_status"] = "measured_but_ineligible"
        return overlay

    if float(acc) < float(competence_threshold):
        overlay["ineligibility_reason"] = "below_competence_floor"
        overlay["pareto_status"] = "measured_but_ineligible"
        return overlay

    if ev == "PROVISIONAL":
        overlay["ineligibility_reason"] = "provisional_evidence"
        overlay["pareto_status"] = "measured_but_ineligible"
        return overlay

    overlay["eligibility_status"] = "pareto_eligible"
    overlay["ineligibility_reason"] = None
    overlay["pareto_eligible"] = True
    overlay["pareto_status"] = "eligible"
    return overlay


def capability_baselines(
    examples: list[BenchExample],
    capabilities: list[str],
    *,
    margin: float = DEFAULT_COMPETENCE_MARGIN,
    production_min: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for cap in capabilities:
        base = trivial_baseline_for_capability(examples, cap)
        tb = base.get("trivial_baseline")
        out[cap] = {
            **base,
            "competence_margin": margin,
            "competence_threshold": competence_threshold_for_capability(
                cap,
                trivial_baseline=tb,
                margin=margin,
                production_min=production_min,
            ),
            "validated_min_examples": DEFAULT_VALIDATED_MIN_EXAMPLES,
        }
    return out


def enrich_backend_summary(
    summary: dict[str, Any],
    *,
    examples: list[BenchExample],
    capabilities: list[str],
    margin: float = DEFAULT_COMPETENCE_MARGIN,
    validated_min: int = DEFAULT_VALIDATED_MIN_EXAMPLES,
    production_min: dict[str, float] | None = None,
) -> dict[str, Any]:
    baselines = capability_baselines(
        examples,
        capabilities,
        margin=margin,
        production_min=production_min,
    )
    by_cap = dict(summary.get("by_capability") or {})
    eligibility: dict[str, Any] = {}
    enriched_by_cap: dict[str, Any] = {}

    for cap in capabilities:
        stats = by_cap.get(cap)
        cap_base = baselines.get(cap) or {}
        overlay = assess_capability_stratum(
            stats,
            capability=cap,
            trivial_baseline=cap_base.get("trivial_baseline"),
            competence_threshold=cap_base.get("competence_threshold"),
            validated_min=validated_min,
            competence_margin=margin,
        )
        eligibility[cap] = overlay
        if stats:
            enriched = dict(stats)
            enriched.update(
                {
                    "n": overlay["n"],
                    "trivial_baseline": overlay["trivial_baseline"],
                    "competence_margin": overlay["competence_margin"],
                    "competence_threshold": overlay["competence_threshold"],
                    "evidence_state": overlay["evidence_state"],
                    "eligibility_status": overlay["eligibility_status"],
                    "ineligibility_reason": overlay["ineligibility_reason"],
                    "pareto_eligible": overlay["pareto_eligible"],
                    "pareto_status": overlay["pareto_status"],
                }
            )
            enriched_by_cap[cap] = enriched

    out = dict(summary)
    out["by_capability"] = enriched_by_cap if enriched_by_cap else by_cap
    out["eligibility_by_capability"] = eligibility
    return out


def enrich_backend_summaries(
    summaries: list[dict[str, Any]],
    examples: list[BenchExample],
    capabilities: list[str],
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return [enrich_backend_summary(s, examples=examples, capabilities=capabilities, **kwargs) for s in summaries]
