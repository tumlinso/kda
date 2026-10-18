"""Command line interface for KDA candidate experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from . import engine
from .contracts import load_json, load_task
from .errors import KDAExperimentError
from .runner import install_termination_handlers
from .store import register_candidate


class _JsonArgumentParser(argparse.ArgumentParser):
    """Keep argparse failures machine-readable while preserving normal help."""

    def error(self, message: str) -> None:
        self._emit({"status": "error", "error": message, "error_type": "ArgumentError"}, sys.stderr)
        self.exit(2)

    @staticmethod
    def _emit(value: Any, stream) -> None:
        try:
            stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        except (TypeError, ValueError):
            stream.write('{"status":"error","error":"result is not JSON serializable"}\n')


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="python3 -m kda_experiments",
        description="Register, evaluate, inspect, and select independent kernel candidates.",
    )
    parser.add_argument("--version", action="version", version=f"kda_experiments {__version__}")
    parser.add_argument("--task", type=Path, help="versioned task contract JSON")
    parser.add_argument("--workspace", type=Path, help="task-owned experiment workspace")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_JsonArgumentParser)

    register = commands.add_parser("register", help="snapshot and record a candidate")
    register.add_argument("candidate_id", metavar="ID")
    register.add_argument("source_dir", type=Path, metavar="SOURCE_DIR")
    register.add_argument("--manifest", required=True, type=Path)
    register.add_argument("--hypothesis", required=True)
    register.add_argument("--change", required=True)
    register.add_argument("--parent")
    register.add_argument("--baseline", action="store_true")
    register.add_argument("--experiment-group")

    prepare = commands.add_parser("prepare", help="build candidate snapshots")
    prepare.add_argument("candidate_ids", nargs="+", metavar="ID")
    prepare.add_argument("--jobs", type=int, default=1)

    evaluate = commands.add_parser("evaluate", help="validate and compare candidates")
    evaluate.add_argument("--candidates", nargs="+", required=True, metavar="ID")
    evaluate.add_argument("--incumbent", metavar="ID")

    inspect = commands.add_parser("inspect", help="inspect workspace, candidate, or run evidence")
    inspect.add_argument("key", nargs="?", metavar="ID")

    resume = commands.add_parser("resume", help="start a fresh attempt from an interrupted run")
    resume.add_argument("run_id", metavar="RUN_ID")

    select = commands.add_parser("select", help="report or apply a completed run's selection")
    select.add_argument("run_id", metavar="RUN_ID")
    select.add_argument("--apply", action="store_true", help="atomically update the preferred candidate reference")

    attach = commands.add_parser("attach-evidence", help="attach profiling, SASS, or ablation evidence to a run")
    attach.add_argument("run_id", metavar="RUN_ID")
    attach.add_argument("artifact", type=Path)
    attach.add_argument("--kind", required=True, choices=("profile", "sass", "ablation"))
    attach.add_argument("--candidate", required=True, metavar="ID")
    attach.add_argument("--case-id")
    attach.add_argument("--architecture")
    attach.add_argument("--symbol")
    attach.add_argument("--dependency-revision")
    attach.add_argument("--experiment-group")

    return parser


def _worker_parser() -> argparse.ArgumentParser:
    # Kept separate from the public subparser list so --help remains focused.
    parser = _JsonArgumentParser(
        prog="python3 -m kda_experiments _worker",
        description="Internal controller-admitted batch worker.",
    )
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--batch-request", required=True, type=Path)
    parser.add_argument("--batch-result", required=True, type=Path)
    return parser


def _require_context(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.task is None or args.workspace is None:
        raise ValueError("--task and --workspace are required for this command")
    _, task_path = load_task(args.task)
    return task_path, args.workspace.resolve()


def _ok_result(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    engine_status = result.get("status")
    if engine_status is not None:
        result["engine_status"] = engine_status
    result["status"] = "ok"
    return result


def _worker(args: argparse.Namespace) -> int:
    request_path = args.batch_request.resolve()
    result_path = args.batch_result.resolve()
    request_id = None
    try:
        batch_request = load_json(request_path)
        if not isinstance(batch_request, dict):
            raise ValueError("batch request must be a JSON object")
        request_id = batch_request.get("request_id")
        result = engine.execute_batch_worker(
            batch_request,
            task_path=args.task.resolve(strict=True),
            workspace=args.workspace.resolve(),
        )
        if result.get("request_id") != request_id or result.get("status") != "complete":
            raise KDAExperimentError("batch worker returned an invalid or unsuccessful result")
        from .store import atomic_write_json

        atomic_write_json(result_path, result)
        return 0
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "request_id": request_id,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            from .store import atomic_write_json

            atomic_write_json(result_path, failure)
        except Exception:
            pass
        _JsonArgumentParser._emit(failure, sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    task_path, workspace = _require_context(args)
    if args.command == "register":
        value = register_candidate(
            workspace,
            args.candidate_id,
            args.source_dir,
            args.manifest,
            parent=args.parent,
            hypothesis=args.hypothesis,
            change=args.change,
            baseline=args.baseline,
            experiment_group=args.experiment_group,
        )
        return _ok_result({"candidate": value}), 0

    if args.command == "prepare":
        results = engine.prepare_candidates(task_path, workspace, args.candidate_ids, jobs=args.jobs)
        passed = all(item.get("status") == "ok" for item in results)
        return {"status": "ok" if passed else "error", "results": results}, 0 if passed else 1

    if args.command == "evaluate":
        value = engine.evaluate_candidates(task_path, workspace, args.candidates, args.incumbent)
        if value.get("status") != "complete":
            raise KDAExperimentError(f"evaluation did not complete successfully: {value.get('status')!r}")
        return _ok_result(value), 0

    if args.command == "inspect":
        return _ok_result(engine.inspect_workspace(workspace, args.key)), 0

    if args.command == "resume":
        value = engine.resume_evaluation(task_path, workspace, args.run_id)
        if value.get("status") != "complete":
            raise KDAExperimentError(f"resumed evaluation did not complete successfully: {value.get('status')!r}")
        return _ok_result(value), 0

    if args.command == "select":
        return _ok_result(engine.select_run(workspace, args.run_id, apply=args.apply)), 0

    if args.command == "attach-evidence":
        value = engine.attach_evidence(
            workspace,
            args.run_id,
            args.artifact,
            kind=args.kind,
            candidate_id=args.candidate,
            case_id=args.case_id,
            architecture=args.architecture,
            symbol=args.symbol,
            dependency_revision=args.dependency_revision,
            experiment_group=args.experiment_group,
        )
        return _ok_result({"evidence": value}), 0

    raise ValueError(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    # Install cancellation handling before either the public controller path
    # or the admitted internal worker can start any evaluator subprocesses.
    install_termination_handlers()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "_worker":
        try:
            worker_args = _worker_parser().parse_args(arguments[1:])
            return _worker(worker_args)
        except SystemExit as exc:
            return int(exc.code or 0)
        except Exception as exc:
            _JsonArgumentParser._emit(
                {"status": "error", "error": str(exc), "error_type": type(exc).__name__},
                sys.stderr,
            )
            return 1

    parser = _parser()
    try:
        args = parser.parse_args(arguments)
        result, code = _dispatch(args)
        _JsonArgumentParser._emit(result, sys.stdout)
        return code
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        _JsonArgumentParser._emit(
            {"status": "error", "error": str(exc), "error_type": type(exc).__name__},
            sys.stdout,
        )
        return 1

