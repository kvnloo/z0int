"""Resident DecisionBackend cache + bridge decision ops."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest import mock

from z0int.backends.base import (
    BackendCapabilities,
    BackendHealth,
    DecisionAnswer,
    DecisionOption,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
)
from z0int.bridge.decision_cache import BackendLoadState, ResidentDecisionCache
from z0int.bridge.runtime import BridgeRuntime


@dataclass
class FakeBackend:
    model_id: str = "fake"
    revision: str = "r1"
    device: str = "cpu"
    load_delay_s: float = 0.05
    fail_load: bool = False
    instance_tag: str = field(default_factory=lambda: f"inst-{time.time()}")
    evaluate_calls: int = 0
    health_load_calls: int = 0

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id="fake",
            kind="test",
            description="fake",
            supports_boolean=True,
            supports_choice=True,
            supports_score=True,
        )

    def health(self, *, load: bool = False) -> BackendHealth:
        if load:
            self.health_load_calls += 1
            if self.fail_load:
                return BackendHealth(
                    id="fake",
                    configured=True,
                    ready=True,
                    loaded=False,
                    detail="forced load failure",
                )
            time.sleep(self.load_delay_s)
            return BackendHealth(
                id="fake",
                configured=True,
                ready=True,
                loaded=True,
                model=self.model_id,
                detail="loaded",
                diagnostics={"device": self.device},
            )
        return BackendHealth(
            id="fake",
            configured=True,
            ready=True,
            loaded=False,
            model=self.model_id,
            detail="not loaded",
        )

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        self.evaluate_calls += 1
        q = request.questions[0]
        return DecisionResult(
            backend="fake",
            model=self.model_id,
            revision=self.revision,
            answers=(
                DecisionAnswer(
                    question_id=q.id,
                    type="choice",
                    value="worker",
                    confidence=0.9,
                    probabilities={"worker": 0.9, "native": 0.05, "abstain": 0.05},
                ),
            ),
            latency_ms=1.0,
            diagnostics={"instance_tag": self.instance_tag},
        )


def _req() -> DecisionRequest:
    return DecisionRequest(
        state={"granted_bytes": 100},
        questions=(
            DecisionQuestion(
                id="decision",
                type="choice",
                instructions="choose",
                options=(
                    DecisionOption(id="native", description="native"),
                    DecisionOption(id="worker", description="worker"),
                    DecisionOption(id="abstain", description="abstain"),
                ),
            ),
        ),
    )


class ResidentDecisionCacheTests(unittest.TestCase):
    def test_warmup_and_reuse_same_instance(self) -> None:
        cache = ResidentDecisionCache()
        fake = FakeBackend(instance_tag="A")
        with mock.patch("z0int.bridge.decision_cache._create_backend", return_value=fake):
            warm = cache.warm("decider_2b")
            self.assertEqual(warm["status"], "warming")
            # status must not load
            st = cache.status()
            self.assertIn("decider_2b", st)
            for _ in range(100):
                if cache.status()["decider_2b"]["state"] == "ready":
                    break
                time.sleep(0.01)
            self.assertEqual(cache.status()["decider_2b"]["state"], "ready")
            self.assertEqual(fake.health_load_calls, 1)

            r1 = cache.evaluate(backend_id="decider_2b", request=_req(), capability_id="rlm.worker_needed")
            r2 = cache.evaluate(backend_id="decider_2b", request=_req(), capability_id="rlm.worker_needed")
            self.assertTrue(r1["ok"])
            self.assertTrue(r2["ok"])
            self.assertEqual(fake.evaluate_calls, 3)  # 1 warmup + 2 live
            self.assertEqual(r1["result"]["diagnostics"]["instance_tag"], "A")
            self.assertEqual(r2["result"]["diagnostics"]["instance_tag"], "A")
            self.assertEqual(r1["runtime"]["residency"], "warm")

    def test_decision_while_warming_returns_quickly(self) -> None:
        cache = ResidentDecisionCache()
        fake = FakeBackend(load_delay_s=0.4)

        with mock.patch("z0int.bridge.decision_cache._create_backend", return_value=fake):
            cache.warm("decider_2b")
            t0 = time.perf_counter()
            out = cache.evaluate(backend_id="decider_2b", request=_req())
            elapsed = time.perf_counter() - t0
            self.assertFalse(out["ok"])
            self.assertEqual(out["status"], "warming")
            self.assertLess(elapsed, 0.2)

    def test_load_failure_is_deterministic(self) -> None:
        cache = ResidentDecisionCache()
        fake = FakeBackend(fail_load=True)
        with mock.patch("z0int.bridge.decision_cache._create_backend", return_value=fake):
            cache.warm("decider_2b")
            for _ in range(100):
                if cache.status()["decider_2b"]["state"] == "failed":
                    break
                time.sleep(0.01)
            self.assertEqual(cache.status()["decider_2b"]["state"], "failed")
            out = cache.evaluate(backend_id="decider_2b", request=_req())
            self.assertFalse(out["ok"])
            self.assertEqual(out["status"], "error")

    def test_status_does_not_trigger_load(self) -> None:
        cache = ResidentDecisionCache()
        fake = FakeBackend()
        with mock.patch("z0int.bridge.decision_cache._create_backend", return_value=fake) as m:
            # Touch slot via status after empty — still unloaded, no create.
            self.assertEqual(cache.status(), {})
            m.assert_not_called()
            cache._slot("decider_2b")
            self.assertEqual(cache.status()["decider_2b"]["state"], "unloaded")
            m.assert_not_called()
            self.assertEqual(fake.health_load_calls, 0)


class BridgeRuntimeDecisionTests(unittest.TestCase):
    def test_decision_op_parses_canonical_request(self) -> None:
        rt = BridgeRuntime(generation=1, instance_id="t", build_id="b")
        fake = FakeBackend(load_delay_s=0.0)
        with mock.patch("z0int.bridge.decision_cache._create_backend", return_value=fake):
            warm = rt.decision_warm(backend="decider_2b")
            self.assertTrue(warm.get("ok"))
            for _ in range(100):
                if rt.decision_status()["decision_backends"]["decider_2b"]["state"] == "ready":
                    break
                time.sleep(0.01)
            out = rt.decision(
                backend="decider_2b",
                capability_id="rlm.worker_needed",
                request_mapping={
                    "state": {
                        "granted_bytes": 512,
                        "pattern_hits": 2,
                        "complexity": "high",
                        "question_sha256": "abc",
                        "question_chars": 10,
                    },
                    "questions": [
                        {
                            "id": "decision",
                            "type": "choice",
                            "instructions": "Should RLM use worker?",
                            "options": [
                                {"id": "native", "description": "native"},
                                {"id": "worker", "description": "worker"},
                                {"id": "abstain", "description": "abstain"},
                            ],
                        }
                    ],
                },
            )
            self.assertTrue(out["ok"])
            self.assertEqual(out["result"]["answers"][0]["value"], "worker")
            # self_check / status do not load additional backends
            before = fake.health_load_calls
            check = rt.self_check()
            self.assertTrue(check["ok"])
            self.assertIn("decision_backends", check)
            self.assertEqual(fake.health_load_calls, before)

    def test_generation_owns_own_cache(self) -> None:
        a = BridgeRuntime(generation=1, instance_id="a", build_id="ba")
        b = BridgeRuntime(generation=2, instance_id="b", build_id="bb")
        self.assertIsNot(a._decision_backends, b._decision_backends)


if __name__ == "__main__":
    unittest.main()
