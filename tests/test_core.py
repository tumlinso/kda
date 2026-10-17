"""Focused contract and evidence-store checks for the experiment package."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kda_experiments.contracts import (
    load_json,
    load_task,
    validate_benchmark_response,
    validate_cases_response,
    workload_descriptor,
)
from kda_experiments.errors import ContractError, IntegrityError
from kda_experiments.store import register_candidate, verify_snapshot
from tests.fixtures.cpu_task import create_workspace, manifest_path, source_dir


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kda-core-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        create_workspace(self.root)
        self.task, self.task_path = load_task(self.root / "task.json")
        self.cases = [workload_descriptor(case) for case in self.task["cases"]]

    def test_task_rejects_duplicate_required_cases(self) -> None:
        config = json.loads((self.root / "task.json").read_text())
        config["cases"].append(dict(config["cases"][0]))
        (self.root / "duplicate.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(ContractError, "duplicate case id"):
            load_task(self.root / "duplicate.json")

    def test_validation_requires_top_level_success_and_exact_case_coverage(self) -> None:
        rows = [{
            "case_id": case["id"], "workload_sha256": case["workload_sha256"], "status": "pass",
        } for case in self.cases]
        response = {"schema_version": 1, "request_id": "r1", "status": "ok", "cases": rows}
        self.assertEqual(validate_cases_response(response, "r1", self.cases)["status"], "ok")
        with self.assertRaisesRegex(ContractError, "status must be 'ok'"):
            validate_cases_response({**response, "status": "error"}, "r1", self.cases)
        with self.assertRaisesRegex(ContractError, "omitted required cases"):
            validate_cases_response({**response, "cases": rows[:-1]}, "r1", self.cases)
        bad_rows = [dict(row) for row in rows]
        bad_rows[0]["workload_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "descriptor mismatch"):
            validate_cases_response({**response, "cases": bad_rows}, "r1", self.cases)

    def test_benchmark_requires_the_declared_metric_unit_and_raw_samples(self) -> None:
        case = self.cases[0]
        timing = self.task["timing"]
        response = {
            "schema_version": 1, "request_id": "b1", "status": "ok",
            "case_id": case["id"], "workload_sha256": case["workload_sha256"],
            "timing_scope": timing["scope"], "warmup": timing["warmup"],
            "repetitions": timing["repetitions"], "metric": timing["metric"],
            "unit": timing["unit"], "samples": [1.0] * timing["repetitions"],
        }
        self.assertEqual(validate_benchmark_response(response, "b1", case, timing)["samples"], [1.0, 1.0])
        for change, message in (({"status": "error"}, "status must be 'ok'"),
                                ({"metric": "other"}, "metric does not match"),
                                ({"unit": "other"}, "unit does not match"),
                                ({"samples": [1.0]}, "exactly")):
            with self.subTest(change=change), self.assertRaisesRegex(ContractError, message):
                validate_benchmark_response({**response, **change}, "b1", case, timing)

    def test_json_reader_rejects_duplicate_keys(self) -> None:
        malformed = self.root / "duplicate-keys.json"
        malformed.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
            load_json(malformed)


class CandidateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kda-store-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        create_workspace(self.root)
        self.workspace = self.root / "workspace"

    def test_registration_snapshots_manifest_and_preserves_executable_bits(self) -> None:
        source = source_dir(self.root, "baseline")
        script = source / "kernel.py"
        script.chmod(0o755)
        record = register_candidate(
            self.workspace, "baseline", source, manifest_path(self.root, "baseline"),
            parent=None, hypothesis="reference", change="register baseline", baseline=True,
        )
        snapshot = verify_snapshot(record)
        copied = snapshot / "kernel.py"
        self.assertEqual(copied.read_bytes(), script.read_bytes())
        self.assertTrue(copied.stat().st_mode & 0o111, "snapshot stripped executable permission")
        self.assertFalse(copied.stat().st_mode & 0o222, "snapshot should be read-only")

    def test_registered_snapshot_is_unchanged_when_source_changes(self) -> None:
        record = register_candidate(
            self.workspace, "baseline", source_dir(self.root, "baseline"),
            manifest_path(self.root, "baseline"), parent=None,
            hypothesis="reference", change="register baseline", baseline=True,
        )
        (source_dir(self.root, "baseline") / "kernel.py").write_text("def compute(values): return 0\n")
        self.assertEqual((verify_snapshot(record) / "kernel.py").read_text(),
                         "def compute(values):\n    total = 0.0\n    for value in values:\n        total += value\n    return total\n")


if __name__ == "__main__":
    unittest.main()
