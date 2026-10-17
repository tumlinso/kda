"""Materialize a portable CPU-only task for KDA CLI tests."""

from __future__ import annotations

import json
import pathlib
import sys

DRIVER = pathlib.Path(__file__).with_name("cpu_driver.py").resolve()

_SOURCES = {
    "baseline": '''def compute(values):
    total = 0.0
    for value in values:
        total += value
    return total
''',
    "fast": '''def compute(values):
    return sum(values)
''',
    "bad": '''def compute(values):
    return 0.0
''',
    "slow": '''def compute(values):
    return sum(values)
''',
    "broken-build": '''def compute(values):
    return sum(values)
''',
}


def _command(mode: str) -> list[str]:
    return [sys.executable, str(DRIVER), mode, "{request}", "{result}"]


def create_workspace(root: str | pathlib.Path, *, validation_mode: str = "validate",
                     probe_mode: str = "probe") -> pathlib.Path:
    """Create a task workspace and three source trees under ``root``.

    Candidate code is only ``kernel.py`` inside candidate source directories;
    the reference and all command drivers stay in the trusted test fixture.
    """
    root = pathlib.Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidates = root / "candidate-sources"
    for name, source in _SOURCES.items():
        source_dir = candidates / name
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "kernel.py").write_text(source, encoding="utf-8")
    task = {
        "schema_version": 1,
        "task_id": "cpu-fixture",
        "cases": [
            {"id": "small", "weight": 1.0, "input": {"seed": 13}, "parameters": {"length": 17}},
            {"id": "larger", "weight": 2.0, "input": {"seed": 31}, "parameters": {"length": 4096}},
        ],
        "commands": {
            "build": {"argv": _command("build"), "cpu_only": True, "timeout_seconds": 30},
            "validate": {"argv": _command(validation_mode), "timeout_seconds": 30},
            "benchmark": {"argv": _command("benchmark"), "timeout_seconds": 30},
        },
        "trusted_inputs": [{"id": "cpu_fixture_driver", "path": str(DRIVER), "role": "harness"}],
        "numerical_requirements": {
            "description": "fixture validator compares candidate output exactly with an independent math.fsum reference"
        },
        "probe": {"argv": _command(probe_mode), "timeout_seconds": 10},
        "timing": {
            "metric": "synthetic_test_cost",
            "unit": "fixture_unit",
            "direction": "minimize",
            "warmup": 1,
            "repetitions": 2,
            "rounds": 2,
            "confirmation_rounds": 2,
            "seed": 19,
            "scope": "testing-only synthetic fixed values; no performance claim",
        },
        "promotion": {
            "min_improvement": 0.05,
            "max_regression": 0.0,
            "confidence": 0.95,
            "bootstrap_samples": 250,
        },
        "target": {"kind": "cpu", "architecture": "cpu-test"},
        "toolchain": {},
        "execution": {"mode": "direct"},
        "budgets": {"max_candidates": 8, "max_build_jobs": 2, "max_seconds": 300},
    }
    (root / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return root


def source_dir(workspace: str | pathlib.Path, candidate_id: str) -> pathlib.Path:
    return pathlib.Path(workspace) / "candidate-sources" / candidate_id


def manifest_path(workspace: str | pathlib.Path, candidate_id: str) -> pathlib.Path:
    path = pathlib.Path(workspace) / f"{candidate_id}.manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "files": ["kernel.py"], "dependencies": []}, indent=2) + "\n",
                    encoding="utf-8")
    return path
