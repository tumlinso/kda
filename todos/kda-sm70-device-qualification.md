

<!-- todo-orchestrator:v2-managed:start -->
# KDA-SM70-DEVICE-QUALIFICATION: Qualify the experiment engine through real V100 controller execution

Task revision: `10`; current project revision is in `todo-status.md`.

## Objective
Complete a bounded native SM70 qualification of the shipped KDA engine: independent numerical correctness and negative control, real repeated CUDA-event timing, evidence-based selection, controller receipts and release, sanitizer checks, interrupted-run resume, and one profiling/diagnosis path through completed skills. Preserve task-owned kernels and raw evidence outside tracked KDA source.

## State
- Lifecycle: `done`
- Execution: `closed`
- Parallel policy: `serial`
- Result: `validated`

## Next Action
Prepare a separate native reduction workspace, freeze its contracts, run all device stages through the CUDA controller, fix concrete integration defects, review evidence, archive it and publish bounded qualification.

## Ownership
- `exclusive`: `docs/experiment-engine.md`
- `exclusive`: `kda_experiments`
- `exclusive`: `planning/device-qualification.md`
- `exclusive`: `planning/device-qualification.todo.json`
- `exclusive`: `tests`
- `read`: `skills/KernelWiki`
- `read`: `skills/ncu-report-skill`

## Dependencies
_None._
<!-- todo-orchestrator:v2-managed:end -->
