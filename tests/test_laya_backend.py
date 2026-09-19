"""Tests for Laya DecisionBackend adapter."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from z0int.backends.base import DecisionOption, DecisionQuestion, DecisionRequest
from z0int.backends.laya import LayaBackend, _answer_from_laya, _question_to_laya


class LayaMappingTests(unittest.TestCase):
    def test_choice_mapping_roundtrip(self):
        q = DecisionQuestion(
            id="decision",
            type="choice",
            instructions="pick one",
            options=(
                DecisionOption("a", "A"),
                DecisionOption("b", "B"),
            ),
        )
        lq = _question_to_laya(q)
        self.assertEqual(lq["type"], "choice")
        self.assertEqual(set(lq["criteria"].keys()), {"a", "b"})
        ans = _answer_from_laya(
            q,
            {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": 0.7, "b": 0.3},
                "confidence": 0.4,
            },
        )
        self.assertEqual(ans.value, "a")
        self.assertAlmostEqual(sum(ans.probabilities.values()), 1.0, places=4)

    def test_boolean_mapping_uses_noul(self):
        q = DecisionQuestion(
            id="decision",
            type="boolean",
            instructions="verify?",
            false_criterion="no verify",
            true_criterion="verify",
        )
        lq = _question_to_laya(q)
        self.assertEqual(lq["type"], "noul")
        ans = _answer_from_laya(q, {"type": "noul", "noul": 0.8, "confidence": 0.6})
        self.assertTrue(ans.value)
        self.assertAlmostEqual(ans.probabilities["true"], 0.8)


class LayaBackendTests(unittest.TestCase):
    def test_unavailable_without_weights(self):
        backend = LayaBackend(
            model_id="laya_421m",
            hf="convaiinnovations/laya",
            revision="7c76b622dfc5cac71b2dc1c29873efe2ce509a05",
            model_dir=Path("/nonexistent/laya"),
        )
        with mock.patch("z0int.backends.laya._laya_import_error", return_value=None):
            health = backend.health(load=False)
        self.assertFalse(health.ready)
        self.assertIn("not cached", health.detail)

    def test_evaluate_with_mock_agent(self):
        backend = LayaBackend(
            model_id="laya_421m",
            hf="convaiinnovations/laya",
            revision="7c76b622dfc5cac71b2dc1c29873efe2ce509a05",
            model_dir=Path("/tmp/laya-mock"),
        )
        fake_agent = mock.Mock()
        fake_agent.device = "cpu"
        fake_agent.predict.return_value = {
            "answers": {
                "decision": {
                    "type": "choice",
                    "choice": "native",
                    "probabilities": {"native": 0.6, "worker": 0.4},
                    "confidence": 0.2,
                }
            },
            "usage": {"input_tokens": 42, "output_tokens": 0},
        }
        backend._loaded = type("L", (), {"agent": fake_agent, "model_dir": "/tmp/laya-mock", "load_ms": 1.0})()
        req = DecisionRequest(
            state={"x": 1},
            questions=(
                DecisionQuestion(
                    id="decision",
                    type="choice",
                    instructions="pick",
                    options=(
                        DecisionOption("native", "native"),
                        DecisionOption("worker", "worker"),
                    ),
                ),
            ),
            request_id="t1",
        )
        result = backend.evaluate(req)
        self.assertEqual(result.answers[0].value, "native")
        self.assertAlmostEqual(result.answers[0].probabilities["native"], 0.6)
        fake_agent.predict.assert_called_once()

    def test_invalid_option_count_surfaces_error(self):
        backend = LayaBackend(
            model_id="laya_421m",
            hf="convaiinnovations/laya",
            revision="7c76b622dfc5cac71b2dc1c29873efe2ce509a05",
            model_dir=Path("/tmp/laya-mock"),
        )
        fake_agent = mock.Mock()
        fake_agent.device = "cpu"
        fake_agent.predict.side_effect = ValueError("question 'decision' options exceed head_max_len=192")
        backend._loaded = type("L", (), {"agent": fake_agent, "model_dir": "/tmp/laya-mock", "load_ms": 1.0})()
        req = DecisionRequest(
            state={"x": 1},
            questions=(
                DecisionQuestion(
                    id="decision",
                    type="choice",
                    instructions="pick",
                    options=tuple(DecisionOption(f"o{i}", f"O{i}") for i in range(20)),
                ),
            ),
        )
        with self.assertRaises(ValueError):
            backend.evaluate(req)


if __name__ == "__main__":
    unittest.main()
