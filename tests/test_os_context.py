from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from z0int.os_context import (
    OPERATOR_FAMILIES,
    compile_episode,
    import_from_db,
    normalize_operator,
)
from z0int.specialists.next_operator import fit_recency_prior, predict, safe_coverage


class OperatorVocabTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_operator("switch_app"), "open_context")
        self.assertEqual(normalize_operator("noop"), "noop")
        self.assertEqual(normalize_operator("stay"), "noop")
        self.assertIn("inspect_result", OPERATOR_FAMILIES)

    def test_compile_rejects_open_episode(self):
        self.assertIsNone(compile_episode({"closed": 0, "state_before_json": "{}"}))

    def test_compile_separates_features_and_labels(self):
        ep = compile_episode(
            {
                "id": 1,
                "closed": 1,
                "context_id": "abc",
                "ts_before": 1.0,
                "ts_after": 2.0,
                "state_before_json": json.dumps({"app": "kitty", "project": "z0intelligence", "title": "SECRET"}),
                "state_after_json": json.dumps({"app": "zen"}),
                "action_family": "switch_app",
                "action_target": "zen",
            }
        )
        assert ep is not None
        self.assertEqual(ep["schema"], "os.context_episode.v0")
        self.assertEqual(ep["actual_operator"], "open_context")
        self.assertEqual(ep["state_before"]["app"], "kitty")
        self.assertNotIn("title", ep["state_before"])
        # label must not appear inside feature blob keys as actual_operator
        self.assertNotIn("actual_operator", ep["state_before"])


class ImportDbTests(unittest.TestCase):
    def test_import_from_temp_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "workspace.db"
            con = sqlite3.connect(db)
            con.execute(
                """CREATE TABLE context_episodes (
                id INTEGER PRIMARY KEY, context_id TEXT, open_event_id INT, close_event_id INT,
                ts_before REAL, ts_after REAL, state_before_json TEXT, action_family TEXT,
                action_target TEXT, state_after_json TEXT, horizon_ms REAL, closed INT
                )"""
            )
            con.execute(
                """CREATE TABLE shadow_predictions (
                id INTEGER PRIMARY KEY, pred_id TEXT, schema_name TEXT, ts REAL,
                trigger_event_id INT, context_id TEXT, state_json TEXT, topk_json TEXT,
                latency_ms REAL, actual_context_id TEXT, actual_family TEXT, actual_target TEXT,
                ranked INT, manual_equivalent INT, matched_at REAL, horizon_ms REAL,
                confidence REAL, margin REAL, entropy REAL, receipt_json TEXT
                )"""
            )
            con.execute(
                """CREATE TABLE prediction_horizons (
                id INTEGER PRIMARY KEY, pred_id TEXT, horizon_ms REAL, opened_at REAL, closed_at REAL,
                actual_family TEXT, actual_target TEXT, actual_context_id TEXT, ranked INT, manual_equivalent INT
                )"""
            )
            con.execute(
                """CREATE TABLE routine_candidates (
                fingerprint TEXT, created_at REAL, updated_at REAL, ngram_n INT, sequence_json TEXT,
                project TEXT, support INT, sessions INT, same_ratio REAL, median_duration_ms REAL,
                source_mix_json TEXT, existing_shortcut INT
                )"""
            )
            con.execute(
                "INSERT INTO context_episodes VALUES (1,'c1',1,2,1.0,2.0,?,?,?,?,NULL,1)",
                (json.dumps({"app": "kitty", "project": "p"}), "switch_app", "zen", json.dumps({"app": "zen"})),
            )
            con.commit()
            con.close()

            # point episodes dir via env
            import os
            from unittest import mock

            with mock.patch.dict(os.environ, {"Z0INT_HOME": tmp}):
                # paths.home uses Z0INT_HOME
                out = import_from_db(db_path=db, limit=10)
            self.assertTrue(out["ok"])
            self.assertEqual(out["episodes"], 1)
            self.assertEqual(out["operator_histogram"].get("open_context"), 1)


class NextOperatorShadowTests(unittest.TestCase):
    def test_safe_coverage_runs(self):
        eps = [
            {
                "state_before": {
                    "app": "kitty",
                    "project": "z0intelligence",
                    "harness_state": "completed",
                },
                "actual_operator": "inspect_result",
            },
            {
                "state_before": {
                    "app": "kitty",
                    "project": "z0intelligence",
                    "harness_state": "completed",
                },
                "actual_operator": "inspect_result",
            },
            {
                "state_before": {"app": "zen", "project": "other"},
                "actual_operator": "open_context",
            },
        ]
        model = fit_recency_prior(eps)
        pred = predict(
            {"app": "kitty", "project": "z0intelligence", "harness_state": "completed"},
            model,
        )
        self.assertEqual(pred["top1"], "inspect_result")
        self.assertEqual(pred["gate"], "PREDICT")
        cov = safe_coverage(eps, model, precision_floor=0.5, min_p=0.1)
        self.assertGreaterEqual(cov["n"], 3)
        self.assertIn("coverage", cov)
        self.assertEqual(cov["gate"], "PREDICT")


if __name__ == "__main__":
    unittest.main()
