"""Adversarial end-to-end tests for the public experiment CLI.

All runs use a temporary CPU-only task. The fixture's deterministic benchmark
samples exist only to exercise selection; they are not performance evidence.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests.fixtures.cpu_task import create_workspace, manifest_path, source_dir


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]


class CliTask:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.task_file = root / "task.json"
        self.workspace = root / "experiment-workspace"
        self.audit = root / "fixture-audit.jsonl"
        self.interrupt_marker = root / "interrupt-once.marker"
        self.env_overrides: dict[str, str] = {}
        create_workspace(root)

    def read_task(self) -> dict:
        return json.loads(self.task_file.read_text(encoding="utf-8"))

    def write_task(self, value: dict) -> None:
        self.task_file.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def command(self, *args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["KDA_FIXTURE_AUDIT"] = str(self.audit)
        if self.interrupt_marker.exists() or self.interrupt_marker.parent.exists():
            env["KDA_FIXTURE_INTERRUPT_ONCE"] = str(self.interrupt_marker)
        env.update(self.env_overrides)
        result = subprocess.run(
            [sys.executable, "-m", "kda_experiments", "--task", str(self.task_file),
             "--workspace", str(self.workspace), *args],
            cwd=REPOSITORY,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        if expect_success and result.returncode != 0:
            raise AssertionError(
                f"CLI failed ({result.returncode}): {' '.join(args)}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def register(self, candidate_id: str, *, parent: str | None = None,
                 baseline: bool = False) -> None:
        args = [
            "register", candidate_id, str(source_dir(self.root, candidate_id)),
            "--manifest", str(manifest_path(self.root, candidate_id)),
            "--hypothesis", f"fixture hypothesis for {candidate_id}",
            "--change", f"fixture change for {candidate_id}",
        ]
        if parent:
            args.extend(["--parent", parent])
        if baseline:
            args.append("--baseline")
        self.command(*args)

    def register_all(self, *, include_bad: bool = False, include_slow: bool = False,
                     include_build_failure: bool = False) -> None:
        self.register("baseline", baseline=True)
        self.register("fast", parent="baseline")
        if include_bad:
            self.register("bad", parent="baseline")
        if include_slow:
            self.register("slow", parent="baseline")
        if include_build_failure:
            self.register("broken-build", parent="baseline")

    def prepare(self, *candidate_ids: str) -> None:
        self.command("prepare", *candidate_ids)

    def evaluate(self, *candidate_ids: str) -> dict:
        result = self.command("evaluate", "--candidates", *candidate_ids, "--incumbent", "baseline",
                              expect_success=False)
        if not result.stdout.strip():
            return {"returncode": result.returncode, "stderr": result.stderr}
        try:
            output = json.loads(result.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            output = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        output.setdefault("returncode", result.returncode)
        return output

    def events(self, event_name: str) -> list[dict]:
        if not self.audit.exists():
            return []
        return [json.loads(line) for line in self.audit.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("event") == event_name]

    def configure_fake_controller(self, *, behavior: str = "normal") -> pathlib.Path:
        log = self.root / "fake-controller-log.jsonl"
        controller = pathlib.Path(__file__).parent / "fixtures" / "fake_controller.py"
        site = self.root / "fake-site-config.json"
        site.write_text(json.dumps({
            "controller_argv": [sys.executable, str(controller), str(log), behavior],
            "project_root": str(self.root),
            "resources": {"gpus": 1, "cpu_threads": 2},
            "toolchain": {"root": "/configured-test-toolchain"},
        }, indent=2) + "\n", encoding="utf-8")
        task = self.read_task()
        task["execution"] = {
            "mode": "launcher",
            "launcher_argv": [
                sys.executable, "-m", "kda_experiments.controller_launcher",
                "--config", str(site), "--request", "{request}", "--result", "{result}",
            ],
        }
        task["trusted_inputs"] = [
            *task["trusted_inputs"],
            {"id": "fake_cuda_site_config", "path": str(site), "role": "toolchain"},
            {"id": "fake_cuda_controller", "path": str(controller), "role": "other"},
        ]
        self.write_task(task)
        return log

    def latest_attempt(self) -> pathlib.Path:
        attempts = self.workspace / "runs" / "kda-experiments" / "attempts"
        return max((path for path in attempts.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime_ns)


class CliIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="kda-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.task = CliTask(pathlib.Path(self.temp.name))

    def test_good_candidate_is_promoted_and_incorrect_candidate_never_benchmarked(self):
        self.task.register_all(include_bad=True)
        self.task.prepare("baseline", "fast", "bad")
        result = self.task.evaluate("fast", "bad")
        self.assertIn(result.get("status"), {"complete", "ok"}, result)
        self.assertNotIn("bad", {row.get("candidate_id") for row in self.task.events("benchmark")})
        run_id = result["run_id"]
        selected = self.task.command("select", run_id, "--apply")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        group = result["comparison_group"]
        preferred = self.task.workspace / "preferred" / f"{group}.json"
        self.assertTrue(preferred.exists(), f"missing preferred reference: {preferred}")
        reference = json.loads(preferred.read_text(encoding="utf-8"))
        self.assertEqual(reference.get("candidate_id"), "fast")

        inspected_candidate = self.task.command("inspect", "fast")
        candidate_record = json.loads(inspected_candidate.stdout.strip().splitlines()[-1])
        self.assertEqual(candidate_record.get("kind"), "candidate")
        inspected_run = self.task.command("inspect", run_id)
        run_record = json.loads(inspected_run.stdout.strip().splitlines()[-1])
        self.assertEqual(run_record.get("kind"), "run")
        self.assertEqual(run_record.get("run_id"), run_id)
        artifact = self.task.root / "diagnostic-profile.json"
        artifact.write_text('{"source":"cpu-fixture","timing":"not benchmark timing"}\n', encoding="utf-8")
        attached = self.task.command("attach-evidence", run_id, str(artifact), "--kind", "profile",
                                     "--candidate", "fast", "--case-id", "larger")
        attachment = json.loads(attached.stdout.strip().splitlines()[-1])["evidence"]
        self.assertEqual(attachment.get("candidate_id"), "fast")
        self.assertEqual(attachment.get("metric_role"), "diagnostic")
        self.assertFalse(attachment.get("timing_in_benchmark_score"))
        copied = pathlib.Path(attachment["path"])
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), artifact.read_bytes())

    def test_build_failed_challenger_is_recorded_while_valid_candidate_can_win(self):
        self.task.register_all(include_build_failure=True)
        result = self.task.evaluate("fast", "broken-build")
        self.assertIn(result.get("status"), {"complete", "ok"}, result)
        self.assertIn("broken-build", result.get("build_errors", {}), result)
        timed_ids = {row.get("candidate_id") for row in self.task.events("benchmark")}
        self.assertIn("fast", timed_ids)
        self.assertNotIn("broken-build", timed_ids)
        self.assertEqual(result.get("decision", {}).get("candidate_id"), "fast")

    def test_stale_selection_cannot_overwrite_a_newer_preferred_candidate(self):
        self.task.register_all(include_slow=True)
        older = self.task.evaluate("slow")
        self.assertIn(older.get("status"), {"complete", "ok"}, older)
        self.assertFalse(older.get("decision", {}).get("eligible"), older)
        old_preferred = self.task.workspace / "preferred" / f"{older['comparison_group']}.json"
        self.assertEqual(json.loads(old_preferred.read_text(encoding="utf-8")).get("candidate_id"), "baseline")
        newer = self.task.evaluate("fast")
        self.assertIn(newer.get("status"), {"complete", "ok"}, newer)
        self.assertEqual(newer.get("decision", {}).get("candidate_id"), "fast")
        stale_select = self.task.command("select", older["run_id"], "--apply", expect_success=False)
        self.assertTrue(stale_select.stdout or stale_select.stderr)
        preferred = self.task.workspace / "preferred" / f"{newer['comparison_group']}.json"
        self.assertEqual(json.loads(preferred.read_text(encoding="utf-8")).get("candidate_id"), "fast")

    def test_trusted_launcher_config_change_invalidates_old_selection(self):
        log = self.task.configure_fake_controller()
        config = json.loads((self.task.root / "fake-site-config.json").read_text(encoding="utf-8"))
        self.assertTrue(config["controller_argv"])
        trusted_ids = {item["id"] for item in self.task.read_task()["trusted_inputs"]}
        self.assertIn("fake_cuda_site_config", trusted_ids)
        self.assertIn("fake_cuda_controller", trusted_ids)
        self.task.register_all()
        result = self.task.evaluate("fast")
        self.assertIn(result.get("status"), {"complete", "ok"}, result)
        preferred_path = self.task.workspace / "preferred" / f"{result['comparison_group']}.json"
        preferred_before = json.loads(preferred_path.read_text(encoding="utf-8"))
        site = self.task.root / "fake-site-config.json"
        site.write_text(site.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        selection = self.task.command("select", result["run_id"], "--apply", expect_success=False)
        self.assertNotEqual(selection.returncode, 0)
        preferred_after = json.loads(preferred_path.read_text(encoding="utf-8"))
        self.assertEqual(preferred_after["candidate_id"], preferred_before["candidate_id"])
        self.assertEqual(preferred_after["candidate_id"], "fast")

    def test_validation_rejects_missing_duplicate_oom_unsupported_stale_and_shrunk_cases(self):
        attacks = ("missing", "duplicate", "oom", "unsupported", "wrong_request", "wrong_digest")
        for attack in attacks:
            with self.subTest(attack=attack), tempfile.TemporaryDirectory(prefix="kda-protocol-test-") as raw:
                task = CliTask(pathlib.Path(raw))
                config = task.read_task()
                config["commands"]["validate"]["argv"] = [
                    sys.executable, str(pathlib.Path(__file__).parent / "fixtures" / "cpu_driver.py"),
                    f"validate-attack-{attack}", "{request}", "{result}",
                ]
                task.write_task(config)
                task.register_all()
                task.prepare("baseline", "fast")
                result = task.evaluate("fast")
                self.assertIn(result.get("status"), {"complete", "ok"}, result)
                timed_ids = {row.get("candidate_id") for row in task.events("benchmark")}
                self.assertNotIn("fast", timed_ids,
                                 f"invalid validation response reached candidate timing for attack={attack}")

    def test_top_level_validation_error_rejects_rows_that_all_claim_pass(self):
        config = self.task.read_task()
        config["commands"]["validate"]["argv"] = [
            sys.executable, str(pathlib.Path(__file__).parent / "fixtures" / "cpu_driver.py"),
            "validate-top-error", "{request}", "{result}",
        ]
        self.task.write_task(config)
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        result = self.task.evaluate("fast")
        self.assertNotIn(result.get("status"), {"complete", "ok"}, result)
        self.assertEqual(self.task.events("benchmark"), [])

    def test_nonfinite_or_wrong_benchmark_result_cannot_be_selected(self):
        for mode in (
            "benchmark-nonfinite", "benchmark-wrong-case", "benchmark-shrunk", "benchmark-stale",
            "benchmark-wrong-metric", "benchmark-wrong-unit", "benchmark-top-error",
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="kda-benchmark-test-") as raw:
                task = CliTask(pathlib.Path(raw))
                config = task.read_task()
                config["commands"]["benchmark"]["argv"] = [
                    sys.executable, str(pathlib.Path(__file__).parent / "fixtures" / "cpu_driver.py"),
                    mode.replace("benchmark-", "benchmark-attack-", 1), "{request}", "{result}",
                ]
                task.write_task(config)
                task.register_all()
                task.prepare("baseline", "fast")
                result = task.evaluate("fast")
                self.assertNotEqual(result.get("decision", {}).get("eligible"), True, result)
                preferred = list((task.workspace / "preferred").glob("*.json")) \
                    if (task.workspace / "preferred").exists() else []
                for reference in preferred:
                    self.assertNotEqual(json.loads(reference.read_text(encoding="utf-8")).get("candidate_id"), "fast")

    def test_interrupted_stage_result_is_not_reused_as_a_successful_attempt(self):
        config = self.task.read_task()
        config["probe"]["argv"] = [
            sys.executable, str(pathlib.Path(__file__).parent / "fixtures" / "cpu_driver.py"),
            "probe-interrupt-once", "{request}", "{result}",
        ]
        self.task.write_task(config)
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        failed = self.task.evaluate("fast")
        self.assertNotIn(failed.get("status"), {"complete", "ok"}, failed)
        if not failed.get("run_id"):
            failed["run_id"] = self.task.latest_attempt().name
        self.assertTrue(failed.get("run_id"), failed)
        interrupted_requests = list((self.task.workspace / "runs" / "kda-experiments" / "attempts" /
                                    failed["run_id"] / "stages" / "probe" / "requests").glob("*.json"))
        self.assertTrue(interrupted_requests)
        resumed = self.task.command("resume", failed["run_id"])
        result = json.loads(resumed.stdout.strip().splitlines()[-1])
        self.assertIn(result.get("status"), {"complete", "ok"}, result)
        self.assertNotEqual(result.get("run_id"), failed["run_id"])
        resumed_requests = list((self.task.workspace / "runs" / "kda-experiments" / "attempts" /
                                 result["run_id"] / "stages" / "probe" / "requests").glob("*.json"))
        self.assertTrue(resumed_requests)
        self.assertNotEqual(interrupted_requests[0].name, resumed_requests[0].name,
                            "resume reused an interrupted evaluator request/result identity")
        self.assertTrue(self.task.events("benchmark"), "resumed evaluation did not finish a fresh benchmark")

    def test_environment_mismatch_aborts_before_timing(self):
        config = self.task.read_task()
        config["probe"]["argv"] = [
            sys.executable, str(pathlib.Path(__file__).parent / "fixtures" / "cpu_driver.py"),
            "probe-mismatch", "{request}", "{result}",
        ]
        self.task.write_task(config)
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        result = self.task.evaluate("fast")
        self.assertNotIn(result.get("status"), {"complete", "ok"}, result)
        self.assertEqual(self.task.events("benchmark"), [])

    def test_cuda_target_requires_physical_architecture_and_checks_exact_compiler_code(self):
        self.task.register_all()
        config = self.task.read_task()
        config["target"] = {"kind": "cuda", "architecture": "sm70", "compiler_target": "sm70"}
        config["toolchain"] = {
            "compiler_target_probe_argv": [sys.executable, str(pathlib.Path(__file__).parent / "fixtures" / "cpu_driver.py"),
                                           "print-compiler-target", "sm70"],
        }
        self.task.write_task(config)
        malformed = self.task.command("evaluate", "--candidates", "fast", "--incumbent", "baseline",
                                      expect_success=False)
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("physical architecture", malformed.stderr + malformed.stdout)

        config["target"] = {"kind": "cuda", "architecture": "sm_90", "compiler_target": "sm_90a"}
        config["toolchain"]["compiler_target_probe_argv"][-1] = "sm_90a"
        self.task.write_task(config)
        accepted_code = self.task.command("evaluate", "--candidates", "fast", "--incumbent", "baseline",
                                          expect_success=False)
        self.assertNotEqual(accepted_code.returncode, 0, "CPU probe must not masquerade as CUDA architecture evidence")
        self.assertNotIn("does not report support for target sm_90a", accepted_code.stderr + accepted_code.stdout)
        probes = list((self.task.workspace / "runs" / "kda-experiments" / "preflight").glob("*/compiler-target-probe.stdout.txt"))
        self.assertTrue(probes, "compiler target support probe was not executed")
        self.assertTrue(any("sm_90a" in path.read_text(encoding="utf-8") for path in probes))

    def test_launcher_denial_never_falls_back_to_direct_execution(self):
        launcher = pathlib.Path(__file__).parent / "fixtures" / "deny_launcher.py"
        config = self.task.read_task()
        config["execution"] = {
            "mode": "launcher",
            "launcher_argv": [sys.executable, str(launcher), "{request}", "{result}"],
        }
        config["trusted_inputs"].append({
            "id": "denial_launcher", "path": str(launcher), "role": "other",
        })
        self.task.write_task(config)
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        result = self.task.evaluate("fast")
        self.assertNotIn(result.get("status"), {"complete", "ok"}, result)
        self.assertEqual(self.task.events("benchmark"), [])

    def test_controller_launcher_executes_one_cpu_only_batch_with_exact_worker_command(self):
        log = self.task.configure_fake_controller()
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        result = self.task.evaluate("fast")
        self.assertIn(result.get("status"), {"complete", "ok"}, result)
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1, "one launcher admission must cover validation, timing and confirmation")
        self.assertEqual(records[0]["returncode"], 0, records[0])
        attempt = self.task.workspace / "runs" / "kda-experiments" / "attempts" / result["run_id"]
        expected_argv = [
            sys.executable, "-m", "kda_experiments", "_worker",
            "--task", str(self.task.task_file.resolve()),
            "--workspace", str(self.task.workspace.resolve()),
            "--batch-request", str((attempt / "worker-request.json").resolve()),
            "--batch-result", str((attempt / "worker-result.json").resolve()),
        ]
        self.assertEqual(records[0]["argv"], expected_argv)
        self.assertEqual(records[0]["cwd"], str(self.task.workspace.resolve()))
        self.assertEqual(records[0]["project_root"], str(self.task.root))
        receipt = json.loads((attempt / "launcher-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["controller_result"].get("lease_receipt"), "fake-cpu-only-admission")
        self.assertTrue(self.task.events("benchmark"), "batch worker did not execute benchmark stages")

    def test_controller_postcheck_rejection_after_worker_run_leaves_no_selectable_success(self):
        log = self.task.configure_fake_controller(behavior="mutate-task-after-worker")
        self.task.register_all()
        result = self.task.evaluate("fast")
        self.assertNotIn(result.get("status"), {"complete", "ok"}, result)
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["returncode"], 0, "controller must reject only after worker completed")
        run_id = result.get("run_id") or self.task.latest_attempt().name
        attempt = self.task.workspace / "runs" / "kda-experiments" / "attempts" / run_id
        self.assertTrue((attempt / "failure.json").exists())
        self.assertFalse((attempt / "summary.json").exists())
        inspect = self.task.command("inspect", run_id)
        inspected = json.loads(inspect.stdout.strip().splitlines()[-1])
        self.assertIsNone(inspected.get("summary"))
        self.assertIsNotNone(inspected.get("failure"))
        self.assertFalse(list((self.task.workspace / "preferred").glob("*.json"))
                         if (self.task.workspace / "preferred").exists() else [])
        select = self.task.command("select", run_id, "--apply", expect_success=False)
        self.assertNotEqual(select.returncode, 0)

    def test_mutating_registered_snapshot_is_detected_before_build_or_evaluation(self):
        self.task.register_all()
        snapshot = next((self.task.workspace / "runs" / "kda-experiments" / "candidates" / "fast").glob("*/kernel.py"), None)
        self.assertIsNotNone(snapshot, "candidate snapshot not found")
        snapshot.chmod(0o644)
        snapshot.write_text("def compute(values): return -1\n", encoding="utf-8")
        prepared = self.task.command("prepare", "fast", expect_success=False)
        self.assertNotEqual(prepared.returncode, 0)
        self.assertEqual(self.task.events("benchmark"), [])

    def test_candidate_cannot_change_source_or_binary_after_validation_and_reach_timing(self):
        source = source_dir(self.task.root, "fast") / "kernel.py"
        source.write_text(
            "import os, pathlib\n"
            "def compute(values):\n"
            "    for name in ('KDA_FIXTURE_TAMPER_SOURCE', 'KDA_FIXTURE_TAMPER_ARTIFACT'):\n"
            "        target = os.environ.get(name)\n"
            "        if target:\n"
            "            path = pathlib.Path(target)\n"
            "            path.chmod(0o644)\n"
            "            path.write_text('tampered-after-validation\\n')\n"
            "    return sum(values)\n",
            encoding="utf-8",
        )
        self.task.register_all()
        self.task.prepare("baseline", "fast")
        snapshot = next((self.task.workspace / "runs" / "kda-experiments" / "candidates" / "fast").glob("*/kernel.py"))
        artifact = next((self.task.workspace / "runs" / "kda-experiments" / "builds" / "fast").glob("**/kernel.pyc"))
        self.task.env_overrides = {
            "KDA_FIXTURE_TAMPER_SOURCE": str(snapshot),
            "KDA_FIXTURE_TAMPER_ARTIFACT": str(artifact),
        }
        result = self.task.evaluate("fast")
        timed_ids = {row.get("candidate_id") for row in self.task.events("benchmark")}
        self.assertNotIn("fast", timed_ids,
                         f"candidate source or build artifact changed after validation but was benchmarked: {result}")


if __name__ == "__main__":
    unittest.main()
