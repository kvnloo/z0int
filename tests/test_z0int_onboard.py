from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class PathsLayout(unittest.TestCase):
    def test_ensure_layout(self):
        from z0int.paths import ensure_layout

        with tempfile.TemporaryDirectory() as tmp:
            layout = ensure_layout(Path(tmp))
            self.assertTrue((Path(tmp) / "state").is_dir())
            self.assertTrue((Path(tmp) / "episodes").is_dir())
            self.assertEqual(layout["root"], Path(tmp).resolve())


class ModelsPlan(unittest.TestCase):
    def test_decision_roster_five_post_models(self):
        from z0int.models_mgmt import decision_roster

        roster = decision_roster()
        for mid in ("laya_421m", "decider_2b", "nanojev_06b", "reflex", "system_one_4b"):
            self.assertIn(mid, roster["candidates"])
            self.assertEqual(roster["entries"][mid]["family"], "decision_backend")
        self.assertFalse(roster["entries"]["system_one_4b"].get("commercial_use", True))
        self.assertEqual(roster["entries"]["reflex"]["type"], "browser_app")

    def test_plan_twelve_gb(self):
        from z0int.models_mgmt import plan_models

        plan = plan_models(vram_gb=12.0)
        self.assertEqual(plan["policy"], "twelve_gb")
        # NanoJev is the preferred resident semantic decision engine on 12GB;
        # openjev_06b remains available on_demand and must not coreside with nanojev.
        self.assertIn("nanojev_06b", plan["resident"])
        self.assertIn("local_mb", plan["resident"])
        self.assertNotIn("openjev_4b", plan["resident"])
        pairs = {tuple(x) for x in plan["never_coreside"]}
        self.assertIn(("nanojev_06b", "openjev_4b"), pairs)
        self.assertIn(("nanojev_06b", "openjev_06b"), pairs)

    def test_plan_cpu(self):
        from z0int import models_mgmt

        with mock.patch.object(models_mgmt, "detect_vram_gb", return_value=None):
            with mock.patch.object(models_mgmt, "detect_gpu_name", return_value=None):
                plan = models_mgmt.plan_models(vram_gb=None)
        # explicit None still re-detects inside plan_models — pass 0-sentinel via policy
        plan = models_mgmt.plan_models(vram_gb=0.0)
        self.assertEqual(plan["policy"], "cpu_only")
        self.assertIn("local_mb", plan["resident"])


class Doctor(unittest.TestCase):
    def test_doctor_json_shape(self):
        from z0int.doctor import run_doctor

        rep = run_doctor()
        d = rep.to_dict()
        self.assertEqual(d["schema"], "z0int.doctor.v1")
        self.assertIn("checks", d)
        self.assertIn("hardware", d)
        self.assertIn("models_plan", d)


class OnboardDryRun(unittest.TestCase):
    def test_dry_run_skip_el(self):
        from z0int.onboard import run_onboard
        from z0int import paths as paths_mod

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "z0"
            home.mkdir()
            with mock.patch.object(paths_mod, "home", return_value=home):
                # patch onboard module bindings
                import z0int.onboard as ob

                with mock.patch.object(ob.paths, "home", return_value=home):
                    with mock.patch.object(ob.paths, "ensure_layout", return_value={"root": home}):
                        with mock.patch.object(
                            ob.paths, "onboard_state_path", return_value=home / "state" / "onboard.json"
                        ):
                            with mock.patch.object(
                                ob.paths, "config_path", return_value=home / "config" / "z0int.json"
                            ):
                                (home / "state").mkdir(parents=True, exist_ok=True)
                                (home / "config").mkdir(parents=True, exist_ok=True)
                                (home / "sources").mkdir(parents=True, exist_ok=True)
                                report = run_onboard(
                                    dry_run=True,
                                    skip_evolution_lab=True,
                                    force=True,
                                )
        self.assertTrue(report["ok"], report)
        self.assertIn("layout", report["results"])
        self.assertIn("models.plan", report["results"])


class CliSmoke(unittest.TestCase):
    def test_module_main_doctor(self):
        from z0int.cli import main

        rc = main(["doctor", "--json"])
        self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main()
