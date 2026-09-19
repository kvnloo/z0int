"""Paired promotion decisions (A0/B0/A1/B1) without editing frozen select.py."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Literal

CandidateVerdict = Literal["NO_OP", "REJECT", "PROVISIONAL_KEEP", "PROMOTED"]
ResearchJobStatus = Literal["SUCCESS", "ERROR", "DEFERRED"]


@dataclass
class PairedPromotionResult:
    candidate_verdict: CandidateVerdict
    research_job: ResearchJobStatus
    incumbent_mean: float | None
    challenger_mean: float | None
    improve_epsilon: float
    threshold: float | None
    arm_scores: dict[str, float]
    gates_pass: bool
    reason: str


def paired_decide(
    *,
    incumbent_scores: list[float],
    challenger_scores: list[float],
    gates_pass: bool,
    improve_epsilon: float = 0.05,
    promote: bool = True,
) -> PairedPromotionResult:
    """Compare paired means with the same epsilon rule as decide_status.

    Does not mutate frozen select.py — applies the identical threshold formula
    to paired contemporaneous measurements.
    """
    arms = {
        "A0": incumbent_scores[0] if len(incumbent_scores) > 0 else float("nan"),
        "B0": challenger_scores[0] if len(challenger_scores) > 0 else float("nan"),
        "A1": incumbent_scores[1] if len(incumbent_scores) > 1 else (
            incumbent_scores[0] if incumbent_scores else float("nan")
        ),
        "B1": challenger_scores[1] if len(challenger_scores) > 1 else (
            challenger_scores[0] if challenger_scores else float("nan")
        ),
    }
    if not gates_pass:
        return PairedPromotionResult(
            candidate_verdict="REJECT",
            research_job="SUCCESS",
            incumbent_mean=mean(incumbent_scores) if incumbent_scores else None,
            challenger_mean=mean(challenger_scores) if challenger_scores else None,
            improve_epsilon=improve_epsilon,
            threshold=None,
            arm_scores=arms,
            gates_pass=False,
            reason="gates_failed",
        )
    if not incumbent_scores or not challenger_scores:
        return PairedPromotionResult(
            candidate_verdict="REJECT",
            research_job="SUCCESS",
            incumbent_mean=None,
            challenger_mean=None,
            improve_epsilon=improve_epsilon,
            threshold=None,
            arm_scores=arms,
            gates_pass=True,
            reason="missing_paired_scores",
        )
    inc = mean(incumbent_scores)
    ch = mean(challenger_scores)
    threshold = inc * (1.0 - float(improve_epsilon))
    if ch < threshold:
        verdict: CandidateVerdict = "PROMOTED" if promote else "PROVISIONAL_KEEP"
        return PairedPromotionResult(
            candidate_verdict=verdict,
            research_job="SUCCESS",
            incumbent_mean=inc,
            challenger_mean=ch,
            improve_epsilon=float(improve_epsilon),
            threshold=threshold,
            arm_scores=arms,
            gates_pass=True,
            reason="paired_improve",
        )
    return PairedPromotionResult(
        candidate_verdict="REJECT",
        research_job="SUCCESS",
        incumbent_mean=inc,
        challenger_mean=ch,
        improve_epsilon=float(improve_epsilon),
        threshold=threshold,
        arm_scores=arms,
        gates_pass=True,
        reason="paired_no_improve",
    )


def noop_result(*, reason: str = "fingerprint_match") -> PairedPromotionResult:
    return PairedPromotionResult(
        candidate_verdict="NO_OP",
        research_job="SUCCESS",
        incumbent_mean=None,
        challenger_mean=None,
        improve_epsilon=0.0,
        threshold=None,
        arm_scores={},
        gates_pass=True,
        reason=reason,
    )
