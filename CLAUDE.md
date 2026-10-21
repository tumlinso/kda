# Agent Instructions

This repository is the generic Kernel Design Agents workflow reference. It should stay small and task-agnostic.

For agents applying KDA to work in another repository, use the
[consumer entrypoint](docs/agent-entry.md). This file describes conventions for
work on KDA itself.

## Repository Rules

- Use English for repository-facing files, comments, documentation, prompts, and commit messages.
- Keep task-specific prompts, datasets, validators, generated implementations, benchmark logs, and candidate artifacts out of this repository.
- Treat benchmark competitions, including MLSys-style work, as downstream applications of KDA rather than as the scope of this repository.
- Put generated outputs in `runs/`, `outputs/`, or `profile/`; these paths are ignored by git.
- Prefer documenting reusable workflow mechanics over documenting one task's private harness or acceptance thresholds.

## Maintaining KDA

- Keep NVIDIA upstream's agent workflow usable; additions such as the experiment
  engine and pinned skills remain optional.
- Keep repository plans in `planning/` and use the project workflow in
  `AGENTS.md` for authoritative task state. This registration does not own tasks
  in consumer repositories.
- Preserve skill responsibilities and documented interfaces. KDA coordinates
  their use; the experiment engine owns evaluation and selection rather than
  kernel design or a second scheduler.
- Run checks relevant to the change. The full runtime/export suite is
  `python3 -m pytest tests -q`; documentation changes need link and consistency
  checks. Existing hardware evidence is not a new GPU qualification.
- Follow `CONTRIBUTING.md`, including signed-off commits and third-party notices.

The downstream design, implementation, validation, and promotion loop is
documented in `docs/agent-entry.md`, `docs/agent-flow.md`, and the starter prompt.
Keep those guides authoritative instead of duplicating their workflow here.
