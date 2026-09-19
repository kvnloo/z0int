"""Tests for decision-capability-v1 Pareto benchmark harness."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from z0int.backends.base import (
    BackendCapabilities,
    BackendHealth,
    DecisionAnswer,
    DecisionRequest,
    DecisionResult,
    DecisionQuestion,
    DecisionOption,
)
from z0int.backends.bench.contract import BENCH_CONTRACT, CAPABILITIES
from z0int.backends.bench.eligibility import enrich_backend_summary
from z0int.backends.bench.fixtures import BenchExample, load_fixtures
from z0int.backends.bench.metrics import score_example
from z0int.backends.bench.pareto import build_pareto_report, dominates, pareto_frontier
from z0int.backends.bench.roster import probe_candidate
from z0int.backends.bench.runner import run_bench


class GoldMockBackend:
    ID = "gold_mock"

    def __init__(self, gold_by_request: dict[str, str]):
        self.gold_by_request = gold_by_request

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id=self.ID,
            kind="mock",
            description="returns fixture gold labels",
            supports_boolean=True,
            supports_choice=True,
            supports_score=False,
            max_choice_options=16,
            max_score_levels=0,
            supports_batch_questions=False,
            local=True,
        )

    def health(self, *, load: bool = False) -> BackendHealth:
        return BackendHealth(
            id=self.ID,
            configured=True,
            ready=True,
            loaded=True,
            model="mock",
            revision=None,
            detail="mock",
        )

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        rid = request.request_id or "unknown"
        gold = self.gold_by_request[rid]
        q = request.questions[0]
        if q.type == "boolean":
            probs = {"false": 0.05, "true": 0.05}
            probs[gold] = 0.9
            value = gold == "true"
        else:
            ids = [o.id for o in q.options]
            rest = max(1, len(ids) - 1)
            probs = {i: (0.9 if i == gold else 0.1 / rest) for i in ids}
            value = gold
        return DecisionResult(
            backend=self.ID,
            model="mock",
            revision=None,
            answers=(
                DecisionAnswer(
                    question_id=q.id,
                    type=q.type,
                    probabilities=probs,
                    value=value,
                    confidence=0.9,
                ),
            ),
            latency_ms=1.0,
        )


class BenchHarnessTests(unittest.TestCase):
    def test_fixtures_load(self):
        examples = load_fixtures()
        self.assertGreaterEqual(len(examples), 10)
        caps = {e.capability for e in examples}
        for c in CAPABILITIES:
            self.assertIn(c, caps)

    def test_score_example_brier(self):
        ex = BenchExample(
            id="t",
            capability="rlm.worker_needed",
            provenance="test",
            state={"x": 1},
            question=DecisionQuestion(
                id="d",
                type="choice",
                instructions="pick",
                options=(DecisionOption("a", "A"), DecisionOption("b", "B")),
            ),
            gold="a",
        )
        scored = score_example(ex, probabilities={"a": 0.8, "b": 0.2}, pred="a")
        self.assertTrue(scored["verified_correct"])
        self.assertAlmostEqual(scored["brier"], 0.08, places=5)

    def test_roster_probe_reflex_unavailable(self):
        st = probe_candidate("reflex")
        self.assertEqual(st.status, "unavailable")
        self.assertIn("browser", (st.reason or "").lower())

    def test_roster_system_one_noncommercial(self):
        st = probe_candidate("system_one_4b")
        self.assertFalse(st.commercial_use)

    def test_run_bench_with_mock_factory(self):
        examples = load_fixtures()
        gold_map = {e.id: e.gold for e in examples}

        def factory(_cid: str):
            return GoldMockBackend(gold_map)

        def always_available(cid: str):
            from z0int.backends.bench.roster import CandidateStatus

            return CandidateStatus(
                candidate_id=cid,
                status="available",
                reason=None,
                backend_impl="gold_mock",
                commercial_use=True,
                platforms=("test",),
                license=None,
                optional=False,
                family="decision_backend",
            )

        with tempfile.TemporaryDirectory() as tmp:
            import z0int.backends.bench.roster as roster_mod

            old_probe = roster_mod.probe_candidate
            roster_mod.probe_candidate = always_available
            try:
                out = run_bench(
                    contract=BENCH_CONTRACT,
                    backend_filter="nanojev_06b",
                    output_dir=Path(tmp),
                    backend_factory=factory,
                )
            finally:
                roster_mod.probe_candidate = old_probe

            self.assertTrue(out["ok"])
            self.assertTrue(out["parity_ok"], msg=out.get("parity_errors"))
            self.assertTrue(Path(out["tokenomics_events"]).is_file())
            raw = Path(out["raw_jsonl"]).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(raw), len(examples))
            row = json.loads(raw[0])
            self.assertEqual(row["status"], "ok")
            self.assertTrue(row["verified_correct"])
            summary = json.loads(Path(out["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["contract"], BENCH_CONTRACT)
            self.assertTrue(Path(out["pareto_md"]).is_file())

    def test_pareto_dominance_requires_eligibility(self):
        examples = load_fixtures()
        a = enrich_backend_summary(
            {
                "candidate_id": "fast",
                "commercial_use": True,
                "vram_mb_peak": 1000,
                "by_capability": {
                    "rlm.worker_needed": {
                        "verified_accuracy": 0.9,
                        "latency_ms_p50": 10,
                        "mean_brier": 0.1,
                        "dangerous_false_rate": 0.0,
                        "denominator": 50,
                    }
                },
            },
            examples=examples,
            capabilities=["rlm.worker_needed"],
            validated_min=50,
        )
        b = enrich_backend_summary(
            {
                "candidate_id": "slow",
                "commercial_use": True,
                "vram_mb_peak": 8000,
                "by_capability": {
                    "rlm.worker_needed": {
                        "verified_accuracy": 0.85,
                        "latency_ms_p50": 100,
                        "mean_brier": 0.12,
                        "dangerous_false_rate": 0.0,
                        "denominator": 50,
                    }
                },
            },
            examples=examples,
            capabilities=["rlm.worker_needed"],
            validated_min=50,
        )
        self.assertTrue(a["by_capability"]["rlm.worker_needed"]["pareto_eligible"])
        self.assertTrue(dominates(a, b, "rlm.worker_needed"))
        frontier = pareto_frontier([a, b], "rlm.worker_needed")
        self.assertIn("fast", frontier)

    def test_unsafe_backend_excluded_from_pareto(self):
        examples = load_fixtures()
        safe = enrich_backend_summary(
            {
                "candidate_id": "safe",
                "commercial_use": True,
                "vram_mb_peak": 3000,
                "by_capability": {
                    "retry_or_escalate": {
                        "verified_accuracy": 0.5,
                        "latency_ms_p50": 50,
                        "mean_brier": 0.2,
                        "dangerous_false_rate": 0.0,
                        "denominator": 2,
                    }
                },
            },
            examples=examples,
            capabilities=["retry_or_escalate"],
        )
        unsafe = enrich_backend_summary(
            {
                "candidate_id": "unsafe",
                "commercial_use": True,
                "vram_mb_peak": 100,
                "by_capability": {
                    "retry_or_escalate": {
                        "verified_accuracy": 1.0,
                        "latency_ms_p50": 8,
                        "mean_brier": 0.05,
                        "dangerous_false_rate": 0.5,
                        "denominator": 2,
                    }
                },
            },
            examples=examples,
            capabilities=["retry_or_escalate"],
        )
        frontier = pareto_frontier([safe, unsafe], "retry_or_escalate")
        self.assertEqual(frontier, [])
        report = build_pareto_report(
            contract=BENCH_CONTRACT,
            capabilities=["retry_or_escalate"],
            backend_summaries=[safe, unsafe],
            examples=examples,
        )
        block = report["by_capability"]["retry_or_escalate"]
        self.assertIn("unsafe", block["excluded_unsafe"])
        self.assertNotIn("unsafe", block["pareto_optimal"])


if __name__ == "__main__":
    unittest.main()
