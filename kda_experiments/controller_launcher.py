"""Optional site adapter for the independently installed CUDA controller.

This module has no CUDA imports and discovers no devices. It translates one
engine worker request into one controller-admitted foreground command. The
engine is responsible for CPU-only preparation and the outer process-group
deadline. Neither this adapter nor a failed controller runs the worker directly.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time


def _object(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _argv(value, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item or "\0" in item for item in value
    ):
        raise ValueError(f"{name} must be a nonempty argv array")
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _Cancelled(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


def _controller_process(argv: list[str], *, cwd: Path, stdout, stderr) -> int:
    """Give the controller a chance to release admission on cancellation.

    SIGTERM does not unwind Python finally blocks. Translate cancellation to
    SIGINT for the controller, then enforce a short bounded cleanup deadline.
    The outer engine also bounds this adapter and its process group.
    """
    process = None
    previous = {}
    pending_signal = None

    def cancelled(signum, _frame):
        nonlocal pending_signal
        if process is None:
            # Popen may be interrupted after spawning but before returning its
            # handle. Defer cleanup until that handle has been assigned.
            pending_signal = signum
            return
        raise _Cancelled(signum)

    def signal_group(signum):
        if process is None:
            return
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    if os.name != "posix":
        raise ValueError("controller launcher requires POSIX process groups")
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, cancelled)
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            if pending_signal is not None:
                raise _Cancelled(pending_signal)
            return process.wait()
        except BaseException:
            # Avoid a second interrupt cutting short the cleanup that releases
            # the controller's reservation. The engine retains its hard limit.
            for signum in previous:
                signal.signal(signum, signal.SIG_IGN)
            signal_group(signal.SIGINT)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                process.poll()
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                # The controller leader may exit while its worker is still
                # relaying cancellation to an independent evaluator group.
                time.sleep(0.02)
            signal_group(signal.SIGKILL)
            process.wait()
            raise
        finally:
            # A leader exiting does not establish that its descendants exited.
            signal_group(signal.SIGKILL)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def launch(config_path: Path, request_path: Path, result_path: Path) -> dict:
    """Run one controller request; preserve its raw output and lease receipt."""
    request = _object(request_path)
    request_id = request.get("request_id")
    if request.get("schema_version") != 1 or not isinstance(request_id, str) or not request_id:
        raise ValueError("launcher request needs schema_version 1 and request_id")
    if result_path.exists():
        raise ValueError("launcher result already exists; use a fresh attempt")
    config = _object(config_path)
    command = _argv(config.get("controller_argv"), "controller_argv")
    worker = _argv(request.get("argv"), "worker argv")
    project = Path(config["project_root"]).resolve(strict=True)
    cwd = Path(request["cwd"]).resolve(strict=True)
    if not project.is_dir() or not cwd.is_dir() or not cwd.is_relative_to(project):
        raise ValueError("worker cwd must be a directory within project_root")
    timeout = request.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    resources = config.get("resources")
    if not isinstance(resources, dict) or type(resources.get("gpus")) is not int or resources["gpus"] < 1:
        raise ValueError("site config requires resources.gpus >= 1")
    toolchain = config.get("toolchain")
    if not isinstance(toolchain, dict) or not isinstance(toolchain.get("root"), str) or not toolchain["root"]:
        raise ValueError("site config requires an explicit toolchain.root")
    if set(toolchain) - {"root", "require_sanitizer"}:
        raise ValueError("unsupported toolchain configuration")

    spec = {
        "schema_version": 1,
        "project_root": str(project),
        "command_cwd": str(cwd),
        "recipe": "baseline",
        "resources": resources,
        "toolchain": toolchain,
        "argv": worker,
        "timeout": timeout,
    }
    if "quiescence" in config:
        policy = config["quiescence"]
        limits = {"timeout_seconds": 60, "interval_seconds": 5,
                  "consecutive_idle_samples": 64}
        if not isinstance(policy, dict) or not policy or set(policy) - set(limits):
            raise ValueError("unsupported quiescence configuration")
        for key, value in policy.items():
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 < value <= limits[key]
                    or (key == "consecutive_idle_samples" and type(value) is not int)):
                raise ValueError(f"invalid quiescence {key}")
        spec["quiescence"] = dict(policy)
    # These artifacts live beside the unique engine launcher request, not in a
    # shared fixed filename. The controller captures worker stdout independently.
    artifact_dir = request_path.parent / (request_path.stem + "-controller")
    artifact_dir.mkdir(exist_ok=False)
    spec_path = artifact_dir / "spec.json"
    _write(spec_path, spec)
    stdout_path = artifact_dir / "stdout.json"
    stderr_path = artifact_dir / "stderr.txt"
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        returncode = _controller_process(
            command + ["run", "--spec", str(spec_path), "--json"],
            cwd=project, stdout=stdout, stderr=stderr,
        )
    try:
        if stdout_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("controller response exceeds 4 MiB")
        controller = _object(stdout_path)
    except (ValueError, OSError) as exc:
        controller = {"ok": False, "error": str(exc)}
    accepted = returncode == 0 and controller.get("ok") is True
    receipt = {
        "schema_version": 1,
        "request_id": request_id,
        "status": "ok" if accepted else "failed",
        "exit_code": 0 if accepted else (returncode or 1),
        "controller_result": controller,
        "controller_spec": str(spec_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    _write(result_path, receipt)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = launch(args.config.resolve(), args.request.resolve(), args.result.resolve())
        return 0 if receipt["status"] == "ok" else 1
    except _Cancelled as exc:
        print("controller launcher: cancelled", file=sys.stderr)
        return 128 + exc.signum
    except (KeyError, OSError, ValueError) as exc:
        print(f"controller launcher: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
