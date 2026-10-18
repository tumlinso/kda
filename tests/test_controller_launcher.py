"""Adapter tests use a fake controller and never inspect or execute CUDA."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from kda_experiments.controller_launcher import launch


class ControllerLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.controller = self.root / "fake_controller.py"
        self.controller.write_text(
            "import json, pathlib, sys\n"
            "spec=json.loads(pathlib.Path(sys.argv[sys.argv.index('--spec')+1]).read_text())\n"
            "pathlib.Path('seen.json').write_text(json.dumps({'argv':sys.argv[1:],'spec':spec}))\n"
            "print(json.dumps({'ok':True,'lease_receipt':'fake-lease.json'}))\n"
        )
        self.config = self.root / "site.json"
        self.config.write_text(json.dumps({
            "controller_argv": [sys.executable, str(self.controller)],
            "project_root": str(self.root),
            "resources": {"gpus": 1, "cpu_threads": 2},
            "toolchain": {"root": "/configured-toolkit"},
        }))
        self.request = self.root / "request.json"
        self.request.write_text(json.dumps({
            "schema_version": 1, "request_id": "attempt-unique-id",
            "argv": [sys.executable, "worker.py", "--argument", "a b"],
            "cwd": str(self.root), "worker_result_path": str(self.root / "worker-result.json"),
            "timeout_seconds": 30,
        }))
        self.result = self.root / "receipt.json"

    def test_translates_one_batch_without_launching_worker_directly(self):
        receipt = launch(self.config, self.request, self.result)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["request_id"], "attempt-unique-id")
        seen = json.loads((self.root / "seen.json").read_text())
        self.assertEqual(seen["argv"][0], "run")
        self.assertEqual(seen["spec"]["recipe"], "baseline")
        self.assertEqual(seen["spec"]["argv"][-1], "a b")
        self.assertNotIn("metric", seen["spec"])
        self.assertNotIn("correctness_argv", seen["spec"])
        self.assertNotIn("build_argv", seen["spec"])
        self.assertEqual(receipt["controller_result"]["lease_receipt"], "fake-lease.json")

    def test_controller_denial_is_not_success_even_with_zero_exit(self):
        self.controller.write_text("print('{\"ok\":false,\"code\":\"contention\"}')\n")
        self.assertEqual(launch(self.config, self.request, self.result)["status"], "failed")
        self.assertFalse((self.root / "worker-result.json").exists())

    def test_site_quiescence_policy_reaches_controller(self):
        config = json.loads(self.config.read_text())
        config["quiescence"] = {"timeout_seconds": 60, "consecutive_idle_samples": 3,
                                "interval_seconds": 0.5}
        self.config.write_text(json.dumps(config))
        self.assertEqual(launch(self.config, self.request, self.result)["status"], "ok")
        seen = json.loads((self.root / "seen.json").read_text())
        self.assertEqual(seen["spec"]["quiescence"], config["quiescence"])

    def test_invalid_quiescence_policy_fails_before_admission(self):
        config = json.loads(self.config.read_text())
        policies = [None, {}, {"unknown": 1}, {"timeout_seconds": float("nan")},
                    {"timeout_seconds": 61}, {"interval_seconds": 0},
                    {"consecutive_idle_samples": True}, {"consecutive_idle_samples": 1.5}]
        for policy in policies:
            with self.subTest(policy=policy):
                config["quiescence"] = policy
                self.config.write_text(json.dumps(config))
                with self.assertRaisesRegex(ValueError, "quiescence"):
                    launch(self.config, self.request, self.result)
                self.assertFalse((self.root / "seen.json").exists())

    def test_nonzero_exit_rejects_apparent_success_json(self):
        self.controller.write_text("import sys\nprint('{\"ok\":true}')\nsys.exit(2)\n")
        self.assertEqual(launch(self.config, self.request, self.result)["exit_code"], 2)

    def test_malformed_controller_response_fails(self):
        self.controller.write_text("print('not JSON')\n")
        self.assertEqual(launch(self.config, self.request, self.result)["status"], "failed")

    def test_refuses_stale_result(self):
        self.result.write_text("{}")
        with self.assertRaisesRegex(ValueError, "already exists"):
            launch(self.config, self.request, self.result)
        self.assertFalse((self.root / "seen.json").exists())

    def test_refuses_cwd_outside_project(self):
        data = json.loads(self.request.read_text())
        data["cwd"] = str(self.root.parent)
        self.request.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "within project_root"):
            launch(self.config, self.request, self.result)

    def test_requires_explicit_toolchain_and_resources(self):
        config = json.loads(self.config.read_text())
        del config["toolchain"]
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "toolchain"):
            launch(self.config, self.request, self.result)

    @unittest.skipUnless(os.name == "posix", "POSIX controller cleanup")
    def test_cancellation_unwinds_controller_cleanup(self):
        self.controller.write_text(
            "import pathlib,time\n"
            "try:\n"
            " pathlib.Path('ready').write_text('ready')\n"
            " time.sleep(30)\n"
            "finally:\n"
            " pathlib.Path('released').write_text('released')\n"
        )
        with (self.root / "adapter.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "kda_experiments.controller_launcher",
                 "--config", str(self.config), "--request", str(self.request),
                 "--result", str(self.result)],
                stdout=log, stderr=log, start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not (self.root / "ready").exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail("adapter exited before fake controller was ready")
                    time.sleep(0.01)
                self.assertTrue((self.root / "ready").exists())
                os.killpg(process.pid, signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 128 + signal.SIGTERM)
                self.assertTrue((self.root / "released").exists())
                self.assertFalse(self.result.exists())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


if __name__ == "__main__":
    unittest.main()
