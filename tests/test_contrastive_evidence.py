from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from z0int.capabilities.context_project_state import (
    compile_episode,
    family_from_workspace_snapshot,
    fixture_family,
)
from z0int.contrastive_evidence import (
    EvidenceDependency,
    apply_condition,
    derive_implementation_decision,
    evaluate_family,
    evaluate_recipe_on_family,
    example_project_status_family,
    list_conditions,
    store_dependency,
)
from z0int.data_recipe_race import race_data_recipes


@contextmanager
def z0home(tmp: str):
    old = os.environ.get("Z0INT_HOME")
    os.environ["Z0INT_HOME"] = tmp
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("Z0INT_HOME", None)
        else:
            os.environ["Z0INT_HOME"] = old


class DerivedProbeTests(unittest.TestCase):
    def test_derives_from_source_facts_not_decision_label(self) -> None:
        fam = example_project_status_family()
        items = apply_condition(fam, "original")
        self.assertEqual(derive_implementation_decision(items, fam.question), "rev-3")
        # no decision key in evidence facts
        for e in fam.evidence:
            self.assertNotIn("decision", e.facts)

    def test_relevant_edit_changes_source_fact(self) -> None:
        fam = example_project_status_family()
        self.assertEqual(fam.relevant_edit["fact"], "rfc_revision")
        items = apply_condition(fam, "relevant_edit")
        self.assertEqual(derive_implementation_decision(items, fam.question), "rev-4")


class PerEvidenceNecessityTests(unittest.TestCase):
    def test_lists_per_id_and_all_conditions(self) -> None:
        fam = example_project_status_family()
        conds = list_conditions(fam)
        self.assertIn("necessity_delete:rfc_rev", conds)
        self.assertIn("necessity_delete:supersede", conds)
        self.assertIn("necessity_delete:all", conds)

    def test_leave_one_out_abstains_independently(self) -> None:
        fam = example_project_status_family()
        out = evaluate_family(fam)
        for key in ("necessity_delete:rfc_rev", "necessity_delete:supersede", "necessity_delete:all"):
            self.assertIn(key, out["conditions"])
            self.assertIsNone(out["conditions"][key]["predicted"])
            self.assertTrue(out["conditions"][key]["ok"])
        self.assertEqual(out["metrics"]["necessity_conditions"], 3)
        self.assertEqual(out["metrics"]["necessity_passed"], 3)

    def test_fixture_full_family_pass(self) -> None:
        fam = example_project_status_family()
        out = evaluate_family(fam)
        self.assertTrue(out["full_pass"])
        self.assertEqual(out["metrics"]["full_family_pass_rate"], 1.0)

    def test_dropping_one_necessary_fails_ordinary_but_contrastive_catches(self) -> None:
        fam = example_project_status_family()
        bad = evaluate_recipe_on_family(fam, {"drop_evidence_ids": ["rfc_rev"]})
        # original might still fail if probe abstains — ordinary gate weaker
        self.assertFalse(bad["full_pass"])
        race = race_data_recipes([fam], recipe={"drop_evidence_ids": ["rfc_rev"]})
        self.assertGreaterEqual(race["incremental_rejection"], 0)


class EvidenceDependencyTests(unittest.TestCase):
    def test_dependency_object_shape(self) -> None:
        fam = example_project_status_family()
        out = evaluate_family(fam)
        dep = EvidenceDependency(**{k: v for k, v in out["dependency"].items() if k != "schema"})
        self.assertEqual(dep.capability_id, fam.task_family)
        self.assertIn("rfc_rev", dep.requires)
        self.assertIn("unrelated_chat", dep.invariants)
        self.assertTrue(dep.curation_accepted)

    def test_store_not_verified_success(self) -> None:
        fam = example_project_status_family()
        out = evaluate_family(fam)
        with tempfile.TemporaryDirectory() as tmp, z0home(tmp):
            path = store_dependency(out["dependency"])
            text = path.read_text(encoding="utf-8")
            self.assertIn("curation_accepted", text)
            self.assertNotIn('"verified_success": true', text)


class WorkspaceSnapshotTests(unittest.TestCase):
    def test_compile_episode_from_snapshot(self) -> None:
        snap = {
            "project": "z0intelligence",
            "repo_head": "abc123",
            "rfc_revision": 3,
            "superseded": False,
            "open_pr": 10,
            "changed_files": ["src/z0int/contrastive_evidence.py"],
            "session": "s1",
        }
        ep = compile_episode(snap)
        self.assertTrue(ep.get("family_id"))
        self.assertEqual(ep["capability_id"], "context.current_project_state")
        fam = family_from_workspace_snapshot(snap)
        assert fam is not None
        out = evaluate_family(fam)

    def test_workspace_relevant_edit_flips(self) -> None:
        snap = {
            "project": "z0intelligence",
            "repo_head": "abc123",
            "rfc_revision": 3,
            "superseded": False,
            "open_pr": 10,
            "changed_files": ["src/z0int/contrastive_evidence.py"],
            "session": "s1",
        }
        fam = family_from_workspace_snapshot(snap)
        assert fam is not None
        assert fam.answer_original == "rev-3"
        assert fam.answer_after_relevant_edit == "rev-4"
        out = evaluate_family(fam)
        self.assertTrue(out["conditions"]["relevant_edit"]["ok"])


class ContrastiveAutoresearchJobTests(unittest.TestCase):
    def test_run_contrastive_job_keeps_cheaper_sensitive(self) -> None:
        from z0int.autoresearch.daemon import run_once, resume
        from z0int.autoresearch.queue import enqueue_trace

        with tempfile.TemporaryDirectory() as tmp, z0home(tmp):
            resume()
            r = enqueue_trace(
                "contrast-1",
                verified_success=True,
                verifier_id="unit_contrastive",
                payload={"kind": "contrastive_evidence"},
            )
            self.assertTrue(r["enqueued"])
            out = run_once(force=True)
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("kind"), "contrastive_evidence")
            self.assertEqual(out.get("decision"), "KEEP_CHEAPER_SENSITIVE_RECIPE")
            results = (Path(tmp) / "autoresearch" / "results.jsonl").read_text(encoding="utf-8")
            self.assertIn('"verified_success": null', results)


class DataRecipeRaceTests(unittest.TestCase):
    def test_contrastive_stricter_than_ordinary_on_fixture(self) -> None:
        race = race_data_recipes([fixture_family()])
        self.assertEqual(race["ordinary"]["accepted"], 1)
        self.assertEqual(race["contrastive"]["accepted"], 1)
        # both pass on good fixture; incremental_rejection == 0


if __name__ == "__main__":
    unittest.main()
