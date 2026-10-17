"""No-shell subprocess execution for task evaluators and external launchers."""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from .contracts import canonical_json, load_json, resolve_executable, validate_envelope
from .errors import ContractError, ExecutionError, IntegrityError
from .store import atomic_write_json


_active_processes: dict[int, tuple[subprocess.Popen, float]] = {}
# Signal handlers clean every registered group before raising. Remember that
# cleanup so the interrupted _run frame does not repeat its whole grace period.
_signal_cleaned_processes: set[int] = set()
_active_lock = threading.RLock()
_handlers_installed = False
_main_thread_spawning = False
_deferred_signal: int | None = None
_PROCESS_GROUP_POLL_SECONDS = 0.02
_PROCESS_GROUP_GRACE_SECONDS = 1.0
_EXTERNAL_LAUNCHER_GRACE_SECONDS = 4.0
_CANCEL_DEADLINE_MARGIN_SECONDS = 0.5


def _signal_group(process: subprocess.Popen, signum: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signum)
        elif process.poll() is None:  # pragma: no cover - CUDA hosts are POSIX
            if signum == getattr(signal, "SIGKILL", None):
                process.kill()
            else:
                process.terminate()
    except ProcessLookupError:
        pass


def _group_exists(process: subprocess.Popen) -> bool:
    if os.name != "posix":  # pragma: no cover - CUDA hosts are POSIX
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # The group exists, but cannot be signalled.
        return True


def _terminate_processes(processes: list[subprocess.Popen], *, grace_seconds: float) -> None:
    """Terminate command groups, escalating even when only descendants remain."""
    if not processes:
        return
    for process in processes:
        _signal_group(process, signal.SIGTERM)

    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        for process in processes:
            # poll() also reaps direct children where possible. A returned
            # leader does not imply that its process group has disappeared.
            process.poll()
        if not any(_group_exists(process) for process in processes):
            break
        time.sleep(_PROCESS_GROUP_POLL_SECONDS)

    for process in processes:
        if _group_exists(process):
            if os.name == "posix":
                _signal_group(process, signal.SIGKILL)
            elif process.poll() is None:  # pragma: no cover - CUDA hosts are POSIX
                process.kill()
    # Reap every direct child. The KILL above also stops grandchildren that
    # ignored TERM or outlived the group leader.
    for process in processes:
        try:
            process.wait()
        except OSError:
            pass


def install_termination_handlers() -> None:
    """Make worker cancellation terminate every active evaluator process group."""
    global _handlers_installed, _deferred_signal
    if _handlers_installed or threading.current_thread() is not threading.main_thread():
        return

    def terminate_children(signum, _frame):
        global _deferred_signal
        # Popen in the main thread cannot be interrupted between child creation
        # and registration: remember the signal, then handle it as soon as the
        # process is visible. Worker-thread spawns hold _active_lock, so this
        # handler waits for their registration before taking its snapshot.
        if _main_thread_spawning:
            _deferred_signal = signum
            return
        with _active_lock:
            active = list(_active_processes.values())
        processes = [process for process, _grace in active]
        cleaned_ids = {id(process) for process in processes}
        with _active_lock:
            _signal_cleaned_processes.update(cleaned_ids)
        # A caller must leave time for each child to handle cancellation and
        # clean its own descendants. The launcher path needs the longest
        # window because its adapter unwinds an admitted controller batch.
        grace = max((value for _process, value in active), default=_PROCESS_GROUP_GRACE_SECONDS)
        try:
            _terminate_processes(
                processes, grace_seconds=grace + _CANCEL_DEADLINE_MARGIN_SECONDS
            )
        except BaseException:
            with _active_lock:
                _signal_cleaned_processes.difference_update(cleaned_ids)
            raise
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate_children)
    signal.signal(signal.SIGINT, terminate_children)
    _handlers_installed = True


def remaining_seconds(deadline: float, label: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExecutionError(f"experiment time budget exhausted before {label}")
    return remaining


def task_environment() -> dict[str, str]:
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parent.parent)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = package_root + (os.pathsep + old if old else "")
    return env


def _format_argv(argv: list[str], request_path: Path, result_path: Path) -> list[str]:
    values = {"{request}": str(request_path.resolve()), "{result}": str(result_path.resolve())}
    return [values.get(argument, argument) for argument in argv]


def resolve_command_executable(argv: list[str], cwd: os.PathLike[str] | str) -> dict[str, str]:
    """Resolve argv[0] using the same working directory as subprocess launch."""
    if not argv:
        raise ContractError("subprocess argv must be a non-empty string array")
    base_dir = Path(cwd).resolve()
    executable = argv[0]
    candidate = Path(executable)
    if not candidate.is_absolute() and (os.sep in executable or (os.altsep and os.altsep in executable)):
        absolute = (base_dir / candidate).resolve(strict=True)
        return resolve_executable([str(absolute), *argv[1:]], base_dir)
    return resolve_executable(argv, base_dir)


def _run(
    argv: list[str], *, cwd: Path, timeout_seconds: float, output_prefix: Path,
    env: Mapping[str, str] | None = None,
    termination_grace_seconds: float = _PROCESS_GROUP_GRACE_SECONDS,
) -> dict[str, Any]:
    if not argv or any(not isinstance(arg, str) for arg in argv):
        raise ContractError("subprocess argv must be a non-empty string array")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0):
        raise ContractError("subprocess timeout_seconds must be positive")
    if (isinstance(termination_grace_seconds, bool)
            or not isinstance(termination_grace_seconds, (int, float))
            or not math.isfinite(float(termination_grace_seconds))
            or termination_grace_seconds <= 0):
        raise ContractError("subprocess termination_grace_seconds must be positive")
    cwd.mkdir(parents=True, exist_ok=True)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = output_prefix.with_suffix(".stdout.txt")
    stderr_path = output_prefix.with_suffix(".stderr.txt")
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            # A signal handler in the main thread defers cancellation through
            # the tiny Popen/registration window. Do not mask signals here:
            # children inherit the calling thread's signal mask across exec.
            global _main_thread_spawning, _deferred_signal
            main_thread_spawn = threading.current_thread() is threading.main_thread()
            if main_thread_spawn:
                _main_thread_spawning = True
            try:
                with _active_lock:
                    process = subprocess.Popen(
                        argv,
                        cwd=cwd,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout,
                        stderr=stderr,
                        env=dict(env) if env is not None else task_environment(),
                        shell=False,
                        start_new_session=(os.name == "posix"),
                    )
                    _active_processes[process.pid] = (process, float(termination_grace_seconds))
            finally:
                if main_thread_spawn:
                    _main_thread_spawning = False
            try:
                if _deferred_signal is not None:
                    signum = _deferred_signal
                    _deferred_signal = None
                    if signum == signal.SIGINT:
                        raise KeyboardInterrupt
                    raise SystemExit(128 + signum)
                try:
                    exit_code = process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    raise ExecutionError(f"command timed out after {timeout_seconds:.3f}s: {argv[0]}") from exc
                # A well-behaved task command is foreground and leaves no work
                # in its group. Clean up descendants before another stage can
                # run on the same GPU.
                if _group_exists(process):
                    raise ExecutionError(f"command left descendant processes running: {argv[0]}")
            except BaseException:
                with _active_lock:
                    already_cleaned = id(process) in _signal_cleaned_processes
                    _signal_cleaned_processes.discard(id(process))
                if not already_cleaned:
                    _terminate_processes([process], grace_seconds=float(termination_grace_seconds))
                raise
            finally:
                with _active_lock:
                    _active_processes.pop(process.pid, None)
                    _signal_cleaned_processes.discard(id(process))
    except FileNotFoundError as exc:
        raise ExecutionError(f"command executable not found: {argv[0]}") from exc
    except OSError as exc:
        raise ExecutionError(f"could not execute {argv[0]}: {exc}") from exc
    result = {"argv": argv, "cwd": str(cwd), "exit_code": exit_code, "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}
    if exit_code != 0:
        excerpt = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise ExecutionError(f"command exited {exit_code}: {argv[0]}\n{excerpt}")
    return result


def invoke_task_command(
    command: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    cwd: os.PathLike[str] | str,
    stage_dir: os.PathLike[str] | str,
    deadline: float,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    stage = Path(stage_dir)
    requests = stage / "requests"
    responses = stage / "responses"
    requests.mkdir(parents=True, exist_ok=True)
    responses.mkdir(parents=True, exist_ok=True)
    request_id = str(uuid.uuid4())
    request_obj = {"schema_version": 1, "request_id": request_id, **dict(request)}
    request_path = requests / f"{request_id}.json"
    result_path = responses / f"{request_id}.json"
    atomic_write_json(request_path, request_obj)
    argv = _format_argv(list(command["argv"]), request_path, result_path)
    base_dir = Path(cwd).resolve()
    executable = resolve_command_executable(argv, base_dir)
    process_info = _run(
        argv,
        cwd=base_dir,
        timeout_seconds=min(float(command["timeout_seconds"]), remaining_seconds(deadline, label)),
        output_prefix=stage / f"{request_id}.process",
    )
    if not result_path.exists() or result_path.is_symlink():
        raise ExecutionError(f"{label} command succeeded but did not create a regular result file")
    response = load_json(result_path)
    envelope = validate_envelope(response, request_id, label)
    process_info.update({"request_id": request_id, "request_path": str(request_path), "result_path": str(result_path), "result_sha256": __import__("hashlib").sha256(result_path.read_bytes()).hexdigest(), "executable": executable})
    return envelope, process_info, {"request_id": request_id, "sha256": process_info["result_sha256"]}


def run_compiler_target_probe(task: Mapping[str, Any], *, task_dir: Path, deadline: float, evidence_dir: Path) -> dict[str, Any]:
    argv = task.get("toolchain", {}).get("compiler_target_probe_argv")
    target = task["target"].get("compiler_target", task["target"]["architecture"])
    if not argv:
        return {"argv": [], "target": target, "supported": None, "stdout_sha256": None}
    executable = resolve_command_executable(argv, task_dir)
    output_prefix = evidence_dir / "compiler-target-probe"
    process = _run(
        list(argv),
        cwd=task_dir,
        timeout_seconds=min(float(task.get("budgets", {}).get("max_seconds", 300)), remaining_seconds(deadline, "compiler target support probe")),
        output_prefix=output_prefix,
    )
    stdout = Path(process["stdout_path"]).read_text(encoding="utf-8", errors="replace")
    token_present = target in stdout.split()
    record = {
        "argv": list(argv), "executable": executable, "target": target,
        "supported": token_present,
        "stdout_sha256": __import__("hashlib").sha256(stdout.encode("utf-8")).hexdigest(),
        "stdout": stdout,
        "exit_code": process["exit_code"],
    }
    if not token_present:
        raise ExecutionError(f"selected compiler does not report support for target {target}")
    return record


def invoke_external_launcher(
    task: Mapping[str, Any],
    worker_argv: list[str],
    *,
    cwd: os.PathLike[str] | str,
    worker_result_path: os.PathLike[str] | str,
    stage_dir: os.PathLike[str] | str,
    deadline: float,
) -> dict[str, Any]:
    execution = task["execution"]
    if execution["mode"] != "launcher":
        raise ContractError("external launcher requested for direct execution task")
    stage = Path(stage_dir)
    request_id = str(uuid.uuid4())
    launcher_request_path = stage / f"launcher-{request_id}.request.json"
    launcher_receipt_path = stage / f"launcher-{request_id}.receipt.json"
    request = {
        "schema_version": 1,
        "request_id": request_id,
        "argv": worker_argv,
        "cwd": str(Path(cwd).resolve()),
        "worker_result_path": str(Path(worker_result_path).resolve()),
        "timeout_seconds": remaining_seconds(deadline, "external launcher admission"),
    }
    atomic_write_json(launcher_request_path, request)
    launcher_argv = _format_argv(list(execution["launcher_argv"]), launcher_request_path, launcher_receipt_path)
    executable = resolve_command_executable(launcher_argv, Path(cwd).resolve())
    process = _run(
        launcher_argv,
        cwd=Path(cwd).resolve(),
        timeout_seconds=remaining_seconds(deadline, "external launcher"),
        output_prefix=stage / f"launcher-{request_id}.process",
        termination_grace_seconds=_EXTERNAL_LAUNCHER_GRACE_SECONDS,
    )
    if not launcher_receipt_path.exists() or launcher_receipt_path.is_symlink():
        raise ExecutionError("launcher exited successfully but did not create a regular receipt")
    receipt = load_json(launcher_receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1 or receipt.get("request_id") != request_id:
        raise IntegrityError("launcher receipt schema or request_id mismatch")
    if receipt.get("status") != "ok" or receipt.get("exit_code") != 0:
        raise ExecutionError(f"launcher admission/execution failed: {receipt}")
    receipt["process"] = process
    receipt["executable"] = executable
    receipt["request_path"] = str(launcher_request_path)
    receipt["receipt_path"] = str(launcher_receipt_path)
    return receipt
