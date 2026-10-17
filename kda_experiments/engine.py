"""Candidate preparation, correctness gates, paired benchmarking, and promotion."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    canonical_json,
    comparison_group as base_comparison_group,
    digest_file,
    digest_json,
    digest_tree,
    load_json,
    load_task,
    trusted_input_identities,
    validate_benchmark_response,
    validate_cases_response,
    validate_envelope,
    workload_descriptor,
)
from .errors import ContractError, ExecutionError, IntegrityError, KDAExperimentError
from .runner import (
    invoke_external_launcher,
    invoke_task_command,
    remaining_seconds,
    resolve_command_executable,
    run_compiler_target_probe,
)
from .selection import confirm, rank
from .store import (
    append_benchmark,
    append_jsonl,
    atomic_write_json,
    candidate_records,
    candidates_by_id,
    compare_and_write_preferred,
    ensure_layout,
    list_attempts,
    preferred_path,
    read_attempt,
    read_candidate_manifest,
    read_jsonl,
    read_preferred,
    register_candidate as store_register_candidate,
    verify_snapshot,
    workspace_lock,
    workspace_paths,
)


PACKAGE_ROOT = Path(__file__).resolve().parent


def package_fingerprint() -> str:
    files = sorted(PACKAGE_ROOT.glob("*.py"))
    entries = [{"path": file.name, "sha256": digest_file(file)} for file in files]
    return digest_json(entries)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command_identities(
    task: Mapping[str, Any], task_dir: Path, launcher_dir: Path | None = None,
) -> dict[str, Any]:
    identities: dict[str, Any] = {}
    for name, command in task["commands"].items():
        identities[name] = resolve_command_executable(command["argv"], task_dir)
    identities["probe"] = resolve_command_executable(task["probe"]["argv"], task_dir)
    if task["execution"]["mode"] == "launcher":
        identities["launcher"] = resolve_command_executable(
            task["execution"]["launcher_argv"], launcher_dir or task_dir,
        )
    tool_probe = task.get("toolchain", {}).get("compiler_target_probe_argv")
    if tool_probe:
        identities["compiler_target_probe"] = resolve_command_executable(tool_probe, task_dir)
    return identities


def _verify_command_identities(
    task: Mapping[str, Any], task_dir: Path, expected: Mapping[str, Any],
    launcher_dir: Path | None = None,
) -> None:
    if digest_json(_command_identities(task, task_dir, launcher_dir)) != digest_json(expected):
        raise IntegrityError("selected command executable changed during preparation or evaluation")


def _candidate_build_ref(workspace: Path, candidate: Mapping[str, Any], build_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("status") != "ok":
        raise IntegrityError(f"candidate build is not complete: {candidate['candidate_id']}")
    if manifest.get("candidate_id") != candidate["candidate_id"] or manifest.get("snapshot_sha256") != candidate["snapshot_sha256"]:
        raise IntegrityError("build manifest belongs to another candidate snapshot")
    if manifest.get("build_fingerprint") != build_dir.parent.name:
        raise IntegrityError("build manifest fingerprint does not match its immutable build path")
    candidate_build_root = workspace_paths(workspace)["builds"] / candidate["candidate_id"]
    if build_dir.is_symlink() or not build_dir.resolve(strict=True).is_relative_to(candidate_build_root.resolve(strict=True)):
        raise IntegrityError("build directory escapes its candidate build root")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise IntegrityError("build manifest has no artifact list")
    for artifact in artifacts:
        relative = Path(artifact["path"])
        raw_path = build_dir / relative
        if relative.is_absolute() or ".." in relative.parts or raw_path.is_symlink():
            raise IntegrityError(f"invalid build artifact path: {artifact.get('path')}")
        path = raw_path.resolve(strict=True)
        if not path.is_relative_to(build_dir.resolve(strict=True)) or not path.is_file():
            raise IntegrityError(f"invalid build artifact path: {artifact.get('path')}")
        if digest_file(path) != artifact.get("sha256"):
            raise IntegrityError(f"build artifact changed: {artifact['path']}")
    return {
        "directory": str(build_dir.resolve()),
        "fingerprint": manifest["build_fingerprint"],
        "task_contract_sha256": manifest.get("task_contract_sha256"),
        "artifacts": [dict(item) for item in artifacts],
        "manifest_path": str((build_dir / "build.json").resolve()),
        "manifest_sha256": digest_file(build_dir / "build.json"),
    }


def _readonly_artifacts(build_dir: Path, artifacts: list[dict[str, str]]) -> None:
    for artifact in artifacts:
        path = build_dir / artifact["path"]
        if path.is_file():
            path.chmod(path.stat().st_mode & ~0o222)


def _find_cached_build(workspace: Path, candidate: Mapping[str, Any], build_fingerprint: str) -> dict[str, Any] | None:
    root = workspace_paths(workspace)["builds"] / candidate["candidate_id"] / build_fingerprint
    if not root.exists():
        return None
    for folder in sorted(root.iterdir(), reverse=True):
        manifest_path = folder / "build.json"
        if folder.is_symlink() or not folder.is_dir() or not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            manifest = load_json(manifest_path)
            return _candidate_build_ref(workspace, candidate, folder, manifest)
        except (OSError, KDAExperimentError, KeyError, TypeError):
            continue
    return None


def _build_fingerprint(
    task: Mapping[str, Any],
    candidate: Mapping[str, Any],
    task_dir: Path,
    command_identities: Mapping[str, Any],
    trusted: list[dict[str, Any]],
    engine_hash: str,
    compiler_target_probe: Mapping[str, Any],
    task_hash: str,
) -> str:
    return digest_json({
        "candidate_id": candidate["candidate_id"],
        "task_contract_sha256": task_hash,
        "snapshot_sha256": candidate["snapshot_sha256"],
        "dependencies": candidate.get("dependencies", []),
        "build_command": task["commands"]["build"]["argv"],
        "build_executable": command_identities["build"],
        "trusted_inputs": trusted,
        "target": task["target"],
        "toolchain": task.get("toolchain", {}),
        "compiler_target_probe": compiler_target_probe,
        "engine_fingerprint": engine_hash,
    })


def _build_candidate(
    workspace: Path,
    task: Mapping[str, Any],
    task_path: Path,
    task_dir: Path,
    candidate: Mapping[str, Any],
    command_identities: Mapping[str, Any],
    trusted: list[dict[str, Any]],
    engine_hash: str,
    compiler_target_probe: Mapping[str, Any],
    task_hash: str,
    deadline: float,
) -> dict[str, Any]:
    snapshot = verify_snapshot(candidate)
    if digest_file(task_path) != task_hash:
        raise IntegrityError("task contract changed before candidate build")
    _verify_command_identities(task, task_dir, command_identities, workspace)
    fingerprint = _build_fingerprint(
        task, candidate, task_dir, command_identities, trusted, engine_hash,
        compiler_target_probe, task_hash,
    )
    cached = _find_cached_build(workspace, candidate, fingerprint)
    if cached:
        return {"candidate_id": candidate["candidate_id"], "status": "ok", "cached": True, **cached}
    paths = workspace_paths(workspace)
    build_id = uuid.uuid4().hex
    build_dir = paths["builds"] / candidate["candidate_id"] / fingerprint / build_id
    build_dir.mkdir(parents=True, exist_ok=False)
    command_stage = build_dir / "command"
    request = {
        "operation": "build",
        "task_id": task["task_id"],
        "target": task["target"],
        "candidate": {
            "id": candidate["candidate_id"],
            "snapshot_sha256": candidate["snapshot_sha256"],
            "source_dir": str(snapshot),
            "dependencies": candidate.get("dependencies", []),
        },
        "build": {"directory": str(build_dir.resolve())},
    }
    try:
        result, process, response_identity = invoke_task_command(
            task["commands"]["build"], request, cwd=task_dir,
            stage_dir=command_stage, deadline=deadline, label=f"build {candidate['candidate_id']}",
        )
        if digest_file(task_path) != task_hash:
            raise IntegrityError("task contract changed during candidate build")
        _verify_command_identities(task, task_dir, command_identities, workspace)
        if package_fingerprint() != engine_hash:
            raise IntegrityError("KDA experiment engine changed during build")
        if result.get("status") != "ok":
            raise ExecutionError(f"build response reports status {result.get('status')!r}")
        artifacts_value = result.get("artifacts")
        if not isinstance(artifacts_value, list):
            raise ContractError("build response artifacts must be an array")
        artifacts: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, item in enumerate(artifacts_value):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
                raise ContractError(f"build artifact {index} must have path and sha256")
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ContractError(f"build artifact path must be relative to build directory: {item['path']}")
            if item["path"] in seen:
                raise ContractError(f"duplicate build artifact path: {item['path']}")
            seen.add(item["path"])
            artifact_path = build_dir / relative
            if artifact_path.is_symlink() or not artifact_path.is_file():
                raise IntegrityError(f"build artifact is missing or not a regular file: {item['path']}")
            actual = digest_file(artifact_path)
            if actual != item["sha256"]:
                raise IntegrityError(f"build artifact hash mismatch: {item['path']}")
            artifacts.append({"path": relative.as_posix(), "sha256": actual})
        if not artifacts:
            raise ContractError("successful build must produce at least one declared artifact")
        manifest = {
            "schema_version": 1, "status": "ok", "candidate_id": candidate["candidate_id"],
            "task_contract_sha256": task_hash,
            "snapshot_sha256": candidate["snapshot_sha256"], "build_fingerprint": fingerprint,
            "candidate_dependencies": candidate.get("dependencies", []), "artifacts": artifacts,
            "request_id": process["request_id"], "request_path": process["request_path"],
            "response_sha256": response_identity["sha256"], "command": process,
            "compiler_target_probe": dict(compiler_target_probe),
            "engine_fingerprint": engine_hash, "completed_at": _utc_now(),
        }
        _readonly_artifacts(build_dir, artifacts)
        manifest_path = build_dir / "build.json"
        atomic_write_json(manifest_path, manifest)
        manifest_path.chmod(manifest_path.stat().st_mode & ~0o222)
        ref = _candidate_build_ref(workspace, candidate, build_dir, manifest)
        return {"candidate_id": candidate["candidate_id"], "status": "ok", "cached": False, **ref}
    except Exception as exc:
        failure = {
            "schema_version": 1, "status": "error", "candidate_id": candidate["candidate_id"],
            "snapshot_sha256": candidate["snapshot_sha256"], "build_fingerprint": fingerprint,
            "reason": f"{type(exc).__name__}: {exc}", "failed_at": _utc_now(),
            "engine_fingerprint": engine_hash,
        }
        try:
            failure_path = build_dir / "failure.json"
            atomic_write_json(failure_path, failure)
            failure_path.chmod(failure_path.stat().st_mode & ~0o222)
        except IntegrityError:
            pass
        return {"candidate_id": candidate["candidate_id"], "status": "error", "build_fingerprint": fingerprint, "reason": failure["reason"], "build_dir": str(build_dir)}


def prepare_candidates(
    task_path: os.PathLike[str] | str,
    workspace: os.PathLike[str] | str,
    candidate_ids: list[str],
    *,
    jobs: int = 1,
    compiler_target_probe: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    task, resolved_task = load_task(task_path)
    task_hash = digest_file(resolved_task)
    if not candidate_ids:
        raise ContractError("prepare requires at least one candidate id")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ContractError("prepare candidate ids must be unique")
    if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs < 1 or jobs > task["budgets"]["max_build_jobs"]:
        raise ContractError(f"jobs must be between 1 and task budgets.max_build_jobs ({task['budgets']['max_build_jobs']})")
    deadline = time.monotonic() + task["budgets"]["max_seconds"]
    workspace_path = Path(workspace).resolve()
    paths = ensure_layout(workspace_path)
    by_id = candidates_by_id(workspace_path)
    missing = set(candidate_ids) - set(by_id)
    if missing:
        raise ContractError(f"unknown candidate ids: {sorted(missing)}")
    candidates = [by_id[candidate_id] for candidate_id in candidate_ids]
    for candidate in candidates:
        verify_snapshot(candidate)
    trusted = trusted_input_identities(task)
    identities = _command_identities(task, resolved_task.parent, workspace_path)
    engine_hash = package_fingerprint()
    if compiler_target_probe is None:
        compiler_target_probe = run_compiler_target_probe(
            task, task_dir=resolved_task.parent, deadline=deadline,
            evidence_dir=workspace_paths(workspace_path)["runs"] / "preflight" / uuid.uuid4().hex,
        )
    compiler_record = dict(compiler_target_probe)
    expected_compiler_target = task["target"].get("compiler_target", task["target"]["architecture"])
    probe_argv = task["toolchain"].get("compiler_target_probe_argv", [])
    if compiler_record.get("argv") != probe_argv or compiler_record.get("target") != expected_compiler_target:
        raise IntegrityError("compiler target probe does not match the task toolchain contract")
    if probe_argv:
        expected_executable = resolve_command_executable(probe_argv, resolved_task.parent)
        if compiler_record.get("executable") != expected_executable:
            raise IntegrityError("compiler executable changed since compiler target probe")
        stdout = compiler_record.get("stdout")
        if not isinstance(stdout, str) or compiler_record.get("stdout_sha256") != hashlib.sha256(stdout.encode("utf-8")).hexdigest():
            raise IntegrityError("compiler target probe stdout hash is missing or invalid")
        supports_target = expected_compiler_target in stdout.split()
        if compiler_record.get("supported") is not supports_target:
            raise IntegrityError("compiler target probe support result disagrees with its exact output")
    if task["target"]["kind"] == "cuda":
        if compiler_record.get("target") != expected_compiler_target or compiler_record.get("supported") is not True:
            raise IntegrityError("compiler target probe does not confirm the declared CUDA compiler target")
    if digest_file(resolved_task) != task_hash:
        raise IntegrityError("task contract changed during compiler preflight")
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        future_map = {
            pool.submit(
                _build_candidate, workspace_path, task, resolved_task,
                resolved_task.parent,
                candidate, identities, trusted, engine_hash, compiler_record,
                task_hash, deadline,
            ): candidate["candidate_id"]
            for candidate in candidates
        }
        for future in as_completed(future_map):
            candidate_id = future_map[future]
            try:
                results[candidate_id] = future.result()
            except Exception as exc:
                results[candidate_id] = {"candidate_id": candidate_id, "status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if digest_file(resolved_task) != task_hash:
        raise IntegrityError("task contract changed during candidate preparation")
    if package_fingerprint() != engine_hash:
        raise IntegrityError("KDA experiment engine changed during candidate preparation")
    _verify_command_identities(task, resolved_task.parent, identities, workspace_path)
    return [results[candidate_id] for candidate_id in candidate_ids]


def _read_build_ref(workspace: Path, candidate: Mapping[str, Any], build_record: Mapping[str, Any]) -> dict[str, Any]:
    raw_path = Path(build_record["directory"])
    if raw_path.is_symlink():
        raise IntegrityError("build directory is a symlink")
    path = raw_path.resolve(strict=True)
    if not path.is_dir():
        raise IntegrityError("build directory is missing or changed")
    manifest_path = path / "build.json"
    if digest_file(manifest_path) != build_record["manifest_sha256"]:
        raise IntegrityError("build manifest changed since preparation")
    manifest = load_json(manifest_path)
    checked = _candidate_build_ref(workspace, candidate, path, manifest)
    if checked["fingerprint"] != build_record.get("fingerprint"):
        raise IntegrityError("build fingerprint changed since preparation")
    if checked.get("task_contract_sha256") != build_record.get("task_contract_sha256"):
        raise IntegrityError("build task contract identity changed since preparation")
    return checked


def _copy_trusted_inputs(task: Mapping[str, Any], attempt_dir: Path) -> tuple[list[dict[str, Any]], Path]:
    source_identities = trusted_input_identities(task)
    root = attempt_dir / "trusted-inputs"
    root.mkdir(parents=True, exist_ok=True)
    copied = []
    by_id = {item["id"]: item for item in source_identities}
    for item in task["trusted_inputs"]:
        source = Path(item["path"])
        target = root / item["id"]
        original = by_id[item["id"]]
        if source.is_dir():
            shutil.copytree(source, target, symlinks=False)
            copied_hash, entries = digest_tree(target)
            if copied_hash != original["sha256"]:
                raise IntegrityError(f"trusted input changed while snapshotting: {item['id']}")
            copied.append({"id": item["id"], "role": item["role"], "sha256": copied_hash, "files": entries, "snapshot_dir": str(target)})
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied_hash = digest_file(target)
            if copied_hash != original["sha256"]:
                raise IntegrityError(f"trusted input changed while snapshotting: {item['id']}")
            target.chmod(target.stat().st_mode & ~0o222)
            copied.append({"id": item["id"], "role": item["role"], "sha256": copied_hash, "snapshot_path": str(target)})
    atomic_write_json(root / "manifest.json", {"schema_version": 1, "inputs": copied})
    return source_identities, root


def _compare_trusted_before_after(before: list[dict[str, Any]], task: Mapping[str, Any]) -> bool:
    after = trusted_input_identities(task)
    return digest_json(before) == digest_json(after)


def _engine_identity_check(expected: str, task_path: Path, expected_task_hash: str) -> bool:
    return package_fingerprint() == expected and digest_file(task_path) == expected_task_hash


def _normalize_environment(environment: Any, task: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(environment, dict) or not environment:
        raise ContractError("probe result environment must be a non-empty object")
    if not isinstance(environment.get("tools"), dict):
        raise ContractError("probe environment must include selected tool versions in a tools object")
    actual_arch = environment.get("architecture")
    if not actual_arch and isinstance(environment.get("compute_capability"), str):
        digits = environment["compute_capability"].replace(".", "")
        if digits.isdigit():
            actual_arch = "sm_" + digits
    target = task["target"]
    declared = target["architecture"]
    if target["kind"] == "cuda" and actual_arch != declared:
        raise ExecutionError(f"actual GPU architecture {actual_arch!r} does not match requested physical target {declared!r}")
    if target["kind"] == "cpu" and environment.get("kind") not in {"cpu", "cpu-test"}:
        raise ExecutionError("CPU task probe must identify a CPU execution environment")
    if target["kind"] == "cpu" and actual_arch and declared != actual_arch:
        raise ExecutionError(f"actual target {actual_arch!r} does not match declared target {declared!r}")
    if target["kind"] == "cuda":
        device = environment.get("device")
        uuid_value = environment.get("device_uuid")
        if isinstance(device, dict):
            uuid_value = uuid_value or device.get("uuid")
        if not isinstance(uuid_value, str) or not uuid_value:
            raise ContractError("GPU probe environment must report device_uuid")
        for field in ("driver_version", "runtime_version"):
            if not isinstance(environment.get(field), str) or not environment[field]:
                raise ContractError(f"GPU probe environment must report {field}")
    return environment


def _case_list(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [workload_descriptor(case) for case in task["cases"]]


def _case_component(case_id: str) -> str:
    return hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:20]


def _candidate_request(candidate: Mapping[str, Any], build: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate["candidate_id"],
        "snapshot_sha256": candidate["snapshot_sha256"],
        "source_dir": candidate["snapshot_dir"],
        "dependencies": candidate.get("dependencies", []),
        "experiment_group": candidate.get("experiment_group"),
        "parent_id": candidate.get("parent_id"),
        "build": {key: build[key] for key in ("directory", "fingerprint", "artifacts")},
    }


def _verify_candidate_artifacts(
    workspace: Path,
    candidate: Mapping[str, Any],
    build: Mapping[str, Any],
) -> None:
    verify_snapshot(candidate)
    checked = _read_build_ref(workspace, candidate, build)
    if checked["manifest_sha256"] != build.get("manifest_sha256"):
        raise IntegrityError(f"candidate build identity changed: {candidate['candidate_id']}")


def _validate_one_candidate(
    workspace: Path, task: Mapping[str, Any], task_path: Path, attempt_dir: Path, candidate: Mapping[str, Any],
    build: Mapping[str, Any], environment: Mapping[str, Any], deadline: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stage_dir = attempt_dir / "stages" / candidate["candidate_id"] / "validation"
    case_list = _case_list(task)
    request = {
        "operation": "validate", "task_id": task["task_id"], "target": task["target"],
        "candidate": _candidate_request(candidate, build), "cases": case_list,
        "numerical_requirements": task["numerical_requirements"],
        "environment": environment,
    }
    try:
        _verify_candidate_artifacts(workspace, candidate, build)
        response, process, identity = invoke_task_command(
            task["commands"]["validate"], request, cwd=task_path.parent,
            stage_dir=stage_dir, deadline=deadline, label=f"validate {candidate['candidate_id']}",
        )
        _verify_candidate_artifacts(workspace, candidate, build)
        response = validate_cases_response(response, process["request_id"], case_list)
        statuses = {row["case_id"]: row["status"] for row in response["cases"]}
        valid = response["status"] == "ok" and all(status == "pass" for status in statuses.values())
        result = {
            "candidate_id": candidate["candidate_id"], "status": "pass" if valid else "fail",
            "case_status": statuses, "response": response, "process": process,
            "response_sha256": identity["sha256"],
            "reason": None if valid else "one or more required correctness cases did not pass",
            "input_fingerprint": digest_json({"task": task["task_id"], "cases": case_list, "candidate": candidate["snapshot_sha256"], "build": build["manifest_sha256"], "environment": environment, "numerical_requirements": task["numerical_requirements"]}),
        }
        return result, {"process": process, "response": response}
    except Exception as exc:
        return {
            "candidate_id": candidate["candidate_id"], "status": "fail", "case_status": {},
            "reason": f"{type(exc).__name__}: {exc}",
            "input_fingerprint": digest_json({"task": task["task_id"], "cases": case_list, "candidate": candidate["snapshot_sha256"], "build": build.get("manifest_sha256"), "environment": environment}),
        }, {"error": f"{type(exc).__name__}: {exc}"}


def _record_timing(
    workspace: Path, task: Mapping[str, Any], attempt_id: str, candidate_id: str,
    phase: str, case: Mapping[str, Any], round_number: int, environment_fp: str,
    response: Mapping[str, Any], process: Mapping[str, Any],
) -> None:
    samples = list(response["samples"])
    ordered = sorted(samples)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2
    append_benchmark(workspace, {
        "run_id": attempt_id, "candidate_id": candidate_id, "phase": phase,
        "case_id": case["id"], "round": round_number, "metric": task["timing"]["metric"],
        "unit": task["timing"]["unit"], "direction": task["timing"]["direction"],
        "samples_json": canonical_json(samples), "median": median,
        "workload_sha256": case["workload_sha256"], "environment_fingerprint": environment_fp,
        "result_path": process["result_path"], "result_sha256": process["result_sha256"],
    })


def _benchmark_matrix(
    *, workspace: Path, task: Mapping[str, Any], task_path: Path, attempt_dir: Path,
    attempt_id: str, candidates: Mapping[str, Mapping[str, Any]], builds: Mapping[str, Mapping[str, Any]],
    candidate_ids: list[str], environment: Mapping[str, Any], environment_fp: str, deadline: float,
    phase: str, rounds: int, seed: int,
) -> tuple[dict[str, list[dict[str, list[float]]]], dict[str, str], list[dict[str, Any]]]:
    cases = _case_list(task)
    round_data: dict[str, list[dict[str, list[float]]]] = {candidate_id: [] for candidate_id in candidate_ids}
    failures: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    rng = random.Random(seed)
    for round_index in range(rounds):
        round_values = {candidate_id: {case["id"]: [] for case in cases} for candidate_id in candidate_ids}
        jobs = [(candidate_id, case) for case in cases for candidate_id in candidate_ids if candidate_id not in failures]
        rng.shuffle(jobs)
        for candidate_id, case in jobs:
            if candidate_id in failures:
                continue
            stage = attempt_dir / "stages" / candidate_id / phase / f"round-{round_index:03d}" / _case_component(case["id"])
            request = {
                "operation": "benchmark", "task_id": task["task_id"], "target": task["target"],
                "candidate": _candidate_request(candidates[candidate_id], builds[candidate_id]),
                "case": case, "timing": task["timing"], "phase": phase,
                "round": round_index, "environment": environment,
            }
            try:
                _verify_candidate_artifacts(workspace, candidates[candidate_id], builds[candidate_id])
                raw, process, identity = invoke_task_command(
                    task["commands"]["benchmark"], request, cwd=task_path.parent,
                    stage_dir=stage, deadline=deadline, label=f"benchmark {candidate_id}/{phase}/{case['id']} round {round_index}",
                )
                _verify_candidate_artifacts(workspace, candidates[candidate_id], builds[candidate_id])
                response = validate_benchmark_response(raw, process["request_id"], case, task["timing"])
                if response["status"] != "ok":
                    raise ExecutionError("benchmark response reports status error")
                round_values[candidate_id][case["id"]] = response["samples"]
                _record_timing(workspace, task, attempt_id, candidate_id, phase, case, round_index, environment_fp, response, process)
                records.append({"candidate_id": candidate_id, "case_id": case["id"], "round": round_index, "phase": phase, "response_sha256": identity["sha256"], "request_id": process["request_id"]})
            except Exception as exc:
                failures[candidate_id] = f"{type(exc).__name__}: {exc}"
                records.append({"candidate_id": candidate_id, "case_id": case["id"], "round": round_index, "phase": phase, "status": "error", "reason": failures[candidate_id]})
        for candidate_id in candidate_ids:
            if candidate_id not in failures:
                if any(not round_values[candidate_id][case["id"]] for case in cases):
                    failures[candidate_id] = "round did not complete all required workload cases"
                else:
                    round_data[candidate_id].append(round_values[candidate_id])
        if failures.get(next((candidate_id for candidate_id, record in candidates.items() if record.get("baseline")), "")):
            break
    return round_data, failures, records


def _direct_or_launched_worker(task: Mapping[str, Any], batch_request: Mapping[str, Any], *, task_path: Path, workspace: Path, attempt_dir: Path, deadline: float) -> dict[str, Any]:
    worker_result_path = attempt_dir / "worker-result.json"
    if task["execution"]["mode"] == "direct":
        result = execute_batch_worker(batch_request, task_path=task_path, workspace=workspace, deadline=deadline)
        atomic_write_json(worker_result_path, result)
        return result
    worker_request_path = attempt_dir / "worker-request.json"
    atomic_write_json(worker_request_path, dict(batch_request))
    worker_argv = [
        sys.executable, "-m", "kda_experiments", "_worker",
        "--task", str(task_path), "--workspace", str(workspace),
        "--batch-request", str(worker_request_path), "--batch-result", str(worker_result_path),
    ]
    receipt = invoke_external_launcher(
        task, worker_argv, cwd=workspace, worker_result_path=worker_result_path,
        stage_dir=attempt_dir, deadline=deadline,
    )
    result = load_json(worker_result_path)
    if not isinstance(result, dict) or result.get("request_id") != batch_request["request_id"]:
        raise IntegrityError("worker result request_id does not match the launcher batch")
    result["launcher_receipt"] = receipt
    return result


def _finalize_worker_result(
    worker_result: Mapping[str, Any], batch_request: Mapping[str, Any],
    *, task: Mapping[str, Any], task_path: Path, workspace: Path, attempt_dir: Path,
) -> dict[str, Any]:
    """Publish evidence and conditionally promote only after worker receipt checks."""
    run_id = batch_request["run_id"]
    request_id = batch_request["request_id"]
    if worker_result.get("schema_version") != 1 or worker_result.get("status") != "complete":
        raise IntegrityError("worker did not return a successful schema-versioned result")
    if worker_result.get("request_id") != request_id or worker_result.get("run_id") != run_id:
        raise IntegrityError("worker result request_id or run_id does not match the admitted batch")
    provisional_path = attempt_dir / "worker-summary.json"
    if Path(worker_result.get("summary_path", "")).resolve() != provisional_path.resolve():
        raise IntegrityError("worker summary path does not match this attempt")
    if not provisional_path.is_file() or provisional_path.is_symlink() or digest_file(provisional_path) != worker_result.get("summary_sha256"):
        raise IntegrityError("worker summary is missing or its hash does not match the response")
    provisional = load_json(provisional_path)
    if provisional.get("status") != "worker_complete" or provisional.get("run_id") != run_id or provisional.get("request_id") != request_id:
        raise IntegrityError("worker summary identity does not match the admitted batch")
    if provisional.get("task_sha256") != digest_file(task_path) or provisional.get("engine_fingerprint") != package_fingerprint():
        raise IntegrityError("task or engine changed before parent accepted the worker result")
    if not provisional.get("trusted_inputs_unchanged") or not provisional.get("tools_unchanged"):
        raise IntegrityError("worker detected changed trusted inputs or selected tools")
    current_task, current_task_path = load_task(task_path)
    if digest_json(trusted_input_identities(current_task)) != digest_json(provisional.get("trusted_inputs")):
        raise IntegrityError("trusted inputs changed after worker completion and before result acceptance")
    if digest_json(_command_identities(current_task, current_task_path.parent, workspace)) != digest_json(provisional.get("command_identities")):
        raise IntegrityError("selected command executable changed after worker completion and before result acceptance")
    if task["execution"]["mode"] == "launcher":
        receipt = worker_result.get("launcher_receipt")
        if not isinstance(receipt, dict) or receipt.get("status") != "ok" or receipt.get("exit_code") != 0:
            raise IntegrityError("controller launcher receipt is absent or unsuccessful")
        atomic_write_json(attempt_dir / "launcher-receipt.json", receipt)
    else:
        receipt = {"schema_version": 1, "status": "ok", "mode": "direct", "accepted_at": _utc_now()}
        atomic_write_json(attempt_dir / "execution-receipt.json", receipt)

    registered = candidates_by_id(workspace)
    for candidate_id in provisional.get("candidate_ids", []):
        candidate = registered.get(candidate_id)
        if not candidate:
            raise IntegrityError(f"candidate disappeared before finalization: {candidate_id}")
        verify_snapshot(candidate)
        build_record = provisional.get("builds", {}).get(candidate_id)
        if not isinstance(build_record, dict):
            raise IntegrityError(f"candidate build provenance is missing: {candidate_id}")
        _read_build_ref(workspace, candidate, build_record)

    summary = dict(provisional)
    group = summary["comparison_group"]
    expected_preferred = summary.get("preferred_before")
    target = summary.get("preferred_target")
    if not isinstance(target, dict):
        raise IntegrityError("worker summary has no preferred candidate proposal")
    summary.update({
        "status": "complete", "execution_receipt": receipt,
        "promotion_status": "pending", "promoted": False,
        "preferred": expected_preferred,
        "accepted_at": _utc_now(),
    })
    should_update = bool(summary.get("promotion_requested")) or expected_preferred is None
    if not should_update:
        summary["promotion_status"] = "retained"
    # Establish a complete inspectable summary before the atomic preferred ref
    # changes. A crash in between leaves the prior ref intact and a resumable
    # pending promotion backed by the full measurements and receipt.
    atomic_write_json(attempt_dir / "summary.json", summary)
    promoted = False
    if should_update:
        if digest_file(task_path) != summary["task_sha256"] or package_fingerprint() != summary["engine_fingerprint"]:
            raise IntegrityError("task or engine changed before preferred candidate update")
        applied = compare_and_write_preferred(workspace, group, target, expected_preferred)
        if applied:
            promoted = bool(summary.get("promotion_requested"))
            summary["promotion_status"] = "applied" if promoted else "initialized"
            summary["promoted"] = promoted
            summary["preferred"] = target
            atomic_write_json(attempt_dir / "promotion.json", {
                "schema_version": 1, "run_id": run_id, "comparison_group": group,
                "candidate_id": target["candidate_id"], "status": summary["promotion_status"],
                "preferred_path": str(preferred_path(workspace, group)), "applied_at": _utc_now(),
            })
        else:
            summary["promotion_status"] = "conflict"
            summary["preferred"] = read_preferred(workspace, group)
    atomic_write_json(attempt_dir / "summary.json", summary, replace=True)
    append_jsonl(workspace, "candidates", {
        "record_type": "evaluation", "schema_version": 1, "run_id": run_id,
        "comparison_group": group, "candidate_ids": summary.get("candidate_ids", []),
        "incumbent_id": summary.get("incumbent_id"), "decision": summary.get("decision"),
        "promoted": promoted, "promotion_status": summary["promotion_status"],
        "summary_path": str(attempt_dir / "summary.json"),
        "summary_sha256": digest_file(attempt_dir / "summary.json"),
    })
    return {
        "schema_version": 1, "request_id": request_id, "status": "complete",
        "run_id": run_id, "comparison_group": group,
        "rankings": summary.get("rankings", []), "decision": summary.get("decision"),
        "promoted": promoted, "promotion_status": summary["promotion_status"],
        "summary_path": str(attempt_dir / "summary.json"),
        "build_errors": summary.get("build_errors", {}),
    }


def execute_batch_worker(
    batch_request: Mapping[str, Any], *, task_path: os.PathLike[str] | str,
    workspace: os.PathLike[str] | str, deadline: float | None = None,
) -> dict[str, Any]:
    task_path = Path(task_path).resolve(strict=True)
    workspace = Path(workspace).resolve()
    task, resolved_task = load_task(task_path)
    if batch_request.get("schema_version") != 1:
        raise ContractError("batch request schema_version must equal 1")
    worker_request_id = batch_request.get("request_id")
    if not isinstance(worker_request_id, str) or not worker_request_id:
        raise ContractError("batch request must have a unique request_id")
    if batch_request.get("task_sha256") != digest_file(task_path):
        raise IntegrityError("task contract changed after preflight and before worker execution")
    expected_engine = batch_request.get("engine_fingerprint")
    if expected_engine != package_fingerprint():
        raise IntegrityError("KDA experiment engine changed after preflight and before worker execution")
    attempt_id = batch_request.get("run_id")
    attempt_dir = workspace_paths(workspace)["attempts"] / attempt_id
    if not attempt_dir.is_dir():
        raise IntegrityError("batch attempt directory does not exist")
    deadline = deadline or (time.monotonic() + task["budgets"]["max_seconds"])
    by_id = candidates_by_id(workspace)
    candidate_ids = batch_request.get("candidate_ids")
    incumbent_id = batch_request.get("incumbent_id")
    if not isinstance(candidate_ids, list) or not isinstance(incumbent_id, str):
        raise ContractError("batch request requires candidate_ids and incumbent_id")
    all_ids = list(dict.fromkeys([incumbent_id, *candidate_ids]))
    if len(all_ids) > task["budgets"]["max_candidates"]:
        raise ContractError("candidate count exceeds task budget")
    missing = set(all_ids) - set(by_id)
    if missing:
        raise ContractError(f"unknown candidate ids: {sorted(missing)}")
    candidates = {candidate_id: by_id[candidate_id] for candidate_id in all_ids}
    builds: dict[str, dict[str, Any]] = {}
    for candidate_id in all_ids:
        build_data = batch_request.get("builds", {}).get(candidate_id)
        if not isinstance(build_data, dict):
            raise IntegrityError(f"no prepared build for candidate {candidate_id}")
        builds[candidate_id] = _read_build_ref(workspace, candidates[candidate_id], build_data)
        verify_snapshot(candidates[candidate_id])

    engine_hash = package_fingerprint()
    task_hash = digest_file(task_path)
    trusted_before, trusted_snapshot_dir = _copy_trusted_inputs(task, attempt_dir)
    if digest_json(trusted_before) != digest_json(batch_request.get("trusted_inputs")):
        raise IntegrityError("trusted harness/reference inputs changed after preflight")
    atomic_write_json(attempt_dir / "trusted-identities.json", {"inputs": trusted_before, "snapshots": str(trusted_snapshot_dir)})
    identities = _command_identities(task, resolved_task.parent, workspace)
    if digest_json(identities) != digest_json(batch_request.get("command_identities")):
        raise IntegrityError("selected command executable changed after preflight and before admitted evaluation")
    probe_stage = attempt_dir / "stages" / "probe"
    probe_request = {
        "operation": "probe", "task_id": task["task_id"], "declared_target": task["target"],
        "toolchain": task.get("toolchain", {}),
    }
    raw_probe, probe_process, probe_identity = invoke_task_command(
        task["probe"], probe_request, cwd=resolved_task.parent,
        stage_dir=probe_stage, deadline=deadline, label="hardware/toolchain probe",
    )
    probe = validate_envelope(raw_probe, probe_process["request_id"], "probe")
    if probe["status"] != "ok":
        raise ExecutionError("probe response reports status error")
    environment = _normalize_environment(probe.get("environment"), task)
    compiler_probe = batch_request.get("compiler_target_probe") or {}
    trusted = trusted_input_identities(task)
    group = base_comparison_group(task, environment, identities, trusted, compiler_probe)
    dependency_key = candidates[incumbent_id].get("dependencies", [])
    group = "cmp-" + digest_json({"base": group, "dependencies": dependency_key, "engine_fingerprint": engine_hash})[:24]
    preferred = read_preferred(workspace, group)
    if preferred and preferred.get("candidate_id") != incumbent_id:
        raise ContractError(f"incumbent {incumbent_id} differs from current preferred candidate {preferred.get('candidate_id')} for {group}")
    if preferred and preferred.get("environment_fingerprint") != digest_json(environment):
        raise IntegrityError("recorded preferred candidate environment has changed")

    comparable = [incumbent_id]
    rejected_dependencies = {}
    for candidate_id in candidate_ids:
        candidate = candidates[candidate_id]
        if candidate_id == incumbent_id:
            continue
        if candidate.get("dependencies", []) != dependency_key:
            rejected_dependencies[candidate_id] = "declared dependency manifest differs from incumbent"
            continue
        if candidate.get("experiment_group") and candidates[incumbent_id].get("experiment_group") and candidate["experiment_group"] != candidates[incumbent_id]["experiment_group"]:
            rejected_dependencies[candidate_id] = "candidate experiment_group differs from incumbent"
            continue
        comparable.append(candidate_id)

    validation: dict[str, dict[str, Any]] = {}
    validation_artifacts: dict[str, Any] = {}
    for candidate_id in comparable:
        result, artifact = _validate_one_candidate(
            workspace, task, resolved_task, attempt_dir, candidates[candidate_id], builds[candidate_id], environment, deadline,
        )
        validation[candidate_id] = result
        validation_artifacts[candidate_id] = artifact
    # A validator is task-owned, but validated candidate code can still alter
    # its read-only snapshot or build outputs. Recheck every participant after
    # all validators have run before allowing any timing.
    for candidate_id in comparable:
        try:
            _verify_candidate_artifacts(workspace, candidates[candidate_id], builds[candidate_id])
        except Exception as exc:
            validation[candidate_id]["status"] = "fail"
            validation[candidate_id]["reason"] = f"candidate artifact changed during validation: {type(exc).__name__}: {exc}"
    incumbent_valid = validation.get(incumbent_id, {}).get("status") == "pass"
    valid_ids = [candidate_id for candidate_id in comparable if validation.get(candidate_id, {}).get("status") == "pass"]
    if not incumbent_valid:
        raise ExecutionError("incumbent failed correctness validation; no candidate was benchmarked")
    if incumbent_id not in valid_ids:
        raise IntegrityError("validated incumbent missing from valid candidate set")

    environment_fp = digest_json(environment)
    matrix_seed = int(digest_json({"task_seed": task["timing"]["seed"], "request_id": worker_request_id})[:16], 16)
    measurements, benchmark_failures, benchmark_records = _benchmark_matrix(
        workspace=workspace, task=task, task_path=resolved_task, attempt_dir=attempt_dir,
        attempt_id=attempt_id, candidates=candidates, builds=builds, candidate_ids=valid_ids,
        environment=environment, environment_fp=environment_fp, deadline=deadline,
        phase="exploration", rounds=task["timing"]["rounds"], seed=matrix_seed,
    )
    if benchmark_failures.get(incumbent_id):
        raise ExecutionError(f"incumbent benchmark failed: {benchmark_failures[incumbent_id]}")
    rankable = {candidate_id: rounds_data for candidate_id, rounds_data in measurements.items() if len(rounds_data) == task["timing"]["rounds"] and not benchmark_failures.get(candidate_id)}
    if incumbent_id not in rankable:
        raise ExecutionError("incumbent did not complete all benchmark rounds")
    rankings = rank(
        [{"id": case["id"], "weight": case["weight"]} for case in task["cases"]],
        rankable, incumbent_id, task["timing"]["direction"],
    )
    top_challenger = next((item["candidate_id"] for item in rankings if item["candidate_id"] != incumbent_id), None)
    confirmation = None
    decision = {"candidate_id": incumbent_id, "eligible": False, "reason": "incumbent retained; no challenger had complete valid benchmark evidence"}
    if top_challenger is not None:
        confirm_ids = [incumbent_id, top_challenger]
        confirmation_measurements, confirmation_failures, confirmation_records = _benchmark_matrix(
            workspace=workspace, task=task, task_path=resolved_task, attempt_dir=attempt_dir,
            attempt_id=attempt_id, candidates=candidates, builds=builds, candidate_ids=confirm_ids,
            environment=environment, environment_fp=environment_fp, deadline=deadline,
            phase="confirmation", rounds=task["timing"]["confirmation_rounds"], seed=matrix_seed ^ 0x9E3779B97F4A7C15,
        )
        benchmark_records.extend(confirmation_records)
        if not confirmation_failures and all(len(confirmation_measurements[candidate_id]) == task["timing"]["confirmation_rounds"] for candidate_id in confirm_ids):
            confirmation = confirm(
                [{"id": case["id"], "weight": case["weight"]} for case in task["cases"]],
                confirmation_measurements[incumbent_id], confirmation_measurements[top_challenger],
                task["timing"]["direction"],
                min_improvement=task["promotion"]["min_improvement"],
                max_regression=task["promotion"]["max_regression"],
                bootstrap_samples=task["promotion"]["bootstrap_samples"],
                seed=task["timing"]["seed"], confidence=task["promotion"]["confidence"],
            )
            decision = {"candidate_id": top_challenger, **confirmation}
        else:
            confirmation = {"eligible": False, "reason": "confirmation measurements incomplete or invalid", "failures": confirmation_failures}
            decision = {"candidate_id": incumbent_id, "eligible": False, "reason": "incumbent retained because confirmation measurements failed"}

    after_trusted_ok = _compare_trusted_before_after(trusted_before, task)
    provenance_ok = _engine_identity_check(engine_hash, task_path, task_hash)
    try:
        tools_unchanged = digest_json(_command_identities(task, resolved_task.parent, workspace)) == digest_json(identities)
    except Exception:
        tools_unchanged = False
    if not after_trusted_ok:
        decision = {"candidate_id": incumbent_id, "eligible": False, "reason": "trusted harness or reference changed during the experiment"}
    if not provenance_ok:
        decision = {"candidate_id": incumbent_id, "eligible": False, "reason": "task contract or KDA engine source changed during the experiment"}
    if not tools_unchanged:
        decision = {"candidate_id": incumbent_id, "eligible": False, "reason": "selected command executable changed during the experiment"}
    for candidate_id in valid_ids:
        try:
            _verify_candidate_artifacts(workspace, candidates[candidate_id], builds[candidate_id])
        except Exception as exc:
            if candidate_id == incumbent_id:
                raise IntegrityError(f"incumbent artifact changed during benchmark evaluation: {exc}") from exc
            if decision.get("candidate_id") == candidate_id:
                decision = {"candidate_id": incumbent_id, "eligible": False, "reason": f"challenger artifact changed during evaluation: {candidate_id}: {exc}"}
    promotion_requested = bool(decision.get("eligible") and decision.get("candidate_id") != incumbent_id)
    selected_id = decision["candidate_id"] if decision.get("eligible") else incumbent_id
    if not preferred and not promotion_requested:
        selected_id = incumbent_id
    preferred_value = {
        "schema_version": 1, "comparison_group": group, "candidate_id": selected_id,
        "run_id": attempt_id, "environment_fingerprint": environment_fp,
        "task_fingerprint": digest_file(task_path), "engine_fingerprint": package_fingerprint(),
        "selected_at": _utc_now(), "decision": decision,
    }
    summary = {
        "schema_version": 1, "status": "worker_complete", "run_id": attempt_id,
        "request_id": worker_request_id, "task_id": task["task_id"],
        "task_path": str(task_path), "task_sha256": task_hash,
        "comparison_group": group, "environment": environment,
        "environment_fingerprint": environment_fp, "probe": probe,
        "probe_result_sha256": probe_identity["sha256"], "compiler_target_probe": compiler_probe,
        "command_identities": identities, "trusted_inputs": trusted_before,
        "trusted_inputs_unchanged": after_trusted_ok, "tools_unchanged": tools_unchanged,
        "engine_fingerprint": engine_hash,
        "candidate_ids": all_ids, "requested_candidate_ids": list(batch_request.get("requested_candidate_ids", candidate_ids)),
        "incumbent_id": incumbent_id, "builds": builds,
        "build_errors": batch_request.get("build_errors", {}),
        "validation": validation, "validation_artifacts": validation_artifacts,
        "validation_rejected": rejected_dependencies,
        "benchmark_failures": benchmark_failures, "benchmark_records": benchmark_records,
        "rankings": rankings, "confirmation": confirmation,
        "decision": decision, "promotion_requested": promotion_requested,
        "promoted": False, "promotion_status": "awaiting-receipt",
        "preferred_before": preferred, "preferred_target": preferred_value,
        "completed_at": _utc_now(), "resume_from": batch_request.get("resume_from"),
    }
    provisional_path = attempt_dir / "worker-summary.json"
    atomic_write_json(provisional_path, summary)
    return {
        "schema_version": 1, "request_id": worker_request_id, "status": "complete",
        "run_id": attempt_id, "comparison_group": group, "rankings": rankings,
        "decision": decision, "summary_path": str(provisional_path),
        "summary_sha256": digest_file(provisional_path),
    }


def evaluate_candidates(
    task_path: os.PathLike[str] | str,
    workspace: os.PathLike[str] | str,
    candidate_ids: list[str],
    incumbent_id: str | None,
    *,
    resume_from: str | None = None,
    compiler_target_probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    task, resolved_task = load_task(task_path)
    initial_task_hash = digest_file(resolved_task)
    workspace_path = Path(workspace).resolve()
    paths = ensure_layout(workspace_path)
    by_id = candidates_by_id(workspace_path)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ContractError("evaluate candidate ids must be unique")
    if incumbent_id is None:
        baseline = next((record["candidate_id"] for record in candidate_records(workspace_path) if record.get("baseline")), None)
        if baseline is None:
            raise ContractError("evaluate requires --incumbent or a registered --baseline candidate")
        incumbent_id = baseline
    if incumbent_id not in by_id:
        raise ContractError(f"unknown incumbent candidate: {incumbent_id}")
    all_ids = list(dict.fromkeys([incumbent_id, *candidate_ids]))
    if len(all_ids) > task["budgets"]["max_candidates"]:
        raise ContractError("candidate count exceeds task budgets.max_candidates")
    missing = set(all_ids) - set(by_id)
    if missing:
        raise ContractError(f"unknown candidate ids: {sorted(missing)}")
    deadline = time.monotonic() + task["budgets"]["max_seconds"]
    trusted = trusted_input_identities(task)
    identities = _command_identities(task, resolved_task.parent, workspace_path)
    engine_hash = package_fingerprint()
    compiler_record = dict(compiler_target_probe or run_compiler_target_probe(
        task, task_dir=resolved_task.parent, deadline=deadline,
        evidence_dir=paths["runs"] / "preflight" / uuid.uuid4().hex,
    ))
    if digest_file(resolved_task) != initial_task_hash:
        raise IntegrityError("task contract changed during compiler target preflight")
    prepared = prepare_candidates(
        resolved_task, workspace_path, all_ids, jobs=1,
        compiler_target_probe=compiler_record,
    )
    if digest_file(resolved_task) != initial_task_hash:
        raise IntegrityError("task contract changed during candidate preparation")
    build_results = {item["candidate_id"]: item for item in prepared}
    build_errors = {candidate_id: item.get("reason", "build failed") for candidate_id, item in build_results.items() if item.get("status") != "ok"}
    if incumbent_id in build_errors:
        raise ExecutionError(f"incumbent build failed: {build_errors[incumbent_id]}")
    for candidate_id in candidate_ids:
        if candidate_id in build_errors:
            continue
    if digest_json(trusted_input_identities(task)) != digest_json(trusted):
        raise IntegrityError("trusted inputs changed during candidate preparation")
    _verify_command_identities(task, resolved_task.parent, identities, workspace_path)
    if package_fingerprint() != engine_hash:
        raise IntegrityError("KDA experiment engine changed during candidate preparation")
    run_id = str(uuid.uuid4())
    run_dir = paths["attempts"] / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    batch_request = {
        "schema_version": 1, "request_id": str(uuid.uuid4()), "run_id": run_id,
        "task_id": task["task_id"], "task_path": str(resolved_task),
        "candidate_ids": [candidate_id for candidate_id in candidate_ids if candidate_id not in build_errors],
        "requested_candidate_ids": list(candidate_ids), "incumbent_id": incumbent_id,
        "builds": {candidate_id: {key: build_results[candidate_id][key] for key in ("directory", "fingerprint", "task_contract_sha256", "artifacts", "manifest_path", "manifest_sha256")} for candidate_id in all_ids if candidate_id not in build_errors},
        "build_errors": build_errors,
        "command_identities": identities,
        "compiler_target_probe": compiler_record,
        "engine_fingerprint": engine_hash,
        "trusted_inputs": trusted,
        "task_sha256": initial_task_hash,
        "resume_from": resume_from,
    }
    atomic_write_json(run_dir / "batch-request.json", batch_request)
    try:
        worker_result = _direct_or_launched_worker(
            task, batch_request, task_path=resolved_task, workspace=workspace_path,
            attempt_dir=run_dir, deadline=deadline,
        )
        if worker_result.get("request_id") != batch_request["request_id"]:
            raise IntegrityError("worker result request_id mismatch")
        finalized = _finalize_worker_result(
            worker_result, batch_request, task=task, task_path=resolved_task,
            workspace=workspace_path, attempt_dir=run_dir,
        )
        atomic_write_json(run_dir / "worker-response.json", finalized)
        return finalized
    except Exception as exc:
        failure = {
            "schema_version": 1, "status": "error", "run_id": run_id,
            "request_id": batch_request["request_id"], "task_id": task["task_id"],
            "candidate_ids": all_ids, "incumbent_id": incumbent_id,
            "reason": f"{type(exc).__name__}: {exc}", "failed_at": _utc_now(),
            "task_sha256": batch_request["task_sha256"], "engine_fingerprint": engine_hash,
        }
        try:
            atomic_write_json(run_dir / "failure.json", failure)
            append_jsonl(workspace_path, "candidates", {"record_type": "failed_evaluation", **failure, "summary_path": str(run_dir / "failure.json")})
        except IntegrityError:
            pass
        raise


def resume_evaluation(task_path: os.PathLike[str] | str, workspace: os.PathLike[str] | str, run_id: str) -> dict[str, Any]:
    from .store import valid_id
    valid_id(run_id, "run id")
    old_dir = workspace_paths(workspace)["attempts"] / run_id
    if not old_dir.is_dir():
        raise ContractError(f"unknown run id: {run_id}")
    if (old_dir / "summary.json").exists():
        raise ContractError("completed run cannot be resumed")
    request_path = old_dir / "batch-request.json"
    if not request_path.exists():
        raise ContractError("run has no resumable batch request")
    request = load_json(request_path)
    task, resolved_task = load_task(task_path)
    if digest_file(resolved_task) != request.get("task_sha256"):
        raise IntegrityError("task contract changed since interrupted run; a fresh evaluate is required")
    if package_fingerprint() != request.get("engine_fingerprint"):
        raise IntegrityError("KDA experiment engine changed since interrupted run; a fresh evaluate is required")
    workspace_path = Path(workspace).resolve()
    current_identities = _command_identities(task, resolved_task.parent, workspace_path)
    if digest_json(current_identities) != digest_json(request.get("command_identities")):
        raise IntegrityError("selected tools changed since interrupted run; a fresh evaluate is required")
    current_trusted = trusted_input_identities(task)
    if digest_json(current_trusted) != digest_json(request.get("trusted_inputs")):
        raise IntegrityError("trusted inputs changed since interrupted run; a fresh evaluate is required")
    deadline = time.monotonic() + task["budgets"]["max_seconds"]
    current_probe = run_compiler_target_probe(
        task, task_dir=resolved_task.parent, deadline=deadline,
        evidence_dir=workspace_paths(workspace_path)["runs"] / "preflight" / uuid.uuid4().hex,
    )
    if digest_json(current_probe) != digest_json(request.get("compiler_target_probe")):
        raise IntegrityError("compiler target support evidence changed since interrupted run; a fresh evaluate is required")
    # New attempt ID and request ID prevent interrupted child output files from
    # being mistaken for fresh evidence. Successful builds are content-addressed
    # and reused by prepare_candidates only when their fingerprints and hashes
    # still match. Validation and measurements are repeated as a new paired run.
    return evaluate_candidates(
        resolved_task, workspace,
        request.get("requested_candidate_ids", request["candidate_ids"]),
        request["incumbent_id"], resume_from=run_id,
        compiler_target_probe=current_probe,
    )


def inspect_workspace(workspace: os.PathLike[str] | str, key: str | None = None) -> dict[str, Any]:
    paths = workspace_paths(workspace)
    if key is not None:
        candidates = candidates_by_id(workspace)
        if key in candidates:
            return {"kind": "candidate", "candidate": candidates[key]}
        attempt_dir = paths["attempts"] / key
        if attempt_dir.is_dir():
            summary = attempt_dir / "summary.json"
            failure = attempt_dir / "failure.json"
            request = attempt_dir / "batch-request.json"
            return {
                "kind": "run", "run_id": key,
                "summary": load_json(summary) if summary.exists() else None,
                "failure": load_json(failure) if failure.exists() else None,
                "request": load_json(request) if request.exists() else None,
                "resumable": not summary.exists(),
            }
        raise ContractError(f"no candidate or run found with id {key}")
    return {
        "kind": "workspace", "candidates": candidate_records(workspace),
        "runs": [path.name for path in list_attempts(workspace)],
        "preferred": [load_json(path) for path in sorted(paths["preferred"].glob("*.json"))] if paths["preferred"].exists() else [],
    }


def _reconcile_applied_selection(
    workspace: os.PathLike[str] | str,
    run_id: str,
    summary: dict[str, Any],
    group: str,
    target: Mapping[str, Any],
    selected_id: str,
) -> dict[str, Any]:
    """Finish evidence bookkeeping after the preferred reference matches a run."""
    attempt_dir = workspace_paths(workspace)["attempts"] / run_id
    status = "applied" if summary.get("promotion_requested") else "initialized"
    summary["promotion_status"] = status
    summary["promoted"] = bool(summary.get("promotion_requested"))
    summary["preferred"] = dict(target)

    promotion_path = attempt_dir / "promotion.json"
    promotion_record = {
        "schema_version": 1, "run_id": run_id,
        "comparison_group": group, "candidate_id": selected_id,
        "status": status,
        "preferred_path": str(preferred_path(workspace, group)),
        "applied_at": _utc_now(), "recovered": True,
    }
    if promotion_path.exists():
        existing = load_json(promotion_path)
        if (existing.get("run_id") != run_id or existing.get("comparison_group") != group
                or existing.get("candidate_id") != selected_id):
            raise IntegrityError("existing promotion receipt conflicts with the preferred candidate")
        if existing.get("status") != status:
            promotion_record["recovered"] = True
            atomic_write_json(promotion_path, promotion_record, replace=True)
    else:
        atomic_write_json(promotion_path, promotion_record)

    summary_path = attempt_dir / "summary.json"
    atomic_write_json(summary_path, summary, replace=True)
    existing_selection = any(
        row.get("record_type") == "selection" and row.get("run_id") == run_id
        for row in read_jsonl(workspace_paths(workspace)["candidates"])
    )
    if not existing_selection:
        append_jsonl(workspace, "candidates", {
            "record_type": "selection", "schema_version": 1,
            "run_id": run_id, "comparison_group": group,
            "candidate_id": selected_id,
            "preferred_path": str(preferred_path(workspace, group)),
            "selection": summary.get("decision"), "selected_at": _utc_now(),
            "summary_sha256": digest_file(summary_path), "recovered": True,
        })
    return summary


def select_run(workspace: os.PathLike[str] | str, run_id: str, *, apply: bool = False) -> dict[str, Any]:
    summary = read_attempt(workspace, run_id)
    decision = summary.get("decision", {})
    group = summary.get("comparison_group")
    current = read_preferred(workspace, group) if isinstance(group, str) else None
    applied = False
    if apply:
        if summary.get("status") != "complete":
            raise ContractError("only completed evaluations can be selected")
        receipt = summary.get("execution_receipt")
        if not isinstance(receipt, dict) or receipt.get("status") != "ok":
            raise IntegrityError("cannot apply a selection without an accepted execution receipt")
        target = summary.get("preferred_target")
        if not isinstance(target, dict) or target.get("comparison_group") != group:
            raise IntegrityError("completed run has no valid preferred-candidate proposal")
        selected_id = target.get("candidate_id")
        incumbent_id = summary.get("incumbent_id")
        if selected_id not in summary.get("candidate_ids", []):
            raise IntegrityError("proposed candidate is not part of the evaluated batch")
        if decision.get("eligible"):
            if decision.get("candidate_id") != selected_id or selected_id == incumbent_id:
                raise IntegrityError("preferred-candidate proposal disagrees with confirmation decision")
            if not summary.get("promotion_requested"):
                raise IntegrityError("confirmation decision was not marked for promotion")
        elif selected_id != incumbent_id:
            raise ContractError("cannot apply a challenger without eligible confirmation evidence")
        expected_preferred = summary.get("preferred_before")
        if expected_preferred is not None and not summary.get("promotion_requested"):
            raise ContractError("run did not propose a new preferred candidate")
        if not summary.get("trusted_inputs_unchanged", False):
            raise IntegrityError("cannot apply selection after trusted inputs changed")
        task_path = Path(summary.get("task_path", "")).resolve(strict=True)
        task, task_path = load_task(task_path)
        if summary.get("task_sha256") != digest_file(task_path):
            raise IntegrityError("cannot apply selection after task contract changed")
        if summary.get("engine_fingerprint") != package_fingerprint():
            raise IntegrityError("cannot apply selection after engine source changed")
        if digest_json(trusted_input_identities(task)) != digest_json(summary.get("trusted_inputs")):
            raise IntegrityError("cannot apply selection after trusted inputs changed")
        if digest_json(_command_identities(task, task_path.parent, Path(workspace).resolve())) != digest_json(summary.get("command_identities")):
            raise IntegrityError("cannot apply selection after selected tools changed")
        if target.get("task_fingerprint") != summary.get("task_sha256") or target.get("engine_fingerprint") != summary.get("engine_fingerprint"):
            raise IntegrityError("preferred-candidate proposal has stale task or engine identity")
        if target.get("environment_fingerprint") != summary.get("environment_fingerprint"):
            raise IntegrityError("preferred-candidate proposal has stale environment identity")
        registered = candidates_by_id(workspace)
        builds = summary.get("builds", {})
        validation = summary.get("validation", {})
        for candidate_id in set(summary.get("candidate_ids", [])):
            candidate = registered.get(candidate_id)
            build = builds.get(candidate_id)
            if not isinstance(candidate, dict) or not isinstance(build, dict):
                raise IntegrityError(f"candidate or build evidence is missing: {candidate_id}")
            _verify_candidate_artifacts(Path(workspace).resolve(), candidate, build)
        if validation.get(selected_id, {}).get("status") != "pass":
            raise IntegrityError("proposed preferred candidate did not pass every correctness case")

        if current == target:
            applied = True
        else:
            if current != expected_preferred:
                raise IntegrityError("preferred candidate changed after this run; refusing stale selection")
            if not compare_and_write_preferred(workspace, group, target, expected_preferred):
                raise IntegrityError("preferred candidate changed concurrently; refusing stale selection")
            current = target
            applied = True
        if applied:
            if read_preferred(workspace, group) != target:
                raise IntegrityError("preferred candidate changed before selection evidence could be finalized")
            summary = _reconcile_applied_selection(
                workspace, run_id, summary, group, target, selected_id,
            )
    return {
        "run_id": run_id, "comparison_group": group, "rankings": summary.get("rankings", []),
        "decision": decision, "current_preferred": current, "applied": applied,
    }


def attach_evidence(
    workspace: os.PathLike[str] | str,
    run_id: str,
    artifact: os.PathLike[str] | str,
    *,
    kind: str,
    candidate_id: str,
    case_id: str | None = None,
    architecture: str | None = None,
    symbol: str | None = None,
    dependency_revision: str | None = None,
    experiment_group: str | None = None,
) -> dict[str, Any]:
    from .store import valid_id
    run_id = valid_id(run_id, "run id")
    candidate_id = valid_id(candidate_id, "candidate id")
    if kind not in {"profile", "sass", "ablation"}:
        raise ContractError("evidence kind must be profile, sass, or ablation")
    summary = read_attempt(workspace, run_id)
    if candidate_id not in summary.get("candidate_ids", []):
        raise ContractError("evidence candidate does not belong to this attempt")
    if kind == "sass" and (not architecture or not symbol):
        raise ContractError("SASS evidence requires architecture and symbol metadata")
    if kind == "ablation" and not experiment_group:
        raise ContractError("ablation evidence requires an experiment_group label")
    if kind == "profile" and not case_id:
        raise ContractError("profile evidence requires the workload case_id it describes")
    task, task_path = load_task(summary["task_path"])
    if digest_file(task_path) != summary.get("task_sha256"):
        raise IntegrityError("cannot attach evidence after the task contract changed")
    case = None
    if case_id is not None:
        case = next((workload_descriptor(item) for item in task["cases"] if item["id"] == case_id), None)
        if case is None:
            raise ContractError(f"unknown workload case for attached evidence: {case_id}")
    candidate = candidates_by_id(workspace)[candidate_id]
    build = summary.get("builds", {}).get(candidate_id)
    if not isinstance(build, dict):
        raise IntegrityError("attached candidate has no verified build in this run")
    _verify_candidate_artifacts(Path(workspace).resolve(), candidate, build)
    build_artifacts = [dict(item) for item in build["artifacts"]]
    target_architecture = task["target"].get("compiler_target", task["target"]["architecture"])
    if kind == "sass" and architecture != target_architecture:
        raise ContractError(f"SASS architecture must match the candidate compiler target {target_architecture}")
    if kind == "profile" and architecture is None:
        architecture = summary.get("environment", {}).get("architecture")
    source_path = Path(artifact)
    if source_path.is_symlink():
        raise ContractError("attached evidence must not be a symlink")
    source = source_path.resolve(strict=True)
    if not source.is_file():
        raise ContractError("attached evidence must be a regular file")
    attempt_dir = workspace_paths(workspace)["attempts"] / run_id
    evidence_dir = attempt_dir / "attachments"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sha256 = digest_file(source)
    destination = evidence_dir / f"{candidate_id}-{kind}-{sha256[:16]}{source.suffix}"
    if not destination.exists():
        shutil.copyfile(source, destination)
        if digest_file(destination) != sha256:
            raise IntegrityError("attached evidence changed during copy")
        destination.chmod(0o444)
    record = {
        "schema_version": 1, "run_id": run_id, "candidate_id": candidate_id,
        "kind": kind, "case_id": case_id, "architecture": architecture,
        "symbol": symbol, "dependency_revision": dependency_revision,
        "experiment_group": experiment_group, "sha256": sha256,
        "workload": case, "binary_artifacts": build_artifacts,
        "path": str(destination), "environment_fingerprint": summary.get("environment_fingerprint"),
        "metric_role": "diagnostic" if kind == "profile" else "supporting-evidence",
        "timing_in_benchmark_score": False,
    }
    ledger = attempt_dir / "attachments.jsonl"
    with workspace_lock(workspace):
        with ledger.open("ab") as stream:
            stream.write((canonical_json(record) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    return record

