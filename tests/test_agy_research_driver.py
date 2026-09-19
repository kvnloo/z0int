"""Tests for agy ResearchDriver + ResearchProposalV1 (P0)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from z0int.autoresearch.research.convert import proposal_to_fly_candidate
from z0int.autoresearch.research.driver import AgyResearchDriver, DeterministicSearchDriver, get_driver
from z0int.autoresearch.research.job import create_research_job
from z0int.autoresearch.research.proposal import (
    ResearchProposalError,
    ResearchProposalV1,
    validate_proposal,
)
from z0int.autoresearch.resources import ResourceClass, can_run


SEARCH_SPACE = {
    "hidden": [32, 64, 96, 128, 160, 192, 256],
    "dagger_rounds": [0, 1, 2, 3],
    "plasticity_lr": [0.15, 0.25, 0.35, 0.45, 0.55],
    "plasticity_epochs": [10, 15, 20, 30, 40],
    "seed_delta": [-2, -1, 0, 1, 2],
    "k_winners": [5, 8, 10, 12, 15, 19],
}

CHAMPION_KNOBS = {
    "hidden": 128,
    "dagger_rounds": 0,
    "plasticity_lr": 0.35,
    "plasticity_epochs": 20,
    "k_winners": 0,
    "seed": 0,
}


def _valid(**overrides):
    base = dict(
        proposal_id="rp-test",
        hypothesis="Raising hidden to 160 reduces advise p99 under gates.",
        mechanism="Wider Kenyon layer increases capacity without changing history.",
        mutation_kind="parameter",
        target={"knob": "hidden", "value": 160},
        expected_metric="latency_score",
        expected_direction="minimize",
        expected_magnitude=0.05,
        invariants=["history locked at 8"],
        falsifiers=["hidden=160 fails closed_loop_reward>=1.0"],
        confidence=0.55,
    )
    base.update(overrides)
    return ResearchProposalV1.from_dict(base)


class ProposalSchemaTests(unittest.TestCase):
    def test_schema_valid(self):
        p = validate_proposal(_valid(), search_space=SEARCH_SPACE, champion_knobs=CHAMPION_KNOBS)
        self.assertEqual(p.mutation_kind, "parameter")
        self.assertEqual(p.target["knob"], "hidden")

    def test_outside_search_space(self):
        with self.assertRaises(ResearchProposalError):
            validate_proposal(
                _valid(target={"knob": "hidden", "value": 999}),
                search_space=SEARCH_SPACE,
                champion_knobs=CHAMPION_KNOBS,
            )

    def test_kernel_impl_rejected(self):
        with self.assertRaises(ResearchProposalError):
            ResearchProposalV1.from_dict(
                {
                    **_valid().to_dict(),
                    "mutation_kind": "kernel_impl",
                }
            )

    def test_judge_mutation_rejected(self):
        with self.assertRaises(ResearchProposalError):
            validate_proposal(
                _valid(hypothesis="We should edit bench.py to relax gates"),
                search_space=SEARCH_SPACE,
                champion_knobs=CHAMPION_KNOBS,
            )

    def test_seed_delta_space(self):
        p = validate_proposal(
            _valid(target={"knob": "seed", "value": 1}),
            search_space=SEARCH_SPACE,
            champion_knobs=CHAMPION_KNOBS,
        )
        self.assertEqual(p.target["value"], 1)
        with self.assertRaises(ResearchProposalError):
            validate_proposal(
                _valid(target={"knob": "seed", "value": 99}),
                search_space=SEARCH_SPACE,
                champion_knobs=CHAMPION_KNOBS,
            )


class DriverTests(unittest.TestCase):
    def test_agy_unavailable(self):
        d = AgyResearchDriver(binary="/nonexistent/agy-binary-xyz")
        with tempfile.TemporaryDirectory() as td:
            job = create_research_job(
                root=Path(td),
                objective="t",
                champion={"candidate": {"genome_id": "x", "genome": {"architecture": {"hidden": 128, "history": 8}, "training": {"seed": 0}}}},
                measurement_gaps=[],
                world={},
                search_space=SEARCH_SPACE,
                product_target={},
                objective_weights={},
            )
            r = d.propose(job, search_space=SEARCH_SPACE, champion_knobs=CHAMPION_KNOBS)
            self.assertEqual(r.status, "unavailable")

    def test_agy_timeout(self):
        d = AgyResearchDriver(binary="agy")
        with tempfile.TemporaryDirectory() as td:
            job = create_research_job(
                root=Path(td),
                objective="t",
                champion={"status": "seed"},
                measurement_gaps=[],
                world={},
                search_space=SEARCH_SPACE,
                product_target={},
                objective_weights={},
            )
            with mock.patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired(cmd=["agy"], timeout=1)):
                r = d.propose(job, search_space=SEARCH_SPACE, champion_knobs=CHAMPION_KNOBS, timeout_s=1)
            self.assertEqual(r.status, "timeout")

    def test_malformed_json(self):
        d = AgyResearchDriver(binary="agy")
        with tempfile.TemporaryDirectory() as td:
            job = create_research_job(
                root=Path(td),
                objective="t",
                champion={"status": "seed"},
                measurement_gaps=[],
                world={},
                search_space=SEARCH_SPACE,
                product_target={},
                objective_weights={},
            )
            proc = mock.Mock(returncode=0, stdout="not-json{{{", stderr="")
            with mock.patch("subprocess.run", return_value=proc):
                with mock.patch.object(d, "available", return_value=True):
                    r = d.propose(job, search_space=SEARCH_SPACE, champion_knobs=CHAMPION_KNOBS)
            self.assertEqual(r.status, "malformed")

    def test_deterministic_still_works(self):
        el = Path(os.environ.get("EVOLUTION_LAB_ROOT") or "/home/kvn/tmp/evolution-lab-agy")
        if not (el / "evolution_lab" / "autoresearch_propose.py").is_file():
            self.skipTest("evolution-lab not present")
        d = DeterministicSearchDriver(evolution_lab_root=el)
        with tempfile.TemporaryDirectory() as td:
            # write a minimal champion matching FlyCandidate shape via default path
            job = create_research_job(
                root=Path(td),
                objective="t",
                champion={},
                measurement_gaps=[],
                world={},
                search_space=SEARCH_SPACE,
                product_target={},
                objective_weights={},
            )
            r = d.propose(job, search_space=SEARCH_SPACE, champion_knobs=CHAMPION_KNOBS)
            self.assertEqual(r.status, "ok", r.error)
            self.assertIsNotNone(r.proposal)
            self.assertEqual(r.proposal.mutation_kind, "parameter")

    def test_get_driver(self):
        self.assertEqual(get_driver("agy").name, "agy")
        self.assertEqual(get_driver("deterministic").name, "deterministic")


class ConvertTests(unittest.TestCase):
    def test_convert_parameter(self):
        el = Path(os.environ.get("EVOLUTION_LAB_ROOT") or "/home/kvn/tmp/evolution-lab-agy")
        if not (el / "evolution_lab").is_dir():
            self.skipTest("evolution-lab missing")
        p = validate_proposal(_valid(), search_space=SEARCH_SPACE, champion_knobs=CHAMPION_KNOBS)
        fly = proposal_to_fly_candidate(p, evolution_lab_root=el)
        self.assertEqual(fly.genome["architecture"]["hidden"], 160)
        self.assertEqual(fly.genome["architecture"]["history"], 8)


class ResourceGovernorTests(unittest.TestCase):
    def test_remote_research_proceeds_while_gpu_would_pause(self):
        with mock.patch("z0int.autoresearch.resources._gpu_stats", return_value=(90.0, 100.0)):
            with mock.patch("z0int.autoresearch.resources.interactive_recent", return_value=True):
                with mock.patch("z0int.autoresearch.resources._load_avg_ratio", return_value=0.1):
                    remote = can_run(ResourceClass.RESEARCH_REMOTE)
                    gpu = can_run(ResourceClass.GPU_BENCHMARK)
        self.assertFalse(remote["pause"], remote)
        self.assertTrue(gpu["pause"], gpu)
        self.assertIn("interactive_traffic", gpu["reasons"])

    def test_env_kill_switch_pauses_research(self):
        with mock.patch.dict(os.environ, {"Z0INT_PAUSE_RESEARCH": "1"}):
            remote = can_run(ResourceClass.RESEARCH_REMOTE)
        self.assertTrue(remote["pause"])


class WorktreeIsolationTests(unittest.TestCase):
    def test_pipeline_refuses_active_omp_worktree(self):
        from z0int.autoresearch.research.pipeline import run_research_once

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"OMP_WORKTREE": td, "EVOLUTION_LAB_ROOT": td}):
                with self.assertRaises(RuntimeError):
                    run_research_once(driver_name="deterministic", evolution_lab_root=Path(td), force_resources=True)


if __name__ == "__main__":
    unittest.main()
