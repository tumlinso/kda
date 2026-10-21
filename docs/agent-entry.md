# KDA Entry for Agents

Use this page when applying KDA to a task in another repository. It is the
consumer entrypoint; [AGENTS.md](../AGENTS.md) and [CLAUDE.md](../CLAUDE.md)
describe work on KDA itself.

## Start from the task workspace

Read the task repository's agent instructions and inspect its code, tests, and
validation path first. The task repository retains authority over its code,
workflow, and artifacts. KDA supplies optional reusable guidance; it does not
own downstream task state or replace the task's independent reference,
validator, benchmark, or promotion rules.

For implementation or optimization, establish the operation, representative
shapes and dtypes, correctness tolerance and independent reference, baseline,
validation and evaluation commands, resource budget, and promotion criteria.
Write the initial `docs/draft.md` in the task workspace before implementation.
Use the [starter prompt](../prompts/basic-flow.md) and [agent flow](agent-flow.md)
to shape that draft and the work loop.

For research or profiling-only requests, use the relevant guidance below
without requiring a full task scaffold or optimization campaign. Invoke skills
explicitly through the host agent mechanism; do not assume that opening KDA
causes recursive skill discovery.

## Optional pinned skills

Resolve each path from the root of the KDA checkout, including when the agent's
current directory is the separate task workspace. Use only the skills relevant
to the request:

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

Use the task's established evaluator for a single candidate or a research task.
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
agent in the task workspace:

> Use KDA at `<KDA_CHECKOUT>` as an optional workflow reference. Read
> `<KDA_CHECKOUT>/docs/agent-entry.md`, then explicitly invoke only the
> relevant skills from that checkout. Follow this task repository's
> instructions and keep implementation and evidence in this workspace.
