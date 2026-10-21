# Agent Flow

Kernel Design Agents is a repeatable loop for agent-driven implementation work. The loop is useful when a task needs both exploration and evidence-based promotion decisions.

Agents applying KDA from another repository should start at
[`agent-entry.md`](agent-entry.md), which explains workspace ownership, skill
invocation, and when a full optimization loop is appropriate.

## Principle

Keep the reusable workflow separate from the task workspace. This repository explains the flow. The task workspace owns code, tests, datasets, benchmark scripts, private rules, and generated artifacts.

MLSys-style benchmark work is one possible application of this loop. The same flow can also be used for compiler passes, runtime kernels, infrastructure changes, or other performance-sensitive tasks.

## Minimal Loop

1. Define the task contract.
2. Let the agent inspect the local workspace.
3. Make the agent write `docs/draft.md`.
4. Convert the draft into an executable plan.
5. Implement the first candidate.
6. Validate correctness.
7. Measure the target metric when applicable.
8. Record evidence and decide whether to keep, revise, or reject the candidate.
9. Repeat until the promotion criteria are met or the remaining blockers are explicit.

The existing agent loop stays authoritative: agents research, implement,
profile, diagnose, and choose the next experiment. When a task benefits from
evaluating competing implementations consistently, the task can use the
optional `kda_experiments` runner to register candidates, build them, validate
every required case, then measure passing candidates in a serialized batch and
retain evidence for selection. See
[`experiment-engine.md`](experiment-engine.md) for its task contract and
extension boundary. A task can continue using the simple one-candidate flow
when a batch evaluator is not useful.

When relevant, read the pinned skill instructions and linked references from
the KDA checkout: KernelWiki for architecture research and ncu-report-skill for
profiling and report interpretation. Resolve these paths against KDA, not the
separate implementation workspace. Record component revisions and retrieved
source or report identities. Host-specific skill registration is optional.

## Optional Structural Design Review

When a task leaves meaningful freedom in representation, composition, or reuse,
or the caller requests a structural rethink, an agent may consult the
experimental KernelBender skill before settling the design in `docs/draft.md`.
The pinned entry point is
`skills/KernelBender/skills/kernelbender/SKILL.md`; read its instructions and
follow its relevant references. A conventional or library solution remains
valid. Keep KDA’s task contract, independent correctness
validation, and evaluation loop authoritative. Re-enter this review if new
evidence exposes a structural limit or the caller changes reuse, output, or
target constraints; routine tuning can continue without repeating it.

## Task Contract

Each task should state:

- Objective.
- Inputs and outputs.
- Target GPU and toolchain constraints, with representative shapes and dtypes.
- Correctness requirements.
- Independent reference and baseline.
- Constraints on implementation language, dependencies, APIs, or deployment.
- Validation command.
- Evaluation command, if different from validation.
- Resource budget.
- Promotion criteria.

## Evidence Records

Use simple files in the task workspace:

- `docs/draft.md` for the first plan draft.
- `docs/plan.md` for the executable plan.
- `benchmark.csv` or another tabular log for measurable results.
- `candidates.jsonl` for candidate names, parent links, and status.
- `profile/` for profiler output or report summaries.
- `runs/` or `outputs/` for generated artifacts.

The exact format is less important than consistency. A future reader should be able to reconstruct what changed, what was measured, and why a candidate was promoted.

When using `kda_experiments`, keep candidate sources separate from the task's
independent reference and evaluation drivers. Declare numerical requirements
in the task validator and preserve raw timing samples, workload identities,
and environment evidence with each run. Synthetic CPU fixture timings test
the evaluator only; use admitted hardware measurements for performance claims.

## Promotion Rule

Promote a candidate only when it satisfies the task contract and has evidence that it improves or preserves the target metric. If a candidate is rejected, record the reason instead of silently discarding it.
