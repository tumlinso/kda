"""Production-CLI cancellation across the external controller process tree.

Every command in this test is CPU-only. A looping subprocess stands in for a
long native task command and deliberately ignores SIGTERM to exercise the
runner's process-group escalation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from tests.test_cli_integration import CliTask, REPOSITORY


@unittest.skipUnless(
    os.name == "posix" and Path("/proc/self/stat").exists(),
    "process-group cancellation test requires POSIX process groups and /proc",
)
class ProductionCliCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kda-cli-cancel-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.task = CliTask(self.root)
        self.validator = self.root / "long_validation.py"
        self.validator.write_text(textwrap.dedent("""\
            import json, pathlib, signal, subprocess, sys, time, os
            request = json.loads(pathlib.Path(sys.argv[1]).read_text())
            root = pathlib.Path(sys.argv[3])
            pulse = root / 'native-equivalent.pulse'
            child_pid = root / 'native-equivalent.pid'
            child_code = "\\n".join([
                "import os, pathlib, signal, time",
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()))",
                f"pulse = pathlib.Path({str(pulse)!r})",
                "while True:",
                "    with pulse.open('a') as stream:",
                "        stream.write('x')",
                "    time.sleep(0.02)",
            ])
            child = subprocess.Popen([sys.executable, '-c', child_code])
            pathlib.Path(sys.argv[4]).write_text(json.dumps({
                'validator_pid': os.getpid(), 'child_pid': child.pid,
                'child_process_group': os.getpgid(child.pid),
                'request_id': request['request_id'],
            }))
            while True:
                time.sleep(1)
        """), encoding="utf-8")
        self.controller = self.root / "fake_controller.py"
        self.controller_log = self.root / "controller-released.json"
        self.controller.write_text(textwrap.dedent("""\
            import json, os, pathlib, signal, subprocess, sys
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            spec = pathlib.Path(sys.argv[sys.argv.index('--spec') + 1])
            spec_value = json.loads(spec.read_text())
            marker = pathlib.Path(sys.argv[1])
            worker = subprocess.Popen(spec_value['argv'], cwd=spec_value['command_cwd'])
            pathlib.Path(str(marker) + '.started').write_text(json.dumps({
                'controller_pid': os.getpid(), 'controller_pgid': os.getpgrp(),
                'worker_pid': worker.pid,
            }))
            try:
                returncode = worker.wait()
            finally:
                marker.write_text(json.dumps({
                    'controller_pid': os.getpid(), 'worker_pid': worker.pid,
                    'worker_returncode': worker.returncode,
                }))
            print(json.dumps({'ok': False, 'cancelled_worker': returncode}))
            raise SystemExit(1)
        """), encoding="utf-8")

        task = self.task.read_task()
        task["commands"]["validate"] = {
            "argv": [sys.executable, str(self.validator), "{request}", "{result}",
                     str(self.root), str(self.root / "validation-started.json")],
            "timeout_seconds": 120,
        }
        task["execution"] = {
            "mode": "launcher",
            "launcher_argv": [
                sys.executable, "-m", "kda_experiments.controller_launcher",
                "--config", str(self.root / "fake-site.json"),
                "--request", "{request}", "--result", "{result}",
            ],
        }
        task["trusted_inputs"].extend([
            {"id": "long_validation_command", "path": str(self.validator), "role": "harness"},
            {"id": "fake_cancellation_controller", "path": str(self.controller), "role": "other"},
            {"id": "fake_cancellation_site_config", "path": str(self.root / "fake-site.json"), "role": "toolchain"},
        ])
        (self.root / "fake-site.json").write_text(json.dumps({
            "controller_argv": [sys.executable, str(self.controller), str(self.controller_log)],
            "project_root": str(self.root),
            "resources": {"gpus": 1, "cpu_threads": 1},
            "toolchain": {"root": "/fake-cpu-test-toolchain"},
        }, indent=2) + "\n", encoding="utf-8")
        self.task.write_task(task)

    def _wait_for(self, path: Path, process: subprocess.Popen | None, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process is not None and process.poll() is not None:
                break
            time.sleep(0.02)
        status = process.poll() if process is not None else "not applicable"
        self.fail(f"timed out waiting for {path}; CLI status is {status}")

    @staticmethod
    def _process_is_running(pid: int) -> bool:
        stat = Path(f"/proc/{pid}/stat")
        if not stat.exists():
            return False
        # A zombie has stopped executing even if init has not reaped it yet.
        fields = stat.read_text(encoding="utf-8").split()
        return len(fields) > 2 and fields[2] not in {"Z", "X"}

    def _assert_pid_stopped(self, pid: int, *, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._process_is_running(pid):
                return
            time.sleep(0.05)
        self.fail(f"process {pid} was still running after CLI cancellation")

    @staticmethod
    def _stop_group(pgid: int, *, grace: float = 0.5) -> None:
        """Boundedly clean fixture-only groups, even after the CLI has exited."""
        def exists() -> bool:
            try:
                os.killpg(pgid, 0)
                return True
            except ProcessLookupError:
                return False

        if not exists():
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and exists():
            time.sleep(0.02)
        if exists():
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _start_evaluation(self) -> subprocess.Popen[str]:
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        command = [
            sys.executable, "-m", "kda_experiments",
            "--task", str(self.task.task_file), "--workspace", str(self.task.workspace),
            "evaluate", "--candidates", "fast", "--incumbent", "baseline",
        ]
        process = subprocess.Popen(
            command, cwd=REPOSITORY, env={**os.environ, "PYTHONPATH": str(REPOSITORY)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        return process

    def _await_child(self, process: subprocess.Popen[str]) -> tuple[dict, int]:
        self._wait_for(self.root / "validation-started.json", process)
        self._wait_for(self.root / "native-equivalent.pid", process)
        self._wait_for(self.root / "native-equivalent.pulse", process)
        self._wait_for(self.root / "controller-released.json.started", process)
        validation = json.loads((self.root / "validation-started.json").read_text(encoding="utf-8"))
        child_pid = int((self.root / "native-equivalent.pid").read_text(encoding="utf-8"))
        self.assertEqual(child_pid, validation["child_pid"])
        self.assertTrue(self._process_is_running(child_pid))
        controller_started = json.loads((self.root / "controller-released.json.started").read_text(encoding="utf-8"))
        return controller_started, child_pid

    def _assert_no_successful_publication(self) -> Path:
        attempts = self.task.workspace / "runs" / "kda-experiments" / "attempts"
        attempt_dirs = [path for path in attempts.iterdir() if path.is_dir()]
        self.assertEqual(len(attempt_dirs), 1)
        attempt = attempt_dirs[0]
        self.assertTrue((attempt / "batch-request.json").is_file())
        self.assertFalse((attempt / "summary.json").exists(), "cancelled evaluation published a summary")
        self.assertFalse((attempt / "worker-result.json").exists(), "cancelled worker published a result")
        preferred = self.task.workspace / "preferred"
        self.assertFalse(preferred.exists() and list(preferred.glob("*.json")),
                         "cancelled evaluation changed the preferred candidate")
        return attempt

    def _finish_if_needed(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                os.kill(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        # An assertion can fail before the production handler gets a chance to
        # unwind the tree. Test cleanup must not leave its fake controller or
        # validator subprocesses alive, whether or not the CLI parent exited.
        controller_started = self.root / "controller-released.json.started"
        if controller_started.is_file():
            try:
                info = json.loads(controller_started.read_text(encoding="utf-8"))
                self._stop_group(int(info["controller_pgid"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        validation_started = self.root / "validation-started.json"
        if validation_started.is_file():
            try:
                info = json.loads(validation_started.read_text(encoding="utf-8"))
                self._stop_group(int(info["validator_pid"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def test_public_cli_sigterm_unwinds_launcher_and_stops_native_equivalent_child(self):
        process = self._start_evaluation()

        self.addCleanup(self._finish_if_needed, process)
        controller_started, child_pid = self._await_child(process)

        started = time.monotonic()
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 128 + signal.SIGTERM, (stdout, stderr))
        self.assertLess(time.monotonic() - started, 9.0)

        self._wait_for(self.controller_log, None)
        controller = json.loads(self.controller_log.read_text(encoding="utf-8"))
        # An uncaught KeyboardInterrupt exits as a shell-style 130 under some
        # Python entrypoints and as signal termination (-SIGINT) under others.
        # The invariant is that its handler finished cleanup before controller
        # release, which the stopped descendant and release marker establish.
        self.assertIn(controller["worker_returncode"], {-signal.SIGINT, 128 + signal.SIGINT})
        self.assertEqual(controller["worker_pid"], controller_started["worker_pid"])
        self._assert_pid_stopped(child_pid)
        pulse = self.root / "native-equivalent.pulse"
        pulse_size = pulse.stat().st_size
        time.sleep(0.2)
        self.assertEqual(pulse.stat().st_size, pulse_size, "descendant kept running after cancellation returned")

        self._assert_no_successful_publication()

    def test_hidden_worker_sigterm_stops_child_without_publishing_success(self):
        process = self._start_evaluation()
        self.addCleanup(self._finish_if_needed, process)
        controller_started, child_pid = self._await_child(process)

        os.kill(int(controller_started["worker_pid"]), signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 1, (stdout, stderr))
        self._wait_for(self.controller_log, None)
        controller = json.loads(self.controller_log.read_text(encoding="utf-8"))
        self.assertEqual(controller["worker_pid"], controller_started["worker_pid"])
        self.assertEqual(controller["worker_returncode"], 128 + signal.SIGTERM)
        self._assert_pid_stopped(child_pid)

        pulse = self.root / "native-equivalent.pulse"
        pulse_size = pulse.stat().st_size
        time.sleep(0.2)
        self.assertEqual(pulse.stat().st_size, pulse_size, "descendant kept running after worker cancellation")
        attempt = self._assert_no_successful_publication()
        self.assertTrue((attempt / "failure.json").is_file(), "worker cancellation should fail the outer evaluation")


if __name__ == "__main__":
    unittest.main()
