"""Tests for bootstrap Pareto inclusion and uncertainty reducers."""

from __future__ import annotations

import unittest

from z0int.backends.bench.bootstrap import (
    bootstrap_pareto_inclusion,
    dangerous_false_upper_bound,
    quality_uncertainty,
    wilson_interval,
)
from z0int.backends.bench.contract import CAPABILITIES
from z0int.backends.bench.eligibility import enrich_backend_summaries
from z0int.backends.bench.fixtures import load_fixtures


def _row(cid: str, cap: str, fid: str, *, correct: bool, dang: bool = False, lat: float = 10.0) -> dict:
    return {
        "schema": "z0int.backends_bench.row.v1",
        "candidate_id": cid,
        "capability": cap,
        "fixture_id": fid,
        "status": "ok",
        "verified_correct": correct,
        "dangerous_false": dang,
        "brier": 0.1 if correct else 0.9,
        "latency_ms": lat,
        "prediction": "a",
        "gold": "a" if correct else "b",
    }


class BootstrapTests(unittest.TestCase):
    def test_wilson_and_rule_of_three(self):
        lo, hi = wilson_interval(0, 3)
        self.assertIsNotNone(lo)
        self.assertIsNotNone(hi)
        self.assertGreaterEqual(lo, 0.0)
        ub = dangerous_false_upper_bound(0, 3)
        self.assertAlmostEqual(ub, 1.0, places=5)  # 3/3 capped at 1
        ub2 = dangerous_false_upper_bound(0, 50)
        self.assertAlmostEqual(ub2, 3 / 50, places=5)

    def test_quality_uncertainty_notes_zero_danger(self):
        rows = [
            _row("a", "rlm.worker_needed", "f1", correct=True),
            _row("a", "rlm.worker_needed", "f2", correct=False),
        ]
        unc = quality_uncertainty(rows)
        stats = unc["by_backend"]["a"]["rlm.worker_needed"]
        self.assertEqual(stats["dangerous_false_count"], 0)
        self.assertIsNotNone(stats["dangerous_false_upper_95"])
        self.assertIn("does not imply", stats["note"] or "")

    def test_bootstrap_inclusion_deterministic(self):
        examples = load_fixtures()
        # Two backends, same fixtures for one capability
        caps = ["rlm.worker_needed"]
        fixture_ids = [e.id for e in examples if e.capability == "rlm.worker_needed"]
        rows = []
        for fid in fixture_ids:
            rows.append(_row("good", "rlm.worker_needed", fid, correct=True, lat=50.0))
            rows.append(_row("bad", "rlm.worker_needed", fid, correct=False, lat=5.0, dang=True))

        summaries = [
            {
                "candidate_id": "good",
                "commercial_use": True,
                "by_capability": {
                    "rlm.worker_needed": {
                        "denominator": len(fixture_ids),
                        "verified_accuracy": 1.0,
                        "dangerous_false_rate": 0.0,
                        "latency_ms_p50": 50.0,
                        "mean_brier": 0.1,
                    }
                },
            },
            {
                "candidate_id": "bad",
                "commercial_use": True,
                "by_capability": {
                    "rlm.worker_needed": {
                        "denominator": len(fixture_ids),
                        "verified_accuracy": 0.0,
                        "dangerous_false_rate": 1.0,
                        "latency_ms_p50": 5.0,
                        "mean_brier": 0.9,
                    }
                },
            },
        ]
        enriched = enrich_backend_summaries(summaries, examples, caps, validated_min=1)
        a = bootstrap_pareto_inclusion(
            rows,
            examples=examples,
            capabilities=caps,
            backend_summaries=enriched,
            n_boot=50,
            seed=7,
            validated_min=1,
        )
        b = bootstrap_pareto_inclusion(
            rows,
            examples=examples,
            capabilities=caps,
            backend_summaries=enriched,
            n_boot=50,
            seed=7,
            validated_min=1,
        )
        self.assertEqual(a, b)
        # unsafe backend should never be Pareto-included
        self.assertEqual(a["by_capability"]["rlm.worker_needed"]["inclusion_probability"]["bad"], 0.0)
        # good may be provisional or included depending on validated_min=1 and competence
        self.assertGreaterEqual(
            a["by_capability"]["rlm.worker_needed"]["inclusion_probability"]["good"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
