"""Unit tests for Tokenomics bench bridge and materialize-only persistence."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from z0int.backends.bench.contract import BENCH_CONTRACT
from z0int.backends.bench.fixtures import load_fixtures
from z0int.backends.bench.materialize import (
    SEMANTIC_FIELDS,
    compare_rows,
    load_materialized_rows,
    materialize_rows,
    materialize_trace,
)
from z0int.backends.bench.runner import run_bench, run_candidate
from z0int.backends.bench.tokenomics_bridge import (
    BenchTokenomicsSession,
    bench_treatment_hash,
    dataset_hash,
    pair_id,
    task_snapshot_id,
)


def _always_available(cid: str):
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


def _unavailable(cid: str):
    from z0int.backends.bench.roster import CandidateStatus

    return CandidateStatus(
        candidate_id=cid,
        status="unavailable",
        reason="checkpoint_missing",
        backend_impl="missing",
        commercial_use=None,
        platforms=(),
        license=None,
        optional=True,
        family="decision_backend",
    )


class TokenomicsBridgeTests(unittest.TestCase):
    def test_stable_ids(self):
        fixtures_path = (
            Path(__file__).resolve().parents[1]
            / "benchmarks"
            / "fixtures"
            / "decision-capability-v1"
            / "examples.jsonl"
        )
        dhash = dataset_hash(fixtures_path)
        self.assertEqual(len(dhash), 64)
        examples = load_fixtures(fixtures_path)
        snap_a = task_snapshot_id(examples[0])
        snap_b = task_snapshot_id(examples[0])
        self.assertEqual(snap_a, snap_b)
        self.assertEqual(pair_id("fixture", seed=3), "fixture:seed=3")
        th = bench_treatment_hash(
            backend_id="laya_421m",
            model_revision="rev",
            device="cpu",
            contract=BENCH_CONTRACT,
            dataset_sha=dhash,
            backend_impl="laya",
        )
        self.assertEqual(len(th), 16)

    def test_golden_fixture_row_count(self):
        golden = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "tokenomics-bench-parity"
            / "four-way"
            / "raw.jsonl"
        )
        rows = [json.loads(line) for line in golden.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 44)

    def test_mock_bench_event_sourced(self):
        from tests.test_backend_bench import GoldMockBackend

        examples = load_fixtures()
        gold_map = {e.id: e.gold for e in examples}

        def factory(_cid: str):
            return GoldMockBackend(gold_map)

        with tempfile.TemporaryDirectory() as tmp:
            import z0int.backends.bench.runner as runner_mod
            import z0int.backends.bench.roster as roster_mod

            old_probe_r = runner_mod.probe_candidate
            old_probe_s = roster_mod.probe_candidate
            runner_mod.probe_candidate = _always_available
            roster_mod.probe_candidate = _always_available
            try:
                out = run_bench(
                    contract=BENCH_CONTRACT,
                    backend_filter="nanojev_06b",
                    output_dir=Path(tmp),
                    backend_factory=factory,
                    seed=0,
                )
            finally:
                runner_mod.probe_candidate = old_probe_r
                roster_mod.probe_candidate = old_probe_s

            self.assertTrue(out["ok"])
            self.assertTrue(out["event_sourced"])
            self.assertTrue(Path(out["tokenomics_events"]).is_file())
            materialized = load_materialized_rows(out["tokenomics_events"])
            raw_rows = [
                json.loads(line)
                for line in Path(out["raw_jsonl"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(materialized), len(examples))
            # result payloads may differ only by JSON key order after event round-trip
            errs = compare_rows(raw_rows, materialized)
            self.assertEqual(errs, [], msg=errs[:10])
            summary = json.loads(Path(out["summary_json"]).read_text(encoding="utf-8"))
            self.assertTrue(summary["measurement"]["event_sourced"])
            self.assertFalse(summary["measurement"]["dual_write"])
            self.assertTrue(Path(out["run_manifest"]).is_file())
            self.assertTrue((Path(tmp) / "analytics.json").is_file())
            self.assertTrue((Path(tmp) / "coverage.json").is_file())

    def test_unavailable_row_derives_from_tokenomics(self):
        examples = load_fixtures()[:2]
        with tempfile.TemporaryDirectory() as tmp:
            import z0int.backends.bench.runner as runner_mod

            old_probe = runner_mod.probe_candidate
            runner_mod.probe_candidate = _unavailable
            try:
                session = BenchTokenomicsSession.open(
                    run_id="test-unavail",
                    contract=BENCH_CONTRACT,
                    fixtures_path=(
                        Path(__file__).resolve().parents[1]
                        / "benchmarks"
                        / "fixtures"
                        / "decision-capability-v1"
                        / "examples.jsonl"
                    ),
                    seed=0,
                    candidates=["nanojev_06b"],
                    events_path=Path(tmp) / "events.jsonl",
                    repo_root=Path(__file__).resolve().parents[1],
                )
                rows, summary = run_candidate(
                    "nanojev_06b",
                    examples,
                    tm_session=session,
                )
            finally:
                runner_mod.probe_candidate = old_probe

            self.assertEqual(summary["status"], "unavailable")
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["status"], "unavailable")
                self.assertEqual(row["reason"], "checkpoint_missing")
            rematerialized = materialize_rows(session.memory.events)
            self.assertEqual(rows, rematerialized)

    def test_error_row_derives_from_tokenomics(self):
        from z0int.backends.base import DecisionBackend, DecisionResult

        class BoomBackend(DecisionBackend):
            def health(self, *, load: bool = False):
                return {"ok": True}

            def evaluate(self, request):
                raise RuntimeError("inference exploded")

        examples = load_fixtures()[:1]
        with tempfile.TemporaryDirectory() as tmp:
            import z0int.backends.bench.runner as runner_mod

            old_probe = runner_mod.probe_candidate
            runner_mod.probe_candidate = _always_available
            try:
                session = BenchTokenomicsSession.open(
                    run_id="test-error",
                    contract=BENCH_CONTRACT,
                    fixtures_path=(
                        Path(__file__).resolve().parents[1]
                        / "benchmarks"
                        / "fixtures"
                        / "decision-capability-v1"
                        / "examples.jsonl"
                    ),
                    seed=0,
                    candidates=["nanojev_06b"],
                    events_path=Path(tmp) / "events.jsonl",
                    repo_root=Path(__file__).resolve().parents[1],
                )
                rows, _summary = run_candidate(
                    "nanojev_06b",
                    examples,
                    tm_session=session,
                    backend_factory=lambda _cid: BoomBackend(),
                )
            finally:
                runner_mod.probe_candidate = old_probe

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "error")
            self.assertIn("RuntimeError", rows[0]["reason"])
            self.assertIn("inference exploded", rows[0]["reason"])
            rematerialized = materialize_rows(session.memory.events)
            self.assertEqual(rows, rematerialized)

    def test_repeated_materialization_deterministic(self):
        live = (
            Path(__file__).resolve().parents[1]
            / "results"
            / "decision-backends"
            / "20260919T023249Z"
            / "tokenomics-events.jsonl"
        )
        if not live.is_file():
            self.skipTest("live tokenomics events fixture not present")
        a = load_materialized_rows(live)
        b = load_materialized_rows(live)
        self.assertEqual(a, b)
        self.assertEqual(compare_rows(a, b), [])

    def test_golden_semantic_parity_from_live_events(self):
        golden = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "tokenomics-bench-parity"
            / "four-way"
            / "raw.jsonl"
        )
        live = Path(__file__).resolve().parents[1] / "results" / "decision-backends" / "20260919T023249Z"
        events = live / "tokenomics-events.jsonl"
        if not events.is_file():
            self.skipTest("live tokenomics events not present")
        old_rows = [json.loads(line) for line in golden.read_text(encoding="utf-8").splitlines() if line.strip()]
        new_rows = load_materialized_rows(events)
        errs = compare_rows(old_rows, new_rows, fields=SEMANTIC_FIELDS, float_tol=1e-3)
        self.assertEqual(errs, [], msg=errs[:10])

    def test_runner_has_no_inline_row_builder(self):
        """Guardrail: runner must not hand-build analytics row dicts."""
        src = Path(__file__).resolve().parents[1] / "src" / "z0int" / "backends" / "bench" / "runner.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        forbidden = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value == "schema":
                        # allow only string-literal schema assignments that are NOT the row schema
                        vals = [v for v in node.values]
                        # find corresponding value for this key
                        idx = node.keys.index(key)
                        val = node.values[idx]
                        if isinstance(val, ast.Constant) and val.value == "z0int.backends_bench.row.v1":
                            forbidden += 1
        self.assertEqual(
            forbidden,
            0,
            "runner.py must not construct z0int.backends_bench.row.v1 dicts inline",
        )


if __name__ == "__main__":
    unittest.main()
