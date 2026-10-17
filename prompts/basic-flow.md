# Kernel Design Agents Basic Flow Prompt

You are working in a task implementation workspace. Your job is to produce the best correct implementation for the task described below.

## Task Contract

- Task name: `<fill in>`
- Objective: `<fill in the user-facing goal>`
- Correctness requirements: `<fill in required behavior, tolerances, or invariants>`
- Performance or quality target: `<fill in measurable target if any>`
- Allowed implementation approaches: `<fill in languages, libraries, APIs, or constraints>`
- Validation command: `<fill in the command that proves correctness>`
- Evaluation command: `<fill in the command that measures the target, if different>`
- Promotion criteria: `<fill in what must be true before a candidate is accepted>`

## Workflow

1. Read the repository structure, existing implementation, tests, and task documentation.
2. Identify the baseline behavior and the validation path.
3. Research only the references needed for this task.
4. Write an implementation-plan draft to `docs/draft.md`.
5. Turn the draft into an executable plan before editing code.
6. Implement candidates in the task workspace. For competing approaches, preserve independent candidate directories and their parent/change/hypothesis records.
7. Run the task's independent correctness validation before measuring each candidate. For a repeatable batch, use `kda_experiments` as documented in `docs/experiment-engine.md`; keep validation and benchmark drivers outside candidate-controlled sources.
8. Record candidate results, parent relationships, workload and environment identity, and evidence in the workspace.
9. Keep the final change scoped to the task contract.

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
