from __future__ import annotations

import unittest

from adapters.hermes_z0int import close_observation, join_outcome, normalize_envelope


class HermesAdapterTests(unittest.TestCase):
    def test_normalize_sets_hermes_identity(self):
        env = normalize_envelope(
            {
                "session_id": "s1",
                "turn_id": "t9",
                "text": "hello",
                "capability_id": "coding.edit",
            },
            build_id="test",
        )
        self.assertEqual(env["schema"], "z0int.harness_envelope.v1")
        self.assertEqual(env["identity"]["harness_id"], "hermes")
        self.assertEqual(env["identity"]["session_id"], "s1")
        self.assertEqual(env["identity"]["turn_id"], "t9")
        self.assertNotIn("omp_session_id", env["identity"])

    def test_close_keeps_verified_null(self):
        env = normalize_envelope({"session_id": "s", "text": "x"})
        obs = close_observation(env, execution_completed=True, verified_success=None)
        self.assertTrue(obs["execution_completed"])
        self.assertIsNone(obs["verified_success"])
        self.assertEqual(obs["schema"], "z0int.allocation_observation.v1")

    def test_join_outcome_does_not_invent_success(self):
        env = normalize_envelope({"session_id": "s", "text": "x"})
        obs = close_observation(env, execution_completed=True, verified_success=None)
        joined = join_outcome(obs)
        self.assertIsNone(joined["verified_success"])
        joined2 = join_outcome(obs, gold_verified=True)
        self.assertTrue(joined2["verified_success"])

    def test_isolation_fields_differ_per_session(self):
        a = normalize_envelope({"session_id": "A", "text": "1"})
        b = normalize_envelope({"session_id": "B", "text": "2"})
        self.assertNotEqual(a["identity"]["session_id"], b["identity"]["session_id"])


if __name__ == "__main__":
    unittest.main()
