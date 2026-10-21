# KDA planning

Keep repository plans, design notes, and supporting evidence here. This directory
covers the reusable KDA workflow; task-specific kernel implementations and
benchmark artifacts belong in separate implementation workspaces.

To use KDA for another project's optimization task, start with the
[agent entrypoint](../docs/agent-entry.md). The registration and task-state
guidance below applies to maintaining KDA itself; downstream tasks retain their
own project authority and store their plans and evidence in their own workspace.

Plans and reviews here retain their authoring-time assumptions and holds. See
the [integration closeout](integration-closeout-2026-10-21.md) for completed
integration, qualification boundaries, and publication evidence; use the agent
entrypoint and current guides for new work.

Project Control workspace `kda` registers repository `kda` at
`/home/tumlinson/kda`. Use Project Control for substantial repository work.

Todo Orchestrator is the task authority for this workspace. Use the supported
Project Control operations to inspect and update task state; do not edit its
database or generated snapshot and Markdown projections directly. Plans in
this directory document objectives and implementation decisions, but do not
by themselves change authoritative task state.
