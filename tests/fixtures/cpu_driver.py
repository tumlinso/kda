"""Trusted evaluator for the CPU-only CLI integration fixture.

The benchmark values produced here are deterministic test inputs, not timing
measurements. This driver is deliberately outside each candidate snapshot.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import pathlib
import random
import sys
import py_compile
import os


def _read(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _write(path: str, value: dict) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _audit(event: str, request: dict) -> None:
    """Append optional test observations outside the task and candidate trees."""
    audit_path = os.environ.get("KDA_FIXTURE_AUDIT")
    if audit_path:
        record = {"event": event, "request_id": request.get("request_id")}
        candidate = request.get("candidate", {})
        if candidate:
            record["candidate_id"] = candidate.get("id")
        case = request.get("case")
        if case:
            record["case_id"] = case.get("id")
        target = pathlib.Path(audit_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")


def _candidate(request: dict):
    source_dir = pathlib.Path(request["candidate"]["source_dir"])
    source = source_dir / "kernel.py"
    spec = importlib.util.spec_from_file_location("fixture_candidate", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate source: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _values(case: dict) -> list[float]:
    seed = int(case["input"]["seed"])
    count = int(case["parameters"]["length"])
    rng = random.Random(seed)
    # Integer-valued floats keep the simple sum exactly representable while
    # still exercising a floating-point operation with independent reference.
    return [float(rng.randrange(-1000, 1001)) for _ in range(count)]


def _probe(request_path: str, result_path: str, *, mismatch: bool = False) -> None:
    request = _read(request_path)
    _write(result_path, {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": "ok",
        "environment": {
            "kind": "cpu-test",
            "architecture": "other-cpu" if mismatch else "cpu-test",
            "tools": {"python": sys.version.split()[0]},
        },
    })


def _probe_interrupt_once(request_path: str, result_path: str) -> None:
    import os

    _probe(request_path, result_path)
    marker = pathlib.Path(os.environ["KDA_FIXTURE_INTERRUPT_ONCE"])
    if not marker.exists():
        request = _read(request_path)
        marker.write_text(request["request_id"] + "\n", encoding="utf-8")
        raise SystemExit(74)


def _build(request_path: str, result_path: str) -> None:
    request = _read(request_path)
    if request["candidate"]["id"] == "broken-build":
        _write(result_path, {
            "schema_version": 1,
            "request_id": request["request_id"],
            "status": "error",
            "artifacts": [],
        })
        return
    source = pathlib.Path(request["candidate"]["source_dir"]) / "kernel.py"
    build_dir = pathlib.Path(request["build"]["directory"])
    artifact = build_dir / "kernel.pyc"
    build_dir.mkdir(parents=True, exist_ok=True)
    py_compile.compile(str(source), cfile=str(artifact), doraise=True)
    relative = artifact.relative_to(build_dir).as_posix()
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    _write(result_path, {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": "ok",
        "artifacts": [{"path": relative, "sha256": digest}],
    })


def _validate(request_path: str, result_path: str) -> None:
    request = _read(request_path)
    module = _candidate(request)
    rows = []
    for case in request["cases"]:
        values = _values(case)
        actual = module.compute(values)
        expected = math.fsum(values)
        passed = math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.0)
        rows.append({
            "case_id": case["id"],
            "workload_sha256": case["workload_sha256"],
            "status": "pass" if passed else "fail",
        })
    _write(result_path, {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": "ok",
        "cases": rows,
    })


def _validate_top_error(request_path: str, result_path: str) -> None:
    request = _read(request_path)
    _validate(request_path, result_path)
    result = _read(result_path)
    result["status"] = "error"
    _write(result_path, result)


def _benchmark(request_path: str, result_path: str) -> None:
    request = _read(request_path)
    _audit("benchmark", request)
    candidate_id = request["candidate"]["id"]
    case = request["case"]
    # These values are fixed selection-test inputs. No clock or kernel is timed.
    values = {
        "baseline": [10.0, 10.0],
        "fast": [8.0, 8.0],
        "bad": [1.0, 1.0],
        "slow": [12.0, 12.0],
        "broken-build": [7.0, 7.0],
    }[candidate_id]
    _write(result_path, {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": "ok",
        "case_id": case["id"],
        "workload_sha256": case["workload_sha256"],
        "timing_scope": "testing-only synthetic fixed values; no performance claim",
        "metric": request["timing"]["metric"],
        "unit": request["timing"]["unit"],
        "warmup": request["timing"]["warmup"],
        "repetitions": request["timing"]["repetitions"],
        "samples": values,
    })


def _malformed_benchmark(request_path: str, result_path: str, mode: str) -> None:
    request = _read(request_path)
    case = request["case"]
    sample = [float("nan"), 1.0] if mode == "nonfinite" else [1.0, 1.0]
    response = {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": "ok",
        "case_id": case["id"],
        "workload_sha256": case["workload_sha256"],
        "timing_scope": request["timing"]["scope"],
        "metric": request["timing"]["metric"],
        "unit": request["timing"]["unit"],
        "warmup": request["timing"]["warmup"],
        "repetitions": request["timing"]["repetitions"],
        "samples": sample,
    }
    if mode in {"wrong-case", "wrong_case"}:
        response["case_id"] = "unexpected-case"
    elif mode == "shrunk":
        response["workload_sha256"] = "0" * 64
    elif mode == "stale":
        response["request_id"] = "stale-request-id"
    elif mode == "wrong-metric":
        response["metric"] = "different-metric"
    elif mode == "wrong-unit":
        response["unit"] = "different-unit"
    elif mode == "top-error":
        response["status"] = "error"
    _audit("benchmark", request)
    _write(result_path, response)


def _interrupt_once(request_path: str, result_path: str) -> None:
    """Write a plausible result then fail once, testing attempt isolation."""
    import os

    request = _read(request_path)
    _benchmark(request_path, result_path)
    marker = pathlib.Path(os.environ["KDA_FIXTURE_INTERRUPT_ONCE"])
    if not marker.exists():
        marker.write_text(request["request_id"] + "\n", encoding="utf-8")
        raise SystemExit(74)


def _mutate_result(request_path: str, result_path: str, mode: str) -> None:
    """Test hook for adversarial protocol tests; never enabled in demo task."""
    request = _read(request_path)
    case = request["cases"][0]
    rows = [{
        "case_id": item["id"],
        "workload_sha256": item["workload_sha256"],
        "status": "pass",
    } for item in request["cases"]]
    if mode == "missing":
        rows.pop()
    elif mode == "duplicate":
        rows.append(dict(rows[0]))
    elif mode == "oom" or mode == "unsupported":
        rows[0]["status"] = mode
    elif mode == "wrong_digest":
        rows[0]["workload_sha256"] = "0" * 64
    elif mode == "wrong_request":
        request_id = "stale-request-id"
    else:
        request_id = request["request_id"]
    _write(result_path, {
        "schema_version": 1,
        "request_id": locals().get("request_id", request["request_id"]),
        "status": "ok",
        "cases": rows,
    })


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "print-compiler-target":
        print(argv[2])
        return 0
    if len(argv) < 4:
        raise SystemExit("usage: cpu_driver.py MODE REQUEST RESULT [MUTATION]")
    mode, request_path, result_path = argv[1:4]
    if mode == "probe" or mode == "probe-mismatch":
        _probe(request_path, result_path, mismatch=(mode == "probe-mismatch"))
    elif mode == "probe-interrupt-once":
        _probe_interrupt_once(request_path, result_path)
    elif mode == "build":
        _build(request_path, result_path)
    elif mode == "validate":
        _validate(request_path, result_path)
    elif mode == "validate-top-error":
        _validate_top_error(request_path, result_path)
    elif mode.startswith("validate-attack-"):
        request = _read(request_path)
        if request["candidate"]["id"] == "baseline":
            _validate(request_path, result_path)
        else:
            _mutate_result(request_path, result_path, mode.removeprefix("validate-attack-"))
    elif mode == "benchmark":
        _benchmark(request_path, result_path)
    elif mode.startswith("benchmark-attack-"):
        request = _read(request_path)
        if request["candidate"]["id"] == "baseline":
            _benchmark(request_path, result_path)
        else:
            _malformed_benchmark(request_path, result_path, mode.removeprefix("benchmark-attack-"))
    elif mode in {"benchmark-nonfinite", "benchmark-wrong-case", "benchmark-shrunk"}:
        _malformed_benchmark(request_path, result_path, mode.removeprefix("benchmark-"))
    elif mode in {"benchmark-stale", "benchmark-wrong-metric", "benchmark-wrong-unit", "benchmark-top-error"}:
        _malformed_benchmark(request_path, result_path, mode.removeprefix("benchmark-"))
    elif mode == "benchmark-interrupt-once":
        _interrupt_once(request_path, result_path)
    elif mode == "mutate-validation":
        _mutate_result(request_path, result_path, argv[4])
    else:
        raise SystemExit(f"unknown fixture mode: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
