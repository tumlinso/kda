# Prompt Templates

This directory stores generic prompts for the Kernel Design Agents workflow.

Agents working in another repository should start with the
[KDA agent entrypoint](../docs/agent-entry.md); it explains how this prompt,
the optional instruction/reference bundles, and the experiment engine fit
together. The prompt and workflow use plain text files and shell commands, so
they do not require a particular model or agent runtime.

The templates are intentionally task-agnostic. Fill in the task objective, constraints, validation command, and promotion criteria before starting an agent session in a separate implementation workspace.

## Available Templates

| Path | Purpose |
|---|---|
| `basic-flow.md` | Implementation and optimization prompt covering planning, validation, measurement, and iteration. |

## How To Use

For implementation or optimization work:

1. Create or enter the task implementation workspace.
2. Copy the relevant template content into the agent session.
3. Replace placeholders with task-specific details.
4. Ask the agent to read the workspace and write `docs/draft.md`.
5. Convert that draft into an executable plan.
6. Run the implementation loop with validation after each meaningful change.

For research or profiling alone, use the relevant instructions and helpers
linked from the agent entrypoint; this full template is optional.

Task-specific prompts should live with the task they describe. Do not add benchmark-specific datasets, acceptance tables, or private evaluator details to this generic repository.
