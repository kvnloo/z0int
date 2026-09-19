"""Tests for OpenJev direct-logit DecisionBackend adapter."""

from __future__ import annotations

import unittest
from unittest import mock

from z0int.backends.base import DecisionOption, DecisionQuestion, DecisionRequest
from z0int.backends.openjev_direct import OpenJevDirectBackend


class OpenJevMappingTests(unittest.TestCase):
    def test_choice_row_mapping(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )
        req = DecisionRequest(
            state={"event": "tests passed"},
            questions=(
                DecisionQuestion(
                    id="decision",
                    type="choice",
                    instructions="pick one",
                    options=(DecisionOption("native", "native path"), DecisionOption("worker", "worker path")),
                ),
            ),
        )
        row = backend._row_from_question(req, req.questions[0])
        self.assertEqual(row["id"], "decision")
        self.assertEqual(row["state"], {"event": "tests passed"})
        self.assertEqual([o["id"] for o in row["options"]], ["native", "worker"])

    def test_boolean_row_mapping(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )
        req = DecisionRequest(
            state={"x": 1},
            questions=(
                DecisionQuestion(
                    id="verify",
                    type="boolean",
                    instructions="Need verification?",
                    true_criterion="yes, verify again",
                    false_criterion="no, skip verification",
                ),
            ),
        )
        row = backend._row_from_question(req, req.questions[0])
        self.assertEqual([o["id"] for o in row["options"]], ["false", "true"])


class OpenJevBackendTests(unittest.TestCase):
    def test_unavailable_without_weights(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )
        with mock.patch("z0int.models_mgmt.model_present", return_value=False):
            health = backend.health(load=False)
        self.assertFalse(health.ready)
        self.assertIn("not cached", health.detail)

    def test_evaluate_with_mock_scorer(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )
        backend._loaded = type(
            "L",
            (),
            {"model": object(), "tokenizer": object(), "metadata": {"source": "mock"}},
        )()
        backend._direct_score = lambda model, tokenizer, row, metadata: {
            "option_ids": ["native", "worker"],
            "probabilities": [0.25, 0.75],
            "option_logits": [1.0, 2.5],
            "input_tokens": 42,
        }
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
        self.assertEqual(result.answers[0].value, "worker")
        self.assertAlmostEqual(result.answers[0].probabilities["worker"], 0.75)
        self.assertEqual(result.diagnostics["option_logits"]["decision"], [1.0, 2.5])

    def test_runtime_error_surfaces_without_fallback(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )
        backend._loaded = type(
            "L",
            (),
            {"model": object(), "tokenizer": object(), "metadata": {"source": "mock"}},
        )()

        def boom(*_args, **_kwargs):
            raise RuntimeError("CUDA out of memory")

        backend._direct_score = boom
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

    def test_malformed_scorer_output_propagates(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )
        backend._loaded = type(
            "L",
            (),
            {"model": object(), "tokenizer": object(), "metadata": {"source": "mock"}},
        )()
        backend._direct_score = lambda *_a, **_k: {
            "option_ids": ["a", "b"],
            "probabilities": [0.0, 0.0],
            "option_logits": [0.0, 0.0],
            "input_tokens": 1,
        }
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
        with self.assertRaises(ValueError):
            backend.evaluate(req)

    def test_load_failure_surfaces_without_fallback(self):
        backend = OpenJevDirectBackend(
            model_id="openjev_06b",
            hf="Qwen/Qwen3-0.6B",
            revision="c1899de289a04d12100db370d81485cdf75e47ca",
        )

        def fail_load(*_args, **_kwargs):
            raise RuntimeError("checkpoint did not load completely")

        with mock.patch("openjev_phase1.core.load_causal_model", side_effect=fail_load):
            with self.assertRaises(RuntimeError):
                backend._ensure_loaded()


if __name__ == "__main__":
    unittest.main()
