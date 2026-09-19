"""Unit tests for Tokenomics bench bridge and materialize parity."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from z0int.backends.bench.fixtures import load_fixtures
from z0int.backends.bench.materialize import compare_rows, load_materialized_rows, materialize_rows
from z0int.backends.bench.runner import run_bench
from z0int.backends.bench.tokenomics_bridge import (
    bench_treatment_hash,
    dataset_hash,
    pair_id,
    task_snapshot_id,
)
from z0int.backends.bench.contract import BENCH_CONTRACT


class TokenomicsBridgeTests(unittest.TestCase):
    def test_stable_ids(self):
        fixtures_path = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures" / "decision-capability-v1" / "examples.jsonl"
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
        golden = Path(__file__).resolve().parent / "fixtures" / "tokenomics-bench-parity" / "four-way" / "raw.jsonl"
        rows = [json.loads(line) for line in golden.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 44)

    def test_mock_bench_tokenomics_parity(self):
        from tests.test_backend_bench import GoldMockBackend

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
                    seed=0,
                )
            finally:
                roster_mod.probe_candidate = old_probe

            self.assertTrue(out["parity_ok"], msg=out.get("parity_errors"))
            events_path = Path(out["tokenomics_events"])
            self.assertTrue(events_path.is_file())
            materialized = load_materialized_rows(events_path)
            self.assertEqual(len(materialized), len(examples))
            summary = json.loads(Path(out["summary_json"]).read_text(encoding="utf-8"))
            self.assertTrue(summary["measurement"]["parity_ok"])
            self.assertTrue(Path(out["run_manifest"]).is_file())
            self.assertTrue((Path(tmp) / "analytics.json").is_file())
            self.assertTrue((Path(tmp) / "coverage.json").is_file())


if __name__ == "__main__":
    unittest.main()
