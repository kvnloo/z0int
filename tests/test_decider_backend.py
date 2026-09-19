"""Tests for Decider DecisionBackend adapter."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from z0int.backends.base import DecisionOption, DecisionQuestion, DecisionRequest
from z0int.backends.decider import (
    DeciderBackend,
    _answer_from_decider,
    _normalize_probs,
    _question_to_decider,
)


class DeciderMappingTests(unittest.TestCase):
    def test_choice_mapping(self):
        q = DecisionQuestion(
            id="decision",
            type="choice",
            instructions="pick one",
            options=(DecisionOption("a", "A"), DecisionOption("b", "B")),
        )
        dq = _question_to_decider(q)
        self.assertEqual(dq["type"], "choice")
        self.assertEqual(set(dq["criteria"].keys()), {"a", "b"})

    def test_probability_normalization(self):
        probs = _normalize_probs({"a": 0.3333, "b": 0.3333, "c": 0.3333})
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=5)

    def test_choice_answer_roundtrip(self):
        q = DecisionQuestion(
            id="decision",
            type="choice",
            instructions="pick",
            options=(DecisionOption("native", "native"), DecisionOption("worker", "worker")),
        )
        ans = _answer_from_decider(
            q,
            {
                "type": "choice",
                "choice": "native",
                "probabilities": {"native": 0.6, "worker": 0.3999},
                "confidence": 0.6,
            },
        )
        self.assertEqual(ans.value, "native")
        self.assertAlmostEqual(sum(ans.probabilities.values()), 1.0, places=5)


class DeciderBackendTests(unittest.TestCase):
    def test_unavailable_without_weights(self):
        backend = DeciderBackend(
            model_id="decider_2b",
            hf="Mapika/decider-2b",
            revision="1d96be0093133e194fe18105a521b3e69be931d2",
            model_dir=Path("/nonexistent/decider"),
        )
        with mock.patch("z0int.backends.decider._runtime_import_error", return_value=None):
            health = backend.health(load=False)
        self.assertFalse(health.ready)

    def test_evaluate_with_mock_decider(self):
        backend = DeciderBackend(
            model_id="decider_2b",
            hf="Mapika/decider-2b",
            revision="1d96be0093133e194fe18105a521b3e69be931d2",
            model_dir=Path("/tmp/decider-mock"),
        )
        fake = mock.Mock()
        fake.dev = "cuda"
        fake.system_one.return_value = {
            "model": "decider-v8",
            "answers": {
                "decision": {
                    "type": "choice",
                    "choice": "native",
                    "probabilities": {"native": 0.7, "worker": 0.3},
                    "confidence": 0.7,
                }
            },
            "usage": {"input_tokens": 55, "output_tokens": 0},
        }
        backend._loaded = type("L", (), {"decider": fake, "model_dir": "/tmp/decider-mock", "load_ms": 2.0})()
        req = DecisionRequest(
            state={"x": 1},
            questions=(
                DecisionQuestion(
                    id="decision",
                    type="choice",
                    instructions="pick",
                    options=(DecisionOption("native", "native"), DecisionOption("worker", "worker")),
                ),
            ),
        )
        result = backend.evaluate(req)
        self.assertEqual(result.answers[0].value, "native")
        fake.system_one.assert_called_once()

    def test_runtime_error_surfaces_without_fallback(self):
        backend = DeciderBackend(
            model_id="decider_2b",
            hf="Mapika/decider-2b",
            revision="1d96be0093133e194fe18105a521b3e69be931d2",
            model_dir=Path("/tmp/decider-mock"),
        )
        fake = mock.Mock()
        fake.dev = "cuda"
        fake.system_one.side_effect = RuntimeError("CUDA out of memory")
        backend._loaded = type("L", (), {"decider": fake, "model_dir": "/tmp/decider-mock", "load_ms": 2.0})()
        req = DecisionRequest(
            state={"x": 1},
            questions=(
                DecisionQuestion(
                    id="decision",
                    type="choice",
                    instructions="pick",
                    options=(DecisionOption("a", "A"), DecisionOption("b", "B")),
                ),
            ),
        )
        with self.assertRaises(RuntimeError):
            backend.evaluate(req)

    def test_invalid_probability_mass_raises(self):
        with self.assertRaises(ValueError):
            _normalize_probs({"a": 0.0, "b": 0.0})


if __name__ == "__main__":
    unittest.main()
