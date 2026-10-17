"""End-to-end checks for CPU-only evaluation and promotion boundaries."""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from kda_experiments.engine import evaluate_candidates, prepare_candidates, select_run
from kda_experiments.errors import IntegrityError
from kda_experiments.runner import run_compiler_target_probe
from kda_experiments.store import atomic_write_json, read_attempt, read_jsonl, register_candidate, write_preferred
from tests.fixtures.cpu_task import create_workspace, manifest_path, source_dir


def _register(root: pathlib.Path, workspace: pathlib.Path, candidate_id: str, *, baseline: bool = False) -> None:
    register_candidate(
        workspace, candidate_id, source_dir(root, candidate_id),
        manifest_path(root, candidate_id), parent=None if baseline else "baseline",
        hypothesis=f"fixture hypothesis {candidate_id}",
        change=f"fixture change {candidate_id}", baseline=baseline,
    )


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kda-engine-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        create_workspace(self.root)
        self.task_path = self.root / "task.json"
        self.workspace = self.root / "workspace"

    def test_incorrect_candidate_never_reaches_benchmarking(self) -> None:
        task_data = json.loads(self.task_path.read_text())
        task_data["commands"]["validate"]["argv"][2] = "validate-attack-missing"
        self.task_path.write_text(json.dumps(task_data, indent=2) + "\n")
        _register(self.root, self.workspace, "baseline", baseline=True)
        _register(self.root, self.workspace, "fast")

        result = evaluate_candidates(self.task_path, self.workspace, ["fast"], "baseline")

        summary = read_attempt(self.workspace, result["run_id"])
        self.assertEqual(summary["validation"]["baseline"]["status"], "pass")
        self.assertEqual(summary["validation"]["fast"]["status"], "fail")
        benchmark = self.workspace / "benchmark.csv"
        with benchmark.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(rows, "valid incumbent should still establish a comparison")
        self.assertNotIn("fast", {row["candidate_id"] for row in rows})
        self.assertEqual(summary["decision"]["candidate_id"], "baseline")

    def test_compiler_probe_output_participates_in_build_reuse_identity(self) -> None:
        probe_script = self.root / "compiler_probe.py"
        probe_script.write_text(
            "import os\n"
            "print('cpu-test ' + os.environ.get('KDA_FIXTURE_COMPILER_VERSION', 'v1'))\n",
            encoding="utf-8",
        )
        task_data = json.loads(self.task_path.read_text())
        task_data["toolchain"] = {
            "compiler_target_probe_argv": [sys.executable, str(probe_script)],
        }
        task_data["trusted_inputs"].append({
            "id": "compiler_probe_script", "path": str(probe_script), "role": "toolchain",
        })
        self.task_path.write_text(json.dumps(task_data, indent=2) + "\n")
        _register(self.root, self.workspace, "baseline", baseline=True)
        from kda_experiments.contracts import load_task

        task, task_path = load_task(self.task_path)
        with patch.dict(os.environ, {"KDA_FIXTURE_COMPILER_VERSION": "v1"}):
            probe = run_compiler_target_probe(
                task, task_dir=task_path.parent,
                deadline=time.monotonic() + 30,
                evidence_dir=self.root / "probe-evidence-v1",
            )
        first = prepare_candidates(
            self.task_path, self.workspace, ["baseline"], compiler_target_probe=probe,
        )[0]
        with patch.dict(os.environ, {"KDA_FIXTURE_COMPILER_VERSION": "v2"}):
            second_probe = run_compiler_target_probe(
                task, task_dir=task_path.parent,
                deadline=time.monotonic() + 30,
                evidence_dir=self.root / "probe-evidence-v2",
            )
        second = prepare_candidates(
            self.task_path, self.workspace, ["baseline"], compiler_target_probe=second_probe,
        )[0]

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        first_manifest = json.loads(pathlib.Path(first["manifest_path"]).read_text())
        second_manifest = json.loads(pathlib.Path(second["manifest_path"]).read_text())
        self.assertEqual(first_manifest["compiler_target_probe"]["stdout_sha256"], probe["stdout_sha256"])
        self.assertEqual(second_manifest["compiler_target_probe"]["stdout_sha256"], second_probe["stdout_sha256"])

    def test_stale_apply_cannot_replace_a_newer_preferred_reference(self) -> None:
        _register(self.root, self.workspace, "baseline", baseline=True)
        _register(self.root, self.workspace, "fast")
        result = evaluate_candidates(self.task_path, self.workspace, ["fast"], "baseline")
        summary = read_attempt(self.workspace, result["run_id"])
        self.assertTrue(summary["decision"]["eligible"])
        group = summary["comparison_group"]
        current = summary["preferred"]
        newer = {
            **current,
            "candidate_id": "baseline",
            "run_id": "newer-run",
            "selected_at": "later",
        }
        write_preferred(self.workspace, group, newer)

        with self.assertRaisesRegex(IntegrityError, "preferred candidate changed"):
            select_run(self.workspace, result["run_id"], apply=True)
        self.assertEqual(json.loads((self.workspace / "preferred" / f"{group}.json").read_text()), newer)

    def test_select_reports_an_already_applied_promotion_without_overwriting_it(self) -> None:
        _register(self.root, self.workspace, "baseline", baseline=True)
        _register(self.root, self.workspace, "fast")
        result = evaluate_candidates(self.task_path, self.workspace, ["fast"], "baseline")
        summary = read_attempt(self.workspace, result["run_id"])
        target = summary["preferred_target"]
        selected = select_run(self.workspace, result["run_id"], apply=True)
        self.assertTrue(selected["applied"])
        self.assertEqual(selected["current_preferred"], target)
        self.assertEqual(selected["current_preferred"]["candidate_id"], "fast")

    def test_select_recovers_a_crash_after_preferred_update(self) -> None:
        _register(self.root, self.workspace, "baseline", baseline=True)
        _register(self.root, self.workspace, "fast")
        result = evaluate_candidates(self.task_path, self.workspace, ["fast"], "baseline")
        summary = read_attempt(self.workspace, result["run_id"])
        attempt_dir = self.workspace / "runs" / "kda-experiments" / "attempts" / result["run_id"]
        summary["promotion_status"] = "pending"
        summary["promoted"] = False
        atomic_write_json(attempt_dir / "summary.json", summary, replace=True)
        (attempt_dir / "promotion.json").unlink()

        selected = select_run(self.workspace, result["run_id"], apply=True)

        recovered = read_attempt(self.workspace, result["run_id"])
        self.assertTrue(selected["applied"])
        self.assertEqual(recovered["promotion_status"], "applied")
        self.assertTrue(recovered["promoted"])
        self.assertTrue((attempt_dir / "promotion.json").is_file())
        selection_records = [row for row in read_jsonl(self.workspace / "candidates.jsonl")
                             if row.get("record_type") == "selection" and row.get("run_id") == result["run_id"]]
        self.assertEqual(len(selection_records), 1)

    def test_select_recovers_a_crash_after_compare_and_swap(self) -> None:
        _register(self.root, self.workspace, "baseline", baseline=True)
        _register(self.root, self.workspace, "fast")
        result = evaluate_candidates(self.task_path, self.workspace, ["fast"], "baseline")
        summary = read_attempt(self.workspace, result["run_id"])
        attempt_dir = self.workspace / "runs" / "kda-experiments" / "attempts" / result["run_id"]
        expected = summary["preferred_before"]

        # Model a crash after the preferred pointer CAS but before the
        # promotion receipt and final summary were durably written.
        if expected is None:
            (self.workspace / "preferred" / f"{summary['comparison_group']}.json").unlink()
        else:
            write_preferred(self.workspace, summary["comparison_group"], expected)
        summary["promotion_status"] = "pending"
        summary["promoted"] = False
        summary["preferred"] = expected
        atomic_write_json(attempt_dir / "summary.json", summary, replace=True)
        (attempt_dir / "promotion.json").unlink()

        selected = select_run(self.workspace, result["run_id"], apply=True)

        recovered = read_attempt(self.workspace, result["run_id"])
        self.assertTrue(selected["applied"])
        self.assertEqual(selected["current_preferred"], summary["preferred_target"])
        self.assertEqual(recovered["promotion_status"], "applied")
        self.assertTrue(recovered["promoted"])
        self.assertEqual(recovered["preferred"], summary["preferred_target"])
        promotion = json.loads((attempt_dir / "promotion.json").read_text())
        self.assertEqual(promotion["status"], "applied")
        selection_records = [row for row in read_jsonl(self.workspace / "candidates.jsonl")
                             if row.get("record_type") == "selection" and row.get("run_id") == result["run_id"]]
        self.assertEqual(len(selection_records), 1)


if __name__ == "__main__":
    unittest.main()
