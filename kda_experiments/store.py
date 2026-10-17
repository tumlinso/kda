"""Append-only experiment evidence and immutable candidate snapshots."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .contracts import canonical_json, digest_file, digest_json, digest_tree, load_json
from .errors import ContractError, IntegrityError


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CSV_FIELDS = [
    "run_id", "candidate_id", "phase", "case_id", "round", "metric", "unit",
    "direction", "samples_json", "median", "workload_sha256", "environment_fingerprint",
    "result_path", "result_sha256",
]
_thread_lock = threading.RLock()


def valid_id(value: str, label: str = "id") -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or value in {".", ".."}:
        raise ContractError(f"{label} must match {_ID_RE.pattern!r}")
    return value


def workspace_paths(workspace: os.PathLike[str] | str) -> dict[str, Path]:
    root = Path(workspace).resolve()
    return {
        "root": root,
        "candidates": root / "candidates.jsonl",
        "benchmark": root / "benchmark.csv",
        "lock": root / ".kda-experiments.lock",
        "runs": root / "runs" / "kda-experiments",
        "snapshots": root / "runs" / "kda-experiments" / "candidates",
        "builds": root / "runs" / "kda-experiments" / "builds",
        "attempts": root / "runs" / "kda-experiments" / "attempts",
        "preferred": root / "preferred",
    }


@contextmanager
def workspace_lock(workspace: os.PathLike[str] | str) -> Iterator[None]:
    paths = workspace_paths(workspace)
    paths["root"].mkdir(parents=True, exist_ok=True)
    with _thread_lock:
        descriptor = os.open(paths["lock"], os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - KDA's supported CUDA hosts are POSIX
                fcntl = None
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def ensure_layout(workspace: os.PathLike[str] | str) -> dict[str, Path]:
    paths = workspace_paths(workspace)
    for key in ("runs", "snapshots", "builds", "attempts", "preferred"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def atomic_write_bytes(path: os.PathLike[str] | str, data: bytes, *, replace: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not replace:
        raise IntegrityError(f"refusing to overwrite immutable evidence: {target}")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not replace and target.exists():
            raise IntegrityError(f"refusing to overwrite immutable evidence: {target}")
        os.replace(temp_path, target)
        try:
            dirfd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except OSError:
            pass
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_json(path: os.PathLike[str] | str, value: Any, *, replace: bool = False) -> None:
    payload = (canonical_json(value) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload, replace=replace)


def read_jsonl(path: os.PathLike[str] | str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IntegrityError(f"invalid JSONL record at {source}:{number}: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def append_jsonl(workspace: os.PathLike[str] | str, filename: str, record: Mapping[str, Any]) -> None:
    paths = ensure_layout(workspace)
    target = paths[filename]
    line = (canonical_json(dict(record)) + "\n").encode("utf-8")
    with workspace_lock(workspace):
        _append_jsonl_unlocked(target, line)


def _append_jsonl_unlocked(target: Path, line: bytes) -> None:
    with target.open("ab") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def candidate_records(workspace: os.PathLike[str] | str) -> list[dict[str, Any]]:
    return [row for row in read_jsonl(workspace_paths(workspace)["candidates"]) if row.get("record_type") == "candidate"]


def candidates_by_id(workspace: os.PathLike[str] | str) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in candidate_records(workspace):
        candidate_id = record.get("candidate_id")
        if isinstance(candidate_id, str):
            by_id[candidate_id] = record
    return by_id


def read_candidate_manifest(path: os.PathLike[str] | str, source_root: os.PathLike[str] | str) -> dict[str, Any]:
    manifest_path = Path(path).resolve(strict=True)
    value = load_json(manifest_path)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ContractError("candidate manifest schema_version must equal 1")
    files = value.get("files")
    if not isinstance(files, list) or not files or any(not isinstance(item, str) or not item for item in files):
        raise ContractError("candidate manifest files must be a non-empty array of relative file paths")
    if len(set(files)) != len(files):
        raise ContractError("candidate manifest has duplicate files")
    deps = value.get("dependencies", [])
    if not isinstance(deps, list):
        raise ContractError("candidate manifest dependencies must be an array")
    normalized_deps = []
    dep_names: set[str] = set()
    for index, dependency in enumerate(deps):
        if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str) or not dependency["name"] or not isinstance(dependency.get("revision"), str) or not dependency["revision"]:
            raise ContractError(f"candidate dependency {index} must have non-empty name and revision")
        if dependency["name"] in dep_names:
            raise ContractError(f"duplicate dependency name: {dependency['name']}")
        dep_names.add(dependency["name"])
        normalized_deps.append({"name": dependency["name"], "revision": dependency["revision"]})
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ContractError("candidate source path must be a directory")
    normalized_files = []
    for item in sorted(files):
        rel = Path(item)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ContractError(f"candidate manifest path must stay within source directory: {item}")
        current = root
        for part in rel.parts:
            current = current / part
            if current.is_symlink():
                raise IntegrityError(f"candidate manifest may not include symlinks: {item}")
        if not current.is_file():
            raise ContractError(f"candidate manifest source file is missing or not regular: {item}")
        normalized_files.append(rel.as_posix())
    return {"schema_version": 1, "files": normalized_files, "dependencies": normalized_deps, "manifest_sha256": digest_file(manifest_path)}


def _make_read_only(root: Path) -> None:
    for current, dirs, files in os.walk(root, topdown=False):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            path.chmod(path.stat().st_mode & ~0o222)
        for name in dirs:
            (current_path / name).chmod(0o555)
    root.chmod(0o555)


def verify_snapshot(record: Mapping[str, Any]) -> Path:
    raw_snapshot = Path(record["snapshot_dir"])
    if raw_snapshot.is_symlink():
        raise IntegrityError(f"candidate snapshot is a symlink: {record.get('candidate_id')}")
    snapshot = raw_snapshot.resolve(strict=True)
    declared = record.get("source_manifest")
    if not isinstance(declared, list):
        raise IntegrityError("candidate record has no declared source manifest")
    actual_digest, actual_entries = digest_tree(snapshot, [item["path"] for item in declared])
    if actual_entries != declared or actual_digest != record.get("snapshot_sha256"):
        raise IntegrityError(f"candidate snapshot has changed: {record.get('candidate_id')}")
    return snapshot


def register_candidate(
    workspace: os.PathLike[str] | str,
    candidate_id: str,
    source_dir: os.PathLike[str] | str,
    manifest_path: os.PathLike[str] | str,
    *,
    parent: str | None,
    hypothesis: str,
    change: str,
    baseline: bool = False,
    experiment_group: str | None = None,
) -> dict[str, Any]:
    candidate_id = valid_id(candidate_id, "candidate id")
    if parent is not None:
        parent = valid_id(parent, "parent candidate id")
    if not hypothesis.strip() or not change.strip():
        raise ContractError("candidate hypothesis and change description must be non-empty")
    if experiment_group is not None:
        experiment_group = valid_id(experiment_group, "experiment group")
    paths = ensure_layout(workspace)
    source_root = Path(source_dir).resolve(strict=True)
    source_manifest = read_candidate_manifest(manifest_path, source_root)
    snapshot_hash, source_entries = digest_tree(source_root, source_manifest["files"])
    snapshot_dir = paths["snapshots"] / candidate_id / snapshot_hash
    record = {
        "record_type": "candidate",
        "schema_version": 1,
        "candidate_id": candidate_id,
        "parent_id": parent,
        "hypothesis": hypothesis.strip(),
        "change": change.strip(),
        "baseline": bool(baseline),
        "experiment_group": experiment_group,
        "registered_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "source_manifest": source_entries,
        "dependencies": source_manifest["dependencies"],
        "manifest_sha256": source_manifest["manifest_sha256"],
        "snapshot_sha256": snapshot_hash,
        "snapshot_dir": str(snapshot_dir),
    }
    with workspace_lock(workspace):
        existing = candidates_by_id(workspace).get(candidate_id)
        if existing:
            compare_fields = ("parent_id", "hypothesis", "change", "baseline", "experiment_group", "dependencies", "snapshot_sha256", "manifest_sha256")
            if any(existing.get(key) != record.get(key) for key in compare_fields):
                raise IntegrityError(f"candidate id is immutable and already registered differently: {candidate_id}")
            verify_snapshot(existing)
            return existing
        if parent is not None and parent not in candidates_by_id(workspace):
            raise ContractError(f"parent candidate is not registered: {parent}")
        if baseline and any(item.get("baseline") for item in candidate_records(workspace)):
            raise ContractError("only one baseline candidate may be registered")
        snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
        if snapshot_dir.exists():
            raise IntegrityError(f"unregistered snapshot path already exists: {snapshot_dir}")
        temp = snapshot_dir.parent / f".{snapshot_hash}.{uuid.uuid4().hex}.tmp"
        temp.mkdir()
        try:
            for entry in source_entries:
                rel = Path(entry["path"])
                target = temp / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_root / rel, target)
                if digest_file(target) != entry["sha256"]:
                    raise IntegrityError(f"source changed during snapshot registration: {entry['path']}")
            _make_read_only(temp)
            os.replace(temp, snapshot_dir)
        finally:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
        _append_jsonl_unlocked(paths["candidates"], (canonical_json(record) + "\n").encode("utf-8"))
    return record


def append_benchmark(workspace: os.PathLike[str] | str, row: Mapping[str, Any]) -> None:
    paths = ensure_layout(workspace)
    target = paths["benchmark"]
    with workspace_lock(workspace):
        exists = target.exists() and target.stat().st_size > 0
        if exists:
            with target.open("r", newline="", encoding="utf-8") as stream:
                reader = csv.reader(stream)
                try:
                    header = next(reader)
                except StopIteration:
                    header = []
            if header != _CSV_FIELDS:
                raise IntegrityError("benchmark.csv has an existing incompatible header; preserving it without appending ambiguous rows")
        with target.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow({key: row.get(key, "") for key in _CSV_FIELDS})
            stream.flush()
            os.fsync(stream.fileno())


def preferred_path(workspace: os.PathLike[str] | str, comparison_group: str) -> Path:
    valid_id(comparison_group, "comparison group")
    return workspace_paths(workspace)["preferred"] / f"{comparison_group}.json"


def read_preferred(workspace: os.PathLike[str] | str, comparison_group: str) -> dict[str, Any] | None:
    path = preferred_path(workspace, comparison_group)
    if not path.exists():
        return None
    return load_json(path)


def write_preferred(workspace: os.PathLike[str] | str, comparison_group: str, value: Mapping[str, Any]) -> None:
    path = preferred_path(workspace, comparison_group)
    with workspace_lock(workspace):
        atomic_write_json(path, dict(value), replace=True)


def compare_and_write_preferred(
    workspace: os.PathLike[str] | str,
    comparison_group: str,
    value: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
) -> bool:
    """Atomically update the preferred pointer only if its observed value is unchanged."""
    path = preferred_path(workspace, comparison_group)
    with workspace_lock(workspace):
        current = load_json(path) if path.exists() else None
        if current != expected:
            return False
        atomic_write_json(path, dict(value), replace=True)
        return True


def list_attempts(workspace: os.PathLike[str] | str) -> list[Path]:
    root = workspace_paths(workspace)["attempts"]
    if not root.exists():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)


def read_attempt(workspace: os.PathLike[str] | str, run_id: str) -> dict[str, Any]:
    run_id = valid_id(run_id, "run id")
    summary_path = workspace_paths(workspace)["attempts"] / run_id / "summary.json"
    if not summary_path.exists():
        raise ContractError(f"run summary is not complete or does not exist: {run_id}")
    return load_json(summary_path)

