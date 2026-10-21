# Kernel Design Agents Basic Flow Prompt

You are working in a task implementation workspace. Your job is to produce the best correct implementation for the task described below.

This template is for implementation and optimization tasks. For a research or
profiling-only request, start with the [agent entrypoint](../docs/agent-entry.md)
and use the relevant skill without requiring this full workflow. Resolve KDA
references against the KDA checkout, and keep this task's code, evidence, and
workflow state in its own project.

## Task Contract

- Task name: `<fill in>`
- Objective: `<fill in the user-facing goal>`
- Target: `<GPU architecture/device and relevant toolchain constraints>`
- Workloads: `<representative shapes, layouts, dtypes, and input guarantees>`
- Correctness requirements: `<fill in required behavior, tolerances, or invariants>`
- Independent reference and baseline: `<trusted correctness oracle and valid comparison implementation>`
- Performance or quality target: `<fill in measurable target if any>`
- Allowed implementation approaches: `<fill in languages, libraries, APIs, or constraints>`
- Validation command: `<fill in the command that proves correctness>`
- Evaluation command: `<fill in the command that measures the target, if different>`
- Promotion criteria: `<fill in what must be true before a candidate is accepted>`
- Resource budget: `<time, GPU resources, and experiment limits>`

## Workflow

1. Read the repository structure, existing implementation, tests, and task documentation.
2. Identify the baseline behavior and the validation path.
3. Research only the references needed for this task. Read
   `skills/KernelWiki/SKILL.md` for architecture contracts and
   `skills/ncu-report-skill/SKILL.md` for profiling and report interpretation
   when relevant. These are instruction/reference bundles: ordinary file reads
   and their documented commands are sufficient; runtime-specific skill
   registration is optional. Resolve these paths relative to KDA, even when
   implementing elsewhere, and record consumed revisions and source/report
   identities in task evidence.
4. If the task leaves meaningful freedom in representation, composition, or
   reuse—or the caller requests a structural rethink—consider the optional
   experimental KernelBender skill at
   `skills/KernelBender/skills/kernelbender/SKILL.md` before fixing the algorithm
   and kernel boundaries. Read that entry and the relevant references directly,
   or use an optional skill integration provided by the agent runtime. Carry
   its concise design decision and first
   discriminating experiment into `docs/draft.md`; a conventional or library route
   remains valid. Existing profile evidence can ground an optimization of an
   existing hotspot; a new design does not require a profile. Keep the task's
   independent numerical and semantic contract and normal KDA evaluation loop
   authoritative.
5. Write an implementation-plan draft to `docs/draft.md`.
6. Turn the draft into an executable plan before editing code.
7. Implement candidates in the task workspace. For competing approaches, preserve independent candidate directories and their parent/change/hypothesis records.
8. Run the task's independent correctness validation before measuring each candidate. For a repeatable batch, use `kda_experiments` as documented in `docs/experiment-engine.md`; keep validation and benchmark drivers outside candidate-controlled sources.
9. Record candidate results, parent relationships, workload and environment identity, and evidence in the workspace.
10. Keep the final change scoped to the task contract.

## Plan Draft Requirements

The draft in `docs/draft.md` should include:

- The current baseline and how it is validated.
- The main risks and unknowns.
- Candidate implementation directions ranked by expected value and risk.
- The first concrete implementation steps.
- The exact validation and evaluation commands to run.
- The evidence required to promote, revise, or reject a candidate.

For a batch-evaluated task, also record the task JSON path, candidate IDs and
incumbent, independent reference and validator, required workload cases,
numerical requirements, metric direction/units, and promotion thresholds. Use
the runner's evidence to support a decision; keep research, diagnosis, and
decisions about the next implementation in this KDA workflow. Treat synthetic
CPU fixture timings as test data, not performance measurements.

Do not start implementation until the draft exists.
