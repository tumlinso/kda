# KDA Entry for Agents

Use this page with any local or hosted agent applying KDA in a task workspace.
It is the consumer entrypoint; repository-level files such as [AGENTS.md](../AGENTS.md)
and [CLAUDE.md](../CLAUDE.md) describe work on this KDA checkout.

## Start from the task workspace

Read the task repository's agent instructions and inspect its code, tests, and
validation path first. The task repository retains authority over its code,
workflow, and artifacts. KDA does not require Project Control or another task
tracker; use the task repository's authority and any host policy that applies.
KDA supplies optional reusable guidance; it does not own downstream task state
or replace the task's independent reference, validator, benchmark, or
promotion rules.

For implementation or optimization, establish the operation, representative
shapes and dtypes, correctness tolerance and independent reference, baseline,
validation and evaluation commands, resource budget, and promotion criteria.
Write the initial `docs/draft.md` in the task workspace before implementation.
Use the [starter prompt](../prompts/basic-flow.md) and [agent flow](agent-flow.md)
to shape that draft and the work loop.

For research or profiling-only requests, use the relevant guidance below
without requiring a full task scaffold or optimization campaign. Invoke skills
by reading their `SKILL.md` files and following relevant references or helper
commands. A host may offer optional skill registration, but opening KDA does
not imply automatic or recursive discovery.

## Optional pinned skills

Resolve each path from the root of the KDA checkout, including when the agent's
current directory is the separate task workspace. Read only the references
relevant to the request:

- [KernelBender](../skills/KernelBender/skills/kernelbender/SKILL.md) for an
  optional structural design review when representation, composition, or reuse
  can change materially.
- [KernelWiki](../skills/KernelWiki/SKILL.md) for GPU architecture and
  implementation contracts.
- [ncu-report-skill](../skills/ncu-report-skill/SKILL.md) for Nsight Compute
  profiling and report interpretation.

These skills advise the agent; the task's own correctness contract and
evaluation remain authoritative. Record the consumed skill revisions and the
identity of relevant source, report, or evidence in the task workspace.

## Evaluation and evidence

Use the task's established validation or analysis approach for a single
candidate or a research request.
When comparing candidates repeatedly, the optional
[`kda_experiments` engine](experiment-engine.md) can standardize snapshots,
builds, independent correctness gates, measurements, evidence, and selection.
It does not design kernels, supply task references, or replace the agent's
research and decision loop.

Follow the task repository's project authority and the host's GPU execution
controller, admission, and budget rules. Never infer execution authorization
from device visibility alone. Keep implementation, generated files, and raw
evidence in the task workspace; do not add task-specific material to KDA.

## Copyable launch instruction

Replace the placeholder with the local KDA checkout path when starting an
agent in the task workspace. The instruction is runtime-neutral; use direct
file reads and shell commands when no skill registry is available:

> Use KDA at `<KDA_CHECKOUT>` as an optional workflow reference. Read
> `<KDA_CHECKOUT>/docs/agent-entry.md`, then read only the relevant skill
> instructions and references from that checkout. Follow this task repository's
> instructions and keep implementation and evidence in this workspace.
