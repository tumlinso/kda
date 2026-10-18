# Candidate experiment engine

KDA's existing agent flow remains responsible for research, candidate design,
implementation, profiling, and deciding what to try next. The optional
`kda_experiments` package makes candidate evaluation, evidence retention, and
selection repeatable. It does not generate kernels or run a second agent
controller. A task workspace still owns its implementation, independent
reference, validators, benchmark driver, inputs, and numerical requirements.
The current engine targets POSIX hosts, matching its file-lock and process-group
execution controls.

## Source and extension boundary

KDA's upstream workflow already describes the optimization loop and workspace
evidence conventions; before this extension it did not provide an executable
candidate evaluator, selector, or experiment state reader. CUDA Kernel
Optimizer's branch runner demonstrates independent builds, correctness gates,
repeated measurements, and retained alternatives, but it is tied to its own
operator ABI and benchmark harness. The KDA engine implements those useful
principles against task-owned commands and keeps KDA's workflow authoritative.
Source inspection also found workload shrinking after OOM, validation that
casts values to FP32, and a newer-architecture fallback. Those behaviors can
invalidate comparisons or numerical contracts, so the KDA evaluator implements
the principles afresh instead of importing the runner.

The engine owns candidate identity and snapshots, build/evaluation stages,
result validation, experiment records, comparisons, and preferred-candidate
references. Task workspaces own candidate code and all trusted evaluation
inputs; candidate sources cannot replace the reference, validators, or timing
driver. Project Control remains authoritative for repository tasks.

The custom runtime lives entirely in `kda_experiments/`; tests live in `tests/`.
Necessary upstream integration edits are limited to `README.md`,
`docs/agent-flow.md`, and `prompts/basic-flow.md`. This guide and the repository
plan are additions. The runtime imports neither skill submodule: architecture
research and profiling remain agent actions, with their references and artifacts
recorded alongside experiments. The engine and its CPU checks work independently
of both ports, and individual runtime components can be replaced by upstream
equivalents without replacing the agent workflow.

## Use

Run the CLI from the KDA checkout root so Python can import the package. For
another working directory, add the checkout root to `PYTHONPATH`. Task and
workspace paths may point to a separate task workspace:

```text
python3 -m kda_experiments --task task.json --workspace WORKSPACE COMMAND
```

Available commands are `register`, `prepare`, `evaluate`, `inspect`, `resume`,
`select`, and `attach-evidence`. Candidate registration records a source
directory, a declared manifest, a hypothesis, a change description, and
optionally a parent or baseline marker. `prepare` builds registered candidates;
`evaluate` prepares candidates, validates them against every required case,
then measures only those that pass. `inspect` reads candidate or run evidence;
`resume` starts a fresh attempt from interrupted evidence; `select` reports or
applies a completed run's decision; and `attach-evidence` preserves profiling,
SASS, or ablation artifacts with a run. The subcommands take these arguments:

```text
register ID SOURCE_DIR --manifest MANIFEST --hypothesis TEXT --change TEXT [--parent ID] [--baseline] [--experiment-group LABEL]
prepare ID... [--jobs N]
evaluate --candidates ID [ID ...] [--incumbent ID]
inspect [ID]
resume RUN_ID
select RUN_ID [--apply]
attach-evidence RUN_ID ARTIFACT --kind {profile,sass,ablation} --candidate ID [metadata options]
```

Run `python3 -m kda_experiments --help` and the relevant subcommand's `--help`
for option details.

Task JSON uses `schema_version: 1` and declares `task_id`, `cases`, `commands`,
`trusted_inputs`, `numerical_requirements`, `probe`, `timing`, `promotion`,
`target`, `toolchain`, `execution`, and `budgets`. Each case has an `id`,
`weight`, input identity or seed, and optional parameters.
`numerical_requirements` is a non-empty task-defined JSON object passed through
to the validator. The command groups provide argv arrays for
`build`, `validate`, and `benchmark`; build must explicitly declare
`cpu_only: true` to permit parallel preparation. Use `{request}` and
`{result}` argv elements for the fresh JSON request and result paths. Arguments
are passed without a shell; other command arguments are not substituted. Each
command returns a JSON result envelope echoing the request's unique ID.
Validation reports exactly one explicit outcome and workload digest for every
required case. Each benchmark result reports the matching case and digest,
declared metric and unit, timing scope, warmup and repetition counts, and raw
samples. Malformed, missing, duplicate, stale, failed, or non-finite results
are rejected. OOM or unsupported cases fail the evaluation; the engine does
not shrink or skip workloads.

Declare the timing metric, unit, direction, warmup, repetitions, rounds,
confirmation rounds, seed, and scope. Declare the promotion minimum
improvement, maximum regression, confidence, and bootstrap sample count.
There are no implicit measurement or selection thresholds. `budgets.max_seconds`
is required. The CLI defaults `prepare --jobs` to one, bounded by the declared
`budgets.max_build_jobs`.

Set `target.kind` to `cpu` or `cuda`. For CUDA tasks, `target.architecture`
names the physical architecture such as `sm_70`; `target.compiler_target`
defaults to that value and can name an exact compiler-supported suffix token
such as `sm_90a`. The environment probe records actual device identity and
driver/runtime facts. CUDA targets require a compiler target probe and fail
before evaluation if the selected compiler does not report support for the
requested token. The KDA agent workflow can consult documented architecture
knowledge for implementation advice; the engine records probe facts and does
not carry an architecture advice database.

Numerical acceptance is task-owned. Supply an independent reference and a
validator that implements the operation's real dtype, tolerance, and semantic
requirements. The engine does not assume bitwise equality, cast values, or
choose universal tolerances. Trusted references and drivers should remain
outside candidate snapshots. The candidate manifest declares relative source
files and dependency revisions; the engine records their identities alongside
task/evaluator inputs, commands, tool and hardware probe results, and built
artifact hashes.

Build commands are serial by default. Parallel preparation is allowed only
when the task explicitly marks its build command CPU-only and is bounded by
the task's build-job budget. Validation and benchmark execution are serialized
as one evaluation batch. Direct mode is for ordinary installations. Launcher
mode delegates the batch to the configured launcher and fails closed if
admission or execution fails. On a controlled CUDA host, keep CPU-only builds
before controller admission and put probe, correctness checks, and timing
inside one admitted batch. The supplied adapter can be selected with
`execution.mode: "launcher"` and an argv such as:

```json
{
  "execution": {
    "mode": "launcher",
    "launcher_argv": [
      "python3", "-m", "kda_experiments.controller_launcher",
      "--config", "controller.json", "--request", "{request}",
      "--result", "{result}"
    ]
  },
  "trusted_inputs": [
    {
      "id": "site_execution_policy",
      "path": "/site/controller.json",
      "role": "toolchain"
    }
  ]
}
```

The adapter's separate site config supplies `controller_argv`,
`project_root`, `resources`, and `toolchain`. An optional `quiescence` object
passes the site's `timeout_seconds` (up to 60), `consecutive_idle_samples`
(1–64), and `interval_seconds` (up to 5) to the controller. Omit it to retain
controller defaults; slower host probes can need a longer observation window.
This changes the observation budget, never the idle acceptance requirement.
Use the installation-specific
paths and resource values in that config; KDA has no baked-in host paths,
device numbers, or topology. Add `site_execution_policy` to the task's
existing `trusted_inputs` alongside its reference and evaluator inputs. Also
declare the launcher executable/script and any transitive policy/config files
that affect toolchain, resources, admission, or execution, using the `toolchain`
or `other` role. The engine hashes declared inputs but cannot infer
configuration dependencies by parsing launcher argv. It submits one controller run with the worker's
exact argv and working directory using the controller's baseline run spec,
without asking the controller to repeat its own metric loop. The engine owns
the declared correctness and timing rounds. The adapter waits for controller
success and worker success, and returns the receipt. Builds are prepared before
this admission. There is no direct-execution fallback if launcher admission
or execution fails. Adapter tests use a fake controller; this recipe alone
does not qualify the actual host controller or GPU path.

## Evidence and selection

The task workspace keeps the existing `candidates.jsonl` and `benchmark.csv`
conventions and adds engine-owned evidence under
`runs/kda-experiments/{candidates,builds,attempts}/` plus preferred references
under `preferred/`.

Each attempt binds the request and result to candidate, task, trusted inputs,
commands, environment, dependencies, and binary identities. Summaries and
preferred references are atomically updated. Resume reuses a completed stage
only when its recorded inputs still match; otherwise it creates a new attempt.
Failed candidates and attempts remain inspectable.

The comparison group captures the task/evaluation contract and actual
hardware/software environment. Results from different groups are not ranked
together. The engine uses case weights and the declared minimize/maximize
direction to compare per-case medians aggregated across rounds by weighted
geometric benefit. Candidate order is deterministically shuffled and the
incumbent is measured in the same rounds. The leading challenger is remeasured
in fresh paired rounds; round-level bootstrap confidence, minimum total
improvement, and maximum per-case regression limits govern promotion. These
criteria are required task fields rather than hidden defaults. If evidence
does not meet them, the incumbent remains preferred.

Profiling evidence belongs to the exact candidate, binary, workload, and
environment. Nsight Compute replay time is diagnostic evidence and is not
substituted for benchmark throughput. SASS artifacts may support an
architecture- and symbol-scoped explanation but do not establish correctness
or performance by themselves.

## Architecture knowledge, dependencies, and upstream updates

KernelWiki supplies architecture guidance through its documented,
architecture-filtered queries and page references. ncu-report-skill supplies
profiling interpretation through its documented reports. When using either,
record the dependency revision and cite the page or report alongside the task
evidence. KDA does not duplicate their architecture catalog or profiling
pipeline. KDA pins the completed Volta ports through its existing submodules:
KernelWiki `244283cb8b57d1695af61aaa5e0cf5a04edfe9c9` and ncu-report-skill
`bbb60a67fcb44c65510386c7dd41bc327fb91d25`. See the top-level README for
checkout synchronization. Continue consuming their documented interfaces rather
than copying their architecture knowledge or profiler implementation.

Focused dependency consumer checks require no GPU:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 skills/KernelWiki/scripts/query.py --architecture V100 --type hardware --compact --limit 5
PYTHONDONTWRITEBYTECODE=1 python3 skills/KernelWiki/scripts/get_page.py hw-volta-mma --follow-sources
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/KernelWiki/tests -p 'test_volta_architecture.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/ncu-report-skill/tests -v
```

These exercise knowledge retrieval and offline profiling compatibility, rather
than collecting a new GPU profile or qualifying an engine optimization run.

The extension should remain a small set of replaceable modules and narrow
workflow edits. When upstream KDA adds equivalent behavior, compare it against
the contracts above, prefer upstream when it meets them, and retire redundant
custom code while retaining useful historical evidence.

Keep custom engine changes in coherent commits. To incorporate later upstream
work, fetch the NVIDIA KDA repository and merge its `main` into this fork's
feature branch as a separate integration change; resolve conflicts while
preserving the custom engine boundary, then run the focused regressions and
CPU example. Do not rebuild or replace upstream history. Check gitlinks
separately and update them only to inspected, compatible revisions.

## Validation status

The unit suite is run with:

```text
python3 -m unittest discover -s tests -v
```

The CPU-only CLI fixture can be run independently with:

```text
python3 -m unittest tests.test_cli_integration -v
```

The CPU-only example uses task-owned arithmetic and an independent
`math.fsum` reference. Its timing samples are deterministic synthetic values
labelled for testing: they demonstrate registration, correctness gating,
selection, evidence retention, and resume behavior, but are not performance
evidence. The completed dependency ports are pinned and available to KDA.
A bounded controller-backed V100/SM70 qualification passed on 2026-10-18:
independent FP32 references and negative control, native candidate compilation,
repeated CUDA-event comparison, selection/retention, real SIGTERM cleanup and
fresh resume, representative memory/race/synchronization checks, and one exact-
binary NCU report analyzed by the pinned skill. See
[device qualification](../planning/device-qualification.md) for scope, fixes,
regression results and the local evidence archive. This qualifies that device,
toolchain and workload contract; other kernels and environments still need
their own correctness and measurement evidence.
