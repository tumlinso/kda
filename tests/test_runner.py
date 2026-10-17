"""Focused CPU tests for runner argv and process-tree boundaries."""

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

from kda_experiments.errors import ExecutionError
from kda_experiments.runner import _run, invoke_external_launcher, invoke_task_command


class RunnerArgumentTests(unittest.TestCase):
    def test_relative_script_argument_uses_the_command_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "relative.py"
            script.write_text("from pathlib import Path\nPath('cwd.txt').write_text(str(Path.cwd()))\n")

            result = _run(
                [sys.executable, "relative.py"], cwd=root, timeout_seconds=5,
                output_prefix=root / "process",
            )

            self.assertEqual(Path((root / "cwd.txt").read_text()), root.resolve())
            self.assertEqual(result["cwd"], str(root))

    def test_relative_executable_resolution_matches_invocation_cwd(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            driver = root / "driver.py"
            driver.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "request = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
                "pathlib.Path(sys.argv[2]).write_text(json.dumps({"
                "'schema_version': 1, 'request_id': request['request_id'], 'status': 'ok'}))\n"
            )
            driver.chmod(0o755)

            response, process, _ = invoke_task_command(
                {"argv": ["./driver.py", "{request}", "{result}"], "timeout_seconds": 5},
                {"operation": "test"}, cwd=root, stage_dir=root / "stage",
                deadline=time.monotonic() + 10, label="relative command",
            )

            self.assertEqual(response["status"], "ok")
            self.assertEqual(process["cwd"], str(root))
            self.assertEqual(process["executable"]["path"], str(driver.resolve()))
            self.assertEqual(process["argv"][0], "./driver.py")


@unittest.skipUnless(os.name == "posix", "process-group behavior is POSIX-specific")
class ProcessCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def _sentinel_code(pid_path: Path, pulse_path: Path) -> str:
        return textwrap.dedent(f"""\
            import pathlib, signal, time, os
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
            pulse = pathlib.Path({str(pulse_path)!r})
            while True:
                with pulse.open('a') as stream:
                    stream.write('x')
                time.sleep(0.025)
        """)

    def _wait_for_file(self, path: Path, process: subprocess.Popen | None = None) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process is not None and process.poll() is not None:
                break
            time.sleep(0.01)
        self.fail(f"timed out waiting for {path}")

    def _assert_pulse_stopped(self, path: Path) -> None:
        self.assertTrue(path.exists(), "grandchild did not start")
        previous = path.stat().st_size
        stable_since = time.monotonic()
        deadline = stable_since + 3
        while time.monotonic() < deadline:
            time.sleep(0.1)
            current = path.stat().st_size
            if current == previous:
                if time.monotonic() - stable_since >= 0.3:
                    return
            else:
                previous = current
                stable_since = time.monotonic()
        self.fail("grandchild kept running after cancellation returned")

    def test_timeout_escalates_after_group_leader_exits_on_term(self):
        pid_path = self.root / "grandchild.pid"
        pulse_path = self.root / "pulse"
        grandchild = self._sentinel_code(pid_path, pulse_path)
        parent = textwrap.dedent(f"""\
            import subprocess, sys, time
            subprocess.Popen([sys.executable, '-c', {grandchild!r}])
            time.sleep(30)
        """)

        started = time.monotonic()
        with self.assertRaisesRegex(ExecutionError, "timed out"):
            _run(
                [sys.executable, "-c", parent], cwd=self.root,
                timeout_seconds=0.5, output_prefix=self.root / "timed",
            )

        self.assertLess(time.monotonic() - started, 5)
        self._wait_for_file(pulse_path)
        self._assert_pulse_stopped(pulse_path)

    def _cancellation_supervisor(self, pid_path: Path, pulse_path: Path) -> str:
        grandchild = self._sentinel_code(pid_path, pulse_path)
        worker = textwrap.dedent(f"""\
            import pathlib, sys, time
            from kda_experiments.runner import _run, install_termination_handlers
            install_termination_handlers()
            _run([sys.executable, '-c', {grandchild!r}], cwd=pathlib.Path.cwd(),
                 timeout_seconds=30, output_prefix=pathlib.Path({str(self.root / 'inner')!r}))
        """)
        supervisor = textwrap.dedent(f"""\
            import pathlib, sys
            from kda_experiments.runner import _run, install_termination_handlers
            install_termination_handlers()
            _run([sys.executable, '-c', {worker!r}], cwd=pathlib.Path.cwd(),
                 timeout_seconds=30, termination_grace_seconds=2.0,
                 output_prefix=pathlib.Path({str(self.root / 'worker')!r}))
        """)
        return supervisor

    def _single_supervisor(self, pid_path: Path, pulse_path: Path) -> str:
        grandchild = self._sentinel_code(pid_path, pulse_path)
        command = textwrap.dedent(f"""\
            import subprocess, sys, time
            subprocess.Popen([sys.executable, '-c', {grandchild!r}])
            time.sleep(30)
        """)
        return textwrap.dedent(f"""\
            import pathlib, sys
            from kda_experiments.runner import _run, install_termination_handlers
            install_termination_handlers()
            _run([sys.executable, '-c', {command!r}], cwd=pathlib.Path.cwd(),
                 timeout_seconds=30, output_prefix=pathlib.Path({str(self.root / 'single')!r}))
        """)

    def _parallel_supervisor(self, pid_paths: list[Path], pulse_paths: list[Path]) -> str:
        commands = []
        for pid_path, pulse_path in zip(pid_paths, pulse_paths):
            grandchild = self._sentinel_code(pid_path, pulse_path)
            commands.append(textwrap.dedent(f"""\
                import subprocess, sys, time
                subprocess.Popen([sys.executable, '-c', {grandchild!r}])
                time.sleep(30)
            """))
        calls = ",\n".join(
            f"    pool.submit(_run, [sys.executable, '-c', {command!r}], cwd=root, "
            f"timeout_seconds=30, output_prefix=root / 'parallel-{index}')"
            for index, command in enumerate(commands)
        )
        return (
            "import concurrent.futures, pathlib, sys\n"
            "from kda_experiments.runner import _run, install_termination_handlers\n"
            "install_termination_handlers()\n"
            "root = pathlib.Path.cwd()\n"
            "pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)\n"
            "futures = [\n" + calls + "\n]\n"
            "for future in futures:\n    future.result()\n"
        )

    def test_sigterm_during_registry_critical_section_does_not_deadlock(self):
        code = textwrap.dedent("""\
            import os, signal, subprocess, sys
            from kda_experiments.runner import _active_lock, _active_processes, install_termination_handlers
            install_termination_handlers()
            child = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
            child.wait()
            with _active_lock:
                _active_processes[child.pid] = (child, 0.2)
                os.kill(os.getpid(), signal.SIGTERM)
        """)
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self.assertEqual(process.wait(timeout=3), 128 + signal.SIGTERM)

    def test_sigterm_cleans_nested_runner_process_groups(self):
        pid_path = self.root / "grandchild.pid"
        pulse_path = self.root / "pulse"
        supervisor = subprocess.Popen(
            [sys.executable, "-c", self._cancellation_supervisor(pid_path, pulse_path)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())
        self._wait_for_file(pulse_path, supervisor)

        os.kill(supervisor.pid, signal.SIGTERM)
        supervisor.wait(timeout=6)

        self._assert_pulse_stopped(pulse_path)

    def test_keyboard_interrupt_cleans_nested_runner_process_groups(self):
        pid_path = self.root / "grandchild.pid"
        pulse_path = self.root / "pulse"
        supervisor = subprocess.Popen(
            [sys.executable, "-c", self._single_supervisor(pid_path, pulse_path)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())
        self._wait_for_file(pulse_path, supervisor)

        os.kill(supervisor.pid, signal.SIGINT)
        supervisor.wait(timeout=6)

        self._assert_pulse_stopped(pulse_path)

    def test_cancellation_cleans_parallel_worker_groups(self):
        pulses = [self.root / "pulse-a", self.root / "pulse-b"]
        pids = [self.root / "a.pid", self.root / "b.pid"]
        supervisor = subprocess.Popen(
            [sys.executable, "-c", self._parallel_supervisor(pids, pulses)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())
        for pulse_path in pulses:
            self._wait_for_file(pulse_path, supervisor)

        os.kill(supervisor.pid, signal.SIGTERM)
        supervisor.wait(timeout=6)
        for pulse_path in pulses:
            self._assert_pulse_stopped(pulse_path)

    def test_launcher_cancellation_waits_for_controller_and_worker_cleanup(self):
        worker_done = self.root / "worker-done"
        controller_released = self.root / "controller-released"
        pid_path = self.root / "grandchild.pid"
        pulse_path = self.root / "pulse"
        grandchild = self._sentinel_code(pid_path, pulse_path)
        worker = textwrap.dedent(f"""\
            import pathlib, sys
            from kda_experiments.runner import _run, install_termination_handlers
            install_termination_handlers()
            try:
                _run([sys.executable, '-c', {grandchild!r}], cwd=pathlib.Path.cwd(),
                     timeout_seconds=30, output_prefix=pathlib.Path({str(self.root / 'task')!r}))
            finally:
                pathlib.Path({str(worker_done)!r}).write_text('done')
        """)
        controller = self.root / "fake_controller.py"
        controller.write_text(textwrap.dedent(f"""\
            import json, pathlib, signal, subprocess, sys
            signal.signal(signal.SIGINT, lambda *_: None)
            spec_path = pathlib.Path(sys.argv[sys.argv.index('--spec') + 1])
            spec = json.loads(spec_path.read_text())
            worker = subprocess.Popen(spec['argv'], cwd=spec['command_cwd'])
            try:
                worker.wait()
            finally:
                pathlib.Path({str(controller_released)!r}).write_text(
                    'worker_done=' + str(pathlib.Path({str(worker_done)!r}).exists()))
            print(json.dumps({{'ok': False, 'cancelled': True}}))
            sys.exit(1)
        """))
        config = self.root / "site.json"
        config.write_text(json.dumps({
            "controller_argv": [sys.executable, str(controller)],
            "project_root": str(self.root),
            "resources": {"gpus": 1},
            "toolchain": {"root": "/fake-toolkit"},
        }))
        launcher_argv = [
            sys.executable, "-m", "kda_experiments.controller_launcher",
            "--config", str(config), "--request", "{request}", "--result", "{result}",
        ]
        supervisor_code = textwrap.dedent(f"""\
            import pathlib, sys, time
            from kda_experiments.runner import install_termination_handlers, invoke_external_launcher
            install_termination_handlers()
            task = {{'execution': {{'mode': 'launcher', 'launcher_argv': {launcher_argv!r}}}}}
            invoke_external_launcher(
                task, [sys.executable, '-c', {worker!r}], cwd=pathlib.Path.cwd(),
                worker_result_path=pathlib.Path.cwd() / 'worker-result.json',
                stage_dir=pathlib.Path.cwd() / 'stage', deadline=time.monotonic() + 60,
            )
        """)
        supervisor = subprocess.Popen(
            [sys.executable, "-c", supervisor_code], cwd=self.root,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )

        def kill_test_tree():
            if supervisor.poll() is None:
                os.killpg(supervisor.pid, signal.SIGKILL)
                supervisor.wait()

        self.addCleanup(kill_test_tree)
        self._wait_for_file(pulse_path, supervisor)
        os.kill(supervisor.pid, signal.SIGTERM)
        supervisor.wait(timeout=8)

        self.assertEqual(supervisor.returncode, 128 + signal.SIGTERM)
        self.assertTrue(worker_done.exists(), "worker did not finish its cancellation path")
        self.assertEqual(controller_released.read_text(), "worker_done=True")
        self._assert_pulse_stopped(pulse_path)


if __name__ == "__main__":
    unittest.main()
