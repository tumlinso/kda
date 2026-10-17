"""Fake CUDA controller for CPU-only launcher integration tests.

The controller consumes the adapter's generated JSON spec and executes its
exact worker argv and cwd. No CUDA runtime, device, or reservation is accessed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys


def main(argv: list[str]) -> int:
    spec_path = pathlib.Path(argv[argv.index("--spec") + 1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    project = pathlib.Path(spec["project_root"])
    log = pathlib.Path(sys.argv[1])
    behavior = sys.argv[2] if len(sys.argv) > 2 else "normal"
    log.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        spec["argv"], cwd=spec["command_cwd"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "argv": spec["argv"], "cwd": spec["command_cwd"],
            "project_root": str(project), "returncode": completed.returncode,
            "stdout": completed.stdout.decode("utf-8", errors="replace"),
            "stderr": completed.stderr.decode("utf-8", errors="replace"),
        }, sort_keys=True) + "\n")
    if behavior == "mutate-task-after-worker" and completed.returncode == 0:
        command = spec["argv"]
        task_path = pathlib.Path(command[command.index("--task") + 1])
        task_path.write_text(task_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    if completed.returncode != 0:
        print(json.dumps({"ok": False, "worker_exit_code": completed.returncode}))
        return 0
    print(json.dumps({"ok": True, "lease_receipt": "fake-cpu-only-admission"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
