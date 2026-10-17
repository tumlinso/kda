"""Launcher fixture that explicitly denies execution for fail-closed tests."""

from __future__ import annotations

import json
import pathlib
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit("usage: deny_launcher.py REQUEST RESULT")
    request = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))
    receipt = {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": "error",
        "exit_code": 73,
        "receipt": {"reason": "fixture denial"},
    }
    pathlib.Path(argv[2]).write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    return 73


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
