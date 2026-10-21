# Kernel Design Agents

Kernel Design Agents (KDA) is a workflow for local and hosted agents to
research, implement, verify, profile, and optimize NVIDIA CUDA kernels.
This published fork retains compatibility
with NVIDIA's upstream KDA workflow and adds an optional standard-library
candidate evaluator plus three pinned instruction/reference bundles for
structural design, architecture knowledge, and profiler report analysis.

Its docs and prompts use ordinary repository files and shell commands; they
do not require a particular agent runtime, model API, or global skill registry. The included
instruction bundles can be read directly, with optional host-specific skill
registration where available.

## Start a task

Begin in the task's own repository or implementation workspace. Read its
instructions and identify the code, tests, correctness reference, evaluation
commands, project authority, and any GPU execution controls. KDA is workflow
guidance; the task repository owns implementation, validation inputs, and
evidence.

For a new implementation or optimization task, define the operation and target
GPU, representative shapes and dtypes, tolerance and independent correctness
reference, metric and baseline, resource budget, and promotion criteria. Copy
and fill [the starter prompt](prompts/basic-flow.md), then use
[the consumer entrypoint](docs/agent-entry.md) to guide the agent. Write
`docs/draft.md` in the task workspace before editing implementation code.

For a research-only or profiling-only request, read the relevant guidance and
use the matching pinned reference bundle without creating a full optimization
task or candidate-engine setup.

```text
Use KDA at <KDA_CHECKOUT> as an optional workflow reference. Read
<KDA_CHECKOUT>/docs/agent-entry.md and follow this task repository's
instructions. Keep implementation and evidence in this task workspace.
```

No host-specific setup is needed beyond a readable KDA checkout and the tools
required by the task. When using the optional candidate evaluator, use Python 3
as described in [the experiment engine guide](docs/experiment-engine.md).

## What is included

| Path | Purpose |
|---|---|
| `docs/agent-entry.md` | Consumer entrypoint for work in another task workspace. |
| `docs/agent-flow.md` | Reusable design, implementation, and evidence loop. |
| `prompts/basic-flow.md` | Copyable task prompt with contract fields. |
| `docs/experiment-engine.md` | Optional candidate evaluator and evidence format. |
| `skills/` | Pinned instruction and reference bundles; use only as relevant. |

The docs distinguish repository editing from downstream use: `AGENTS.md` and
`CLAUDE.md` describe work on this KDA checkout. For a task in another
repository, start at `docs/agent-entry.md` and follow that task repository's
authority and instructions.

## Checkout and optional reference bundles

The evaluator can be used without initializing the skill submodules. To use
the pinned reference bundles, clone the KDA checkout and initialize its
recorded submodule revisions:

```bash
KDA_CHECKOUT=/path/to/kda
git clone https://github.com/tumlinso/kda.git "$KDA_CHECKOUT"
git -C "$KDA_CHECKOUT" submodule update --init --recursive
git -C "$KDA_CHECKOUT" submodule status
```

This fork's `.gitmodules` entries use SSH URLs for the independently maintained
skill forks. Initializing them therefore requires a GitHub SSH key with access
to those repositories, even though the KDA root is cloned over HTTPS. The
submodule command checks out the revisions recorded by KDA; `git submodule status`
shows those revisions. Directly reading their `SKILL.md` files and
linked references works independently of host-wide registration.

For NVIDIA's upstream KDA project, use its
[official repository](https://github.com/NVlabs/kda). That checkout follows
upstream's own workflow and submodule configuration. This fork's evaluator,
KernelBender route, and component revisions listed below remain optional
additions to that workflow.

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

KernelBender is an optional experimental design reference for reconsidering
computation structure when a task leaves meaningful freedom in representation,
composition, or reuse. The three pinned bundles have separate purposes:
KernelBender for structural design, KernelWiki for architecture knowledge, and
ncu-report-skill for Nsight Compute profiling and report interpretation. They
can be read directly from the KDA checkout. No automatic discovery or
registration is implied.

These submodules are not covered by this repository's first-party license. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the applicable license text and additional details.

One archived V100 attention study demonstrates the complete design-to-promotion
workflow and reports a positive result. It does not establish qualification on
newer GPU generations or a causal performance benefit from any one reference
bundle. See the [integration closeout](planning/integration-closeout-2026-10-21.md)
for evidence and limits. New tasks still need their own trusted correctness
reference, validator, and workload-specific acceptance criteria.

The workflow can use a task's existing harness. For repeatable batches of
competing candidates, the optional [`kda_experiments` evaluator](docs/experiment-engine.md)
retains candidate snapshots and evidence while the agent chooses what to try
and the task defines acceptance criteria. Validated CuTe candidates can be
[exported as Hugging Face kernels](docs/huggingface-export.md).

## Upstream community wishlist

The NVIDIA upstream project also has a community wishlist. Have a kernel that
needs optimization? [Submit a request](https://github.com/NVlabs/kda/tree/wishlist#submit)
as a pull request to `wishlist`, with a reproducible definition,
representative workloads, and the best-known baseline. The wishlist currently
supports NVIDIA B200 and B300 GPUs only. [Browse and upvote requests](https://github.com/NVlabs/kda/pulls?q=is%3Apr%20base%3Awishlist),
[discuss an idea](https://github.com/NVlabs/kda/issues/new?title=%5Bwishlist%5D%20),
or visit the [project website](https://nvlabs.github.io/kda/). Request details
belong in `requests/<github-username>-<kernel-name>/README.md`; use the
[wishlist PR template](.github/PULL_REQUEST_TEMPLATE/wishlist.md). Merging
records the request, while optimization progress and result links remain on
the original pull request. Website source lives on `pages`; the PR template
and issue chooser settings are maintained on `main`.

## Contributing

This project accepts outside contributions under the Developer Certificate of Origin process. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Except for the third-party submodules identified above, first-party documentation, prompts, skills-style content, and assets are licensed under the [Creative Commons Attribution 4.0 International License](LICENSE), and first-party source code is licensed under the [Apache License 2.0](LICENSE).
