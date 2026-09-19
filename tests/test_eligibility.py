"""Tests for pre-Pareto eligibility gates."""

from __future__ import annotations

import unittest

from z0int.backends.bench.contract import CAPABILITIES
from z0int.backends.bench.eligibility import (
    assess_capability_stratum,
    enrich_backend_summary,
    evidence_state,
    trivial_baseline_for_capability,
)
from z0int.backends.bench.fixtures import load_fixtures
from z0int.backends.bench.pareto import build_pareto_report, pareto_frontier


class EligibilityTests(unittest.TestCase):
    def test_trivial_baseline_from_option_cardinality(self):
        examples = load_fixtures()
        base = trivial_baseline_for_capability(examples, "tool_family_select")
        self.assertAlmostEqual(base["trivial_baseline"], 0.125, places=3)
        self.assertEqual(base["fixture_count"], 2)

    def test_zero_accuracy_fails_competence(self):
        examples = load_fixtures()
        base = trivial_baseline_for_capability(examples, "tool_family_select")
        overlay = assess_capability_stratum(
            {
                "denominator": 2,
                "verified_accuracy": 0.0,
                "dangerous_false_rate": 0.0,
                "mean_brier": 1.0,
            },
            capability="tool_family_select",
            trivial_baseline=base["trivial_baseline"],
            competence_threshold=0.175,
        )
        self.assertEqual(overlay["ineligibility_reason"], "below_competence_floor")
        self.assertFalse(overlay["pareto_eligible"])

    def test_provisional_blocks_even_competent_backend(self):
        overlay = assess_capability_stratum(
            {
                "denominator": 3,
                "verified_accuracy": 0.9,
                "dangerous_false_rate": 0.0,
            },
            capability="rlm.worker_needed",
            trivial_baseline=1 / 3,
            competence_threshold=0.60,
            validated_min=50,
        )
        self.assertEqual(overlay["evidence_state"], "PROVISIONAL")
        self.assertEqual(overlay["ineligibility_reason"], "provisional_evidence")
        self.assertFalse(overlay["pareto_eligible"])

    def test_fast_random_backend_not_on_pareto_frontier(self):
        examples = load_fixtures()
        fast_random = {
            "candidate_id": "fast_random",
            "commercial_use": True,
            "vram_mb_peak": 500,
            "by_capability": {
                "tool_family_select": {
                    "denominator": 2,
                    "verified_accuracy": 0.0,
                    "mean_brier": 1.0,
                    "dangerous_false_rate": 0.0,
                    "latency_ms_p50": 5.0,
                }
            },
        }
        good = {
            "candidate_id": "good",
            "commercial_use": True,
            "vram_mb_peak": 5000,
            "by_capability": {
                "tool_family_select": {
                    "denominator": 2,
                    "verified_accuracy": 1.0,
                    "mean_brier": 0.05,
                    "dangerous_false_rate": 0.0,
                    "latency_ms_p50": 100.0,
                }
            },
        }
        enriched = [
            enrich_backend_summary(fast_random, examples=examples, capabilities=["tool_family_select"]),
            enrich_backend_summary(good, examples=examples, capabilities=["tool_family_select"]),
        ]
        frontier = pareto_frontier(enriched, "tool_family_select")
        self.assertEqual(frontier, [])

    def test_unsafe_still_excluded(self):
        unsafe = {
            "candidate_id": "unsafe",
            "commercial_use": True,
            "vram_mb_peak": 100,
            "by_capability": {
                "retry_or_escalate": {
                    "denominator": 2,
                    "verified_accuracy": 1.0,
                    "latency_ms_p50": 8,
                    "mean_brier": 0.05,
                    "dangerous_false_rate": 0.5,
                }
            },
        }
        enriched = enrich_backend_summary(
            unsafe,
            examples=load_fixtures(),
            capabilities=["retry_or_escalate"],
        )
        stats = enriched["by_capability"]["retry_or_escalate"]
        self.assertEqual(stats["eligibility_status"], "excluded_unsafe")
        self.assertNotIn("unsafe", pareto_frontier([enriched], "retry_or_escalate"))

    def test_evidence_state_threshold(self):
        self.assertEqual(evidence_state(3, validated_min=50), "PROVISIONAL")
        self.assertEqual(evidence_state(50, validated_min=50), "VALIDATED")

    def test_pareto_report_marks_ineligible_backends(self):
        examples = load_fixtures()
        summaries = []
        for cid, acc in (
            ("openjev_06b", 0.0),
            ("decider_2b", 1.0),
        ):
            summaries.append(
                enrich_backend_summary(
                    {
                        "candidate_id": cid,
                        "commercial_use": True,
                        "vram_mb_peak": 3000,
                        "by_capability": {
                            "tool_family_select": {
                                "denominator": 2,
                                "verified_accuracy": acc,
                                "mean_brier": 0.1 if acc else 1.0,
                                "dangerous_false_rate": 0.0,
                                "latency_ms_p50": 30 if acc else 5,
                            }
                        },
                    },
                    examples=examples,
                    capabilities=CAPABILITIES,
                )
            )
        report = build_pareto_report(
            contract="decision-capability-v1",
            capabilities=["tool_family_select"],
            backend_summaries=summaries,
            examples=examples,
        )
        block = report["by_capability"]["tool_family_select"]
        self.assertIn("openjev_06b", block["measured_but_ineligible"])
        self.assertEqual(block["pareto_optimal"], [])


if __name__ == "__main__":
    unittest.main()
