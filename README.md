# Kernel Design Agents

Kernel Design Agents (KDA) is an agent-centric workflow for using coding agents to research, implement, verify, and iterate on performance-sensitive CUDA kernel tasks.

This repository documents an early research prototype and remains under active development. Community feedback and contributions are welcome. If you are interested in HAN Lab Mafia's solutions ranking #1–3 on tracks at the MLSys Kernel Contest, see [mit-han-lab/mlsys2026-flashinfer-contest](https://github.com/mit-han-lab/mlsys2026-flashinfer-contest) for performance evaluation and reproduction.

## Contents

| Path | Purpose |
|---|---|
| `docs/agent-flow.md` | Minimal end-to-end KDA workflow. |
| `docs/experiment-engine.md` | Optional candidate evaluator, evidence, and upstream extension boundary. |
| `prompts/README.md` | How to use prompt templates. |
| `planning/` | Repository plans and Project Control authority guidance. |
| `prompts/basic-flow.md` | Generic starter prompt for a new task. |
| `CLAUDE.md` | Repository-facing agent instructions. |
| `CONTRIBUTING.md` | Contribution process and DCO sign-off requirements. |
| `THIRD_PARTY_NOTICES.md` | Third-party component and license disclosures. |
| `third_party_licenses/` | Verbatim upstream license files for distributed third-party components. |

## Community Kernel Wishlist

Have a kernel that needs optimization? [Submit a request](https://github.com/NVlabs/kda/tree/wishlist#submit) directly as a pull request to `wishlist`, with a reproducible definition, representative workloads, and your best-known baseline implementation. No issue is required. The community wishlist currently supports NVIDIA B200 and B300 GPUs only.

[Browse and upvote requests](https://github.com/NVlabs/kda/pulls?q=is%3Apr%20base%3Awishlist), [discuss an idea](https://github.com/NVlabs/kda/issues/new?title=%5Bwishlist%5D%20) if you need help preparing the files, or visit the [project website](https://nvlabs.github.io/kda/). Keep request details in `requests/<github-username>-<kernel-name>/README.md` and use the [wishlist PR template](.github/PULL_REQUEST_TEMPLATE/wishlist.md) for the short description. Merging records the request, while optimization progress and result links remain on the original pull request. Website source lives on `pages`; the PR template and issue chooser settings are maintained on `main`.

## Getting Started
Install the agent workflow dependencies before starting the agent session:

```bash
git clone https://github.com/tumlinso/kda.git
cd kda
git submodule update --init --recursive
git submodule status

# link skills
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/ncu-report-skill" ~/.claude/skills/ncu-report-skill
ln -s "$(pwd)/skills/KernelWiki" ~/.claude/skills/KernelWiki
# optional design skill: link its nested entry directory
ln -s "$(pwd)/skills/KernelBender/skills/kernelbender" ~/.claude/skills/kernelbender

# or clone the independently licensed ncu skill directly
mkdir -p ~/.claude/skills && cd ~/.claude/skills
git clone https://github.com/mit-han-lab/ncu-report-skill.git
```

This fork's `.gitmodules` entries use SSH URLs for the independently maintained
skill forks. Initializing the submodules therefore requires a GitHub SSH key
with access to those repositories, even though the KDA root was cloned over
HTTPS. The update command checks out the revisions recorded by this KDA commit;
`git submodule status` shows those revisions.

For NVIDIA's upstream KDA project, use its
[official repository](https://github.com/NVlabs/kda). That checkout follows
upstream's own submodule configuration and does not include this fork's
additional integrations. When using this fork, prefer the pinned KernelWiki
submodule. A direct upstream KernelWiki checkout may contain artifact
snapshots governed by additional terms that are omitted from this
distribution.

## Submodules

The following third-party projects are included as Git submodules. The source URLs and revisions below are intentional and match the gitlinks recorded in this repository.

| Path | Source | Pinned revision | License |
|---|---|---|---|
| `skills/KernelWiki` | [tumlinso/KernelWiki](https://github.com/tumlinso/KernelWiki.git) | [`542ed702ac662422d55b19186562b29abbb5da29`](https://github.com/tumlinso/KernelWiki/commit/542ed702ac662422d55b19186562b29abbb5da29) | MIT for original material; embedded artifacts retain their upstream terms; restricted CuTe DSL artifacts are omitted |
| `skills/ncu-report-skill` | [tumlinso/ncu-report-skill](https://github.com/tumlinso/ncu-report-skill.git) | [`bbb60a67fcb44c65510386c7dd41bc327fb91d25`](https://github.com/tumlinso/ncu-report-skill/commit/bbb60a67fcb44c65510386c7dd41bc327fb91d25) | MIT |
| `skills/KernelBender` | [tumlinso/KernelBender](https://github.com/tumlinso/KernelBender.git) | [`2e19a747a3be2abfb12243db809a3e85ae8b5d42`](https://github.com/tumlinso/KernelBender/commit/2e19a747a3be2abfb12243db809a3e85ae8b5d42) | No license file selected |

The KernelWiki and ncu-report-skill revisions include the completed Volta knowledge and profiling ports.
After pulling KDA updates, synchronize the skill checkouts to the recorded pins:

```bash
git pull --ff-only
git submodule update --init --recursive
```

Use the committed gitlinks rather than automatically tracking skill branches.

KernelBender is an optional experimental design skill for reconsidering GPU
computation structure when a task leaves meaningful freedom in representation,
composition, or reuse. Its entry point is
`skills/KernelBender/skills/kernelbender/SKILL.md`; register or invoke that
path explicitly through the host agent mechanism. This integration does not
change KDA validation or establish a performance benefit.

These submodules are not covered by this repository's first-party license. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the applicable license text and additional details.

Agents can also explicitly invoke the entries at `skills/KernelWiki/SKILL.md`,
`skills/ncu-report-skill/SKILL.md`, and the KernelBender path above, resolved
against the KDA checkout. No host-global installation is required for that
route. See the [integration closeout](planning/integration-closeout-2026-10-21.md)
for the validated pair, actual skill-use evidence, and publication verification.

Install the `humanize` Claude Code plugin from the Claude Code plugin UI:

```text
/plugin marketplace add PolyArch/humanize
/plugin install humanize@PolyArch
```

## Minimal Flow

1. Create a separate implementation workspace for the target task.
2. Define the task contract: objective, constraints, validation command, and promotion criteria.
3. Start an agent session in the implementation workspace.
4. Give the agent `prompts/basic-flow.md`, filled in with the task-specific details.
5. Ask the agent to write a short plan draft to `docs/draft.md` in the implementation workspace.
6. Convert the draft into an executable plan, either manually or with a planning tool such as Humanize.
7. Implement in small iterations, verifying after each meaningful change.
8. Record candidates, benchmark or evaluation results, profiling evidence, and final promotion decisions. For repeatable candidate batches, use the optional [`kda_experiments` engine](docs/experiment-engine.md) from the existing agent workflow.

The workflow is intentionally independent of any single benchmark harness or hardware target. A downstream task can add its own evaluator, datasets, profiling tools, and domain-specific references.

Validated CuTe candidates can be [exported as Hugging Face kernels](docs/huggingface-export.md).

## Recommended Workspace Layout

Use this repository as reference material, then do implementation work elsewhere:

```text
task-workspace/
  docs/
    draft.md
    plan.md
  runs/
  outputs/
  profile/
  benchmark.csv
  candidates.jsonl
```

The exact files can change by domain. The important rule is that the agent records enough context for another engineer to understand what was tried, what passed validation, and why the final candidate was selected.

## Contributing

This project accepts outside contributions under the Developer Certificate of Origin process. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Except for the third-party submodules identified above, first-party documentation, prompts, skills-style content, and assets are licensed under the [Creative Commons Attribution 4.0 International License](LICENSE), and first-party source code is licensed under the [Apache License 2.0](LICENSE).
