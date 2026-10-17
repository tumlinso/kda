# Repository instructions

Follow `CLAUDE.md` for repository scope and contribution conventions. Keep
repository plans in `planning/` and use supported Project Control operations
to change authoritative task state.

Use configured Codex subagents for delegated engineering. Project Control local
workers are observers only; do not use them for engineering assignments.

<!-- project-control:start -->
## Project Control workflow

For substantial repository work, use `project-control`. Start with `next_task`,
use `inspect_task` for bounded current-task context, and use `coordinate_task`
for typed synchronization. Rich Project Control reads are secondary escalation
tools when bounded workflow context is insufficient.

Todo Orchestrator remains the transactional authority. First-class Codex agents
receive lanes and roles; local workers are optional bounded children of exactly
one parent claim and never become first-class participants.
<!-- project-control:end -->
