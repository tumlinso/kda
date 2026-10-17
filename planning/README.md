# KDA planning

Keep repository plans, design notes, and supporting evidence here. This directory
covers the reusable KDA workflow; task-specific kernel implementations and
benchmark artifacts belong in separate implementation workspaces.

Project Control workspace `kda` registers repository `kda` at
`/home/tumlinson/kda`. Use Project Control for substantial repository work.

Todo Orchestrator is the task authority. Its project identity is recorded in
`.todo-orchestrator/project.json`, and its live SQLite database is stored under
the Git common directory at `todo-orchestrator/<project_uuid>/state.sqlite3`.
The snapshot and generated Markdown files are recovery and status projections.
Plans in this directory do not directly change task state.

The authority starts empty. Add executable work through supported Project
Control planning tools when the next objective is defined.
