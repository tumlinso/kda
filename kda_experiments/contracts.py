"""Versioned task and evaluator contracts for KDA experiments.

The engine deliberately does not know how to compute an answer or what numeric
tolerance is appropriate. Trusted task-owned commands receive a request JSON
file and return a result JSON file. This module validates the envelope and the
workload coverage while leaving numerical comparison to the task validator.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractError, IntegrityError


SCHEMA_VERSION = 1
_ALLOWED_ROLES = {"reference", "harness", "validator", "benchmark", "probe", "toolchain", "other"}
_COMMAND_NAMES = {"build", "validate", "benchmark", "probe"}
_PLACEHOLDERS = {"{request}", "{result}"}
_SM_RE = re.compile(r"^sm_[0-9]{2,3}$")
_COMPILER_SM_RE = re.compile(r"^sm_[0-9]{2,3}[a-z]*$")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-standard JSON number is not allowed: {value}")


def load_json(path: os.PathLike[str] | str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant)
    except ContractError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical JSON: {exc}") from exc


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: os.PathLike[str] | str) -> str:
    file_path = Path(path)
    if file_path.is_symlink() or not file_path.is_file():
        raise IntegrityError(f"expected a regular non-symlink file: {file_path}")
    hasher = hashlib.sha256()
    with file_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def digest_tree(root: os.PathLike[str] | str, files: list[str] | None = None) -> tuple[str, list[dict[str, str]]]:
    base = Path(root).resolve(strict=True)
    if not base.is_dir():
        raise IntegrityError(f"expected directory: {base}")
    if files is None:
        paths: list[str] = []
        for current, dirs, names in os.walk(base, followlinks=False):
            current_path = Path(current)
            for directory in list(dirs):
                child = current_path / directory
                if child.is_symlink():
                    raise IntegrityError(f"symlink in source tree: {child}")
            paths.extend((current_path / name).relative_to(base).as_posix() for name in names)
        files = sorted(paths)
    entries: list[dict[str, str]] = []
    for relative in sorted(set(files)):
        rel = _relative_path(relative, "manifest file")
        source = base / rel
        if source.is_symlink() or not source.is_file():
            raise IntegrityError(f"manifest entry is not a regular file: {rel}")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(base):
            raise IntegrityError(f"manifest entry escapes source directory: {rel}")
        entries.append({"path": rel.as_posix(), "sha256": digest_file(source)})
    if not entries:
        raise IntegrityError("candidate source manifest must contain at least one file")
    return digest_json(entries), entries


def _relative_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError(f"{label} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise ContractError(f"{label} must not be absolute or contain '..': {value}")
    return path


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _number(value: Any, label: str, *, positive: bool = False, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ContractError(f"{label} must be finite numeric")
    result = float(value)
    if positive and result <= 0:
        raise ContractError(f"{label} must be positive")
    if minimum is not None and result < minimum:
        raise ContractError(f"{label} must be at least {minimum}")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _command(value: Any, label: str, *, require_cpu_only: bool = False) -> dict[str, Any]:
    obj = dict(_mapping(value, label))
    argv = obj.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        raise ContractError(f"{label}.argv must be a non-empty array of non-empty strings")
    if "{request}" not in argv or "{result}" not in argv:
        raise ContractError(f"{label}.argv must contain '{{request}}' and '{{result}}' arguments")
    if any("{" in arg or "}" in arg for arg in argv if arg not in _PLACEHOLDERS):
        raise ContractError(f"{label}.argv only supports exact {{request}} and {{result}} arguments")
    timeout = obj.get("timeout_seconds", 300)
    obj["timeout_seconds"] = _number(timeout, f"{label}.timeout_seconds", positive=True)
    if require_cpu_only and obj.get("cpu_only") is not True:
        raise ContractError("build.cpu_only must be true; the engine never runs candidate kernels while preparing builds")
    return obj


def load_task(path: os.PathLike[str] | str) -> tuple[dict[str, Any], Path]:
    task_path = Path(path).resolve(strict=True)
    task = _mapping(load_json(task_path), "task")
    if task.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"task.schema_version must equal {SCHEMA_VERSION}")
    _string(task.get("task_id"), "task.task_id")
    numerical = task.get("numerical_requirements")
    if not isinstance(numerical, dict) or not numerical:
        raise ContractError("task.numerical_requirements must state the task-owned numerical comparison requirements")

    cases = task.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractError("task.cases must be a non-empty array")
    seen: set[str] = set()
    normalized_cases: list[dict[str, Any]] = []
    for index, case_value in enumerate(cases):
        case = dict(_mapping(case_value, f"task.cases[{index}]"))
        case_id = _string(case.get("id"), f"task.cases[{index}].id")
        if case_id in seen:
            raise ContractError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        weight = _number(case.get("weight", 1.0), f"task.cases[{index}].weight", positive=True)
        if "input" not in case or not isinstance(case["input"], dict) or not case["input"]:
            raise ContractError(f"task.cases[{index}].input must identify reproducible input data or a seed")
        params = case.get("parameters", {})
        if not isinstance(params, dict):
            raise ContractError(f"task.cases[{index}].parameters must be an object")
        normalized_cases.append({**case, "id": case_id, "weight": weight, "parameters": params})
    task = dict(task)
    task["cases"] = normalized_cases

    commands = _mapping(task.get("commands"), "task.commands")
    task["commands"] = {
        "build": _command(commands.get("build"), "commands.build", require_cpu_only=True),
        "validate": _command(commands.get("validate"), "commands.validate"),
        "benchmark": _command(commands.get("benchmark"), "commands.benchmark"),
    }
    task["probe"] = _command(task.get("probe"), "task.probe")

    trusted = task.get("trusted_inputs")
    if not isinstance(trusted, list) or not trusted:
        raise ContractError("task.trusted_inputs must declare at least one trusted reference or harness input")
    trusted_ids: set[str] = set()
    resolved_trusted: list[dict[str, str]] = []
    for index, item_value in enumerate(trusted):
        item = _mapping(item_value, f"task.trusted_inputs[{index}]")
        item_id = _string(item.get("id"), f"task.trusted_inputs[{index}].id")
        if item_id in trusted_ids:
            raise ContractError(f"duplicate trusted input id: {item_id}")
        trusted_ids.add(item_id)
        role = _string(item.get("role"), f"task.trusted_inputs[{index}].role")
        if role not in _ALLOWED_ROLES:
            raise ContractError(f"trusted input role must be one of {sorted(_ALLOWED_ROLES)}")
        raw_path = Path(_string(item.get("path"), f"task.trusted_inputs[{index}].path"))
        unresolved = (task_path.parent / raw_path) if not raw_path.is_absolute() else raw_path
        if unresolved.is_symlink():
            raise ContractError(f"trusted input may not be a symlink: {unresolved}")
        resolved = unresolved.resolve(strict=True)
        if not (resolved.is_file() or resolved.is_dir()):
            raise ContractError(f"trusted input must be a regular file or directory: {resolved}")
        resolved_trusted.append({"id": item_id, "role": role, "path": str(resolved)})
    task["trusted_inputs"] = resolved_trusted

    timing = dict(_mapping(task.get("timing"), "task.timing"))
    timing["metric"] = _string(timing.get("metric"), "timing.metric")
    timing["unit"] = _string(timing.get("unit"), "timing.unit")
    timing["direction"] = _string(timing.get("direction"), "timing.direction")
    if timing["direction"] not in {"minimize", "maximize"}:
        raise ContractError("timing.direction must be 'minimize' or 'maximize'")
    warmup = timing.get("warmup")
    if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < 0:
        raise ContractError("timing.warmup must be a non-negative integer")
    timing["warmup"] = warmup
    timing["repetitions"] = _positive_int(timing.get("repetitions"), "timing.repetitions")
    timing["rounds"] = _positive_int(timing.get("rounds"), "timing.rounds")
    timing["confirmation_rounds"] = _positive_int(timing.get("confirmation_rounds"), "timing.confirmation_rounds")
    if timing["rounds"] < 2 or timing["confirmation_rounds"] < 2:
        raise ContractError("timing.rounds and timing.confirmation_rounds must each be at least two")
    timing["seed"] = timing.get("seed")
    if isinstance(timing["seed"], bool) or not isinstance(timing["seed"], int):
        raise ContractError("timing.seed must be an integer")
    timing["scope"] = _string(timing.get("scope"), "timing.scope")
    task["timing"] = timing

    promotion = dict(_mapping(task.get("promotion"), "task.promotion"))
    promotion["min_improvement"] = _number(promotion.get("min_improvement"), "promotion.min_improvement", minimum=0)
    promotion["max_regression"] = _number(promotion.get("max_regression"), "promotion.max_regression", minimum=0)
    if promotion["max_regression"] >= 1:
        raise ContractError("promotion.max_regression must be below 1")
    promotion["confidence"] = _number(promotion.get("confidence"), "promotion.confidence", positive=True)
    if promotion["confidence"] >= 1:
        raise ContractError("promotion.confidence must be below 1")
    promotion["bootstrap_samples"] = _positive_int(promotion.get("bootstrap_samples"), "promotion.bootstrap_samples")
    task["promotion"] = promotion

    target = dict(_mapping(task.get("target"), "task.target"))
    target["kind"] = _string(target.get("kind"), "target.kind")
    if target["kind"] not in {"cpu", "cuda"}:
        raise ContractError("target.kind must be 'cpu' or 'cuda'")
    target["architecture"] = _string(target.get("architecture"), "target.architecture")
    if target["kind"] == "cuda":
        if not _SM_RE.fullmatch(target["architecture"]):
            raise ContractError("CUDA target.architecture must name a physical architecture such as sm_70 or sm_90")
        target.setdefault("compiler_target", target["architecture"])
        if not isinstance(target["compiler_target"], str) or not _COMPILER_SM_RE.fullmatch(target["compiler_target"]):
            raise ContractError("CUDA target.compiler_target must be an exact compiler code such as sm_70 or sm_90a")
    elif _COMPILER_SM_RE.fullmatch(target["architecture"]) or "compiler_target" in target:
        raise ContractError("CPU targets cannot declare CUDA architectures or compiler_target")
    task["target"] = target

    toolchain = dict(_mapping(task.get("toolchain", {}), "task.toolchain"))
    compiler_probe = toolchain.get("compiler_target_probe_argv")
    if target["kind"] == "cuda":
        if not isinstance(compiler_probe, list) or not compiler_probe or any(not isinstance(a, str) or not a for a in compiler_probe):
            raise ContractError("sm_* targets require toolchain.compiler_target_probe_argv (for example nvcc --list-gpu-code)")
    elif compiler_probe is not None and (not isinstance(compiler_probe, list) or not compiler_probe):
        raise ContractError("toolchain.compiler_target_probe_argv must be a non-empty argv array")
    task["toolchain"] = toolchain

    execution = dict(_mapping(task.get("execution"), "task.execution"))
    mode = _string(execution.get("mode"), "execution.mode")
    if mode not in {"direct", "launcher"}:
        raise ContractError("execution.mode must be 'direct' or 'launcher'")
    if mode == "launcher":
        launcher_argv = execution.get("launcher_argv")
        if not isinstance(launcher_argv, list) or not launcher_argv or any(not isinstance(a, str) or not a for a in launcher_argv):
            raise ContractError("launcher execution requires execution.launcher_argv")
        if "{request}" not in launcher_argv or "{result}" not in launcher_argv:
            raise ContractError("execution.launcher_argv must include '{request}' and '{result}' arguments")
    task["execution"] = execution

    budgets = dict(_mapping(task.get("budgets"), "task.budgets"))
    budgets["max_candidates"] = _positive_int(budgets.get("max_candidates"), "budgets.max_candidates")
    budgets["max_build_jobs"] = _positive_int(budgets.get("max_build_jobs"), "budgets.max_build_jobs")
    budgets["max_seconds"] = _number(budgets.get("max_seconds"), "budgets.max_seconds", positive=True)
    task["budgets"] = budgets
    return task, task_path


def workload_descriptor(case: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = {key: value for key, value in case.items() if key != "workload_sha256"}
    return {**descriptor, "workload_sha256": digest_json(descriptor)}


def validate_envelope(response: Any, request_id: str, label: str) -> dict[str, Any]:
    obj = dict(_mapping(response, f"{label} result"))
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"{label} response schema_version must equal {SCHEMA_VERSION}")
    if obj.get("request_id") != request_id:
        raise ContractError(f"{label} response request_id does not match this invocation")
    status = obj.get("status")
    if status not in {"ok", "error"}:
        raise ContractError(f"{label} response status must be 'ok' or 'error'")
    return obj


def validate_cases_response(response: Any, request_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    obj = validate_envelope(response, request_id, "validation")
    if obj["status"] != "ok":
        raise ContractError("validation response status must be 'ok' before per-case results are considered")
    rows = obj.get("cases")
    if not isinstance(rows, list):
        raise ContractError("validation response cases must be an array")
    expected = {case["id"]: case["workload_sha256"] for case in cases}
    seen: set[str] = set()
    for index, row_value in enumerate(rows):
        row = _mapping(row_value, f"validation.cases[{index}]")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in expected:
            raise ContractError(f"validation returned unexpected case id: {case_id}")
        if case_id in seen:
            raise ContractError(f"validation returned duplicate case id: {case_id}")
        seen.add(case_id)
        if row.get("workload_sha256") != expected[case_id]:
            raise ContractError(f"validation workload descriptor mismatch for case {case_id}")
        if row.get("status") not in {"pass", "fail", "oom", "unsupported"}:
            raise ContractError(f"validation case {case_id} has invalid status")
    missing = set(expected) - seen
    if missing:
        raise ContractError(f"validation omitted required cases: {sorted(missing)}")
    return obj


def validate_benchmark_response(response: Any, request_id: str, case: dict[str, Any], timing: Mapping[str, Any]) -> dict[str, Any]:
    obj = validate_envelope(response, request_id, "benchmark")
    if obj["status"] != "ok":
        raise ContractError("benchmark response status must be 'ok'")
    if obj.get("case_id") != case["id"]:
        raise ContractError("benchmark response case_id does not match requested workload")
    if obj.get("workload_sha256") != case["workload_sha256"]:
        raise ContractError(f"benchmark workload descriptor mismatch for case {case['id']}")
    for key in ("timing_scope", "warmup", "repetitions"):
        if obj.get(key) != timing["scope" if key == "timing_scope" else key]:
            raise ContractError(f"benchmark response {key} does not match the task contract")
    for key in ("metric", "unit"):
        if obj.get(key) != timing[key]:
            raise ContractError(f"benchmark response {key} does not match the task contract")
    samples = obj.get("samples")
    if not isinstance(samples, list) or len(samples) != timing["repetitions"]:
        raise ContractError(f"benchmark must return exactly {timing['repetitions']} raw samples")
    checked: list[float] = []
    for index, sample in enumerate(samples):
        if isinstance(sample, bool) or not isinstance(sample, (int, float)) or not math.isfinite(float(sample)) or float(sample) <= 0:
            raise ContractError(f"benchmark sample {index} must be positive and finite")
        checked.append(float(sample))
    obj["samples"] = checked
    return obj


def resolve_executable(argv: list[str], base_dir: Path) -> dict[str, str]:
    executable = argv[0]
    candidate = Path(executable)
    resolved = (base_dir / candidate).resolve() if candidate.is_absolute() is False and len(candidate.parts) > 1 else None
    if resolved is not None and resolved.exists():
        path = resolved
    else:
        found = shutil.which(executable)
        if not found:
            raise ContractError(f"cannot resolve command executable: {executable}")
        path = Path(found).resolve(strict=True)
    if not path.is_file():
        raise ContractError(f"command executable is not a file: {path}")
    return {"path": str(path), "sha256": digest_file(path)}


def trusted_input_identities(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    for item in task["trusted_inputs"]:
        path = Path(item["path"])
        if path.is_dir():
            files: list[dict[str, str]] = []
            for current, dirs, names in os.walk(path, followlinks=False):
                base = Path(current)
                if any((base / directory).is_symlink() for directory in dirs):
                    raise IntegrityError(f"symlink in trusted input directory: {path}")
                for name in sorted(names):
                    source = base / name
                    if source.is_symlink() or not source.is_file():
                        raise IntegrityError(f"non-regular file in trusted input: {source}")
                    files.append({"path": source.relative_to(path).as_posix(), "sha256": digest_file(source)})
            identities.append({"id": item["id"], "role": item["role"], "path": str(path), "files": files, "sha256": digest_json(files)})
        else:
            identities.append({"id": item["id"], "role": item["role"], "path": str(path), "sha256": digest_file(path)})
    return identities


def comparison_group(task: Mapping[str, Any], environment: Mapping[str, Any], command_identities: Mapping[str, Any], trusted: list[dict[str, Any]], compiler_targets: Mapping[str, Any] | None = None) -> str:
    basis = {
        "task_id": task["task_id"],
        "cases": task["cases"],
        "numerical_requirements": task["numerical_requirements"],
        "commands": {name: task["commands"][name]["argv"] for name in ("validate", "benchmark", "build")},
        "command_identities": command_identities,
        "trusted_inputs": trusted,
        "environment": environment,
        "target": task["target"],
        "toolchain": task.get("toolchain", {}),
        "execution": task["execution"],
        "compiler_targets": compiler_targets or {},
        "timing": task["timing"],
        "promotion": task["promotion"],
    }
    return "cmp-" + digest_json(basis)[:24]

