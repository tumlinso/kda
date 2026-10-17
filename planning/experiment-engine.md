# Reproducible candidate experimentation

## Goal and boundary

Extend upstream KDA's prompt-led workflow with a replaceable, standard-library
Python experiment package. Task workspaces own kernels, independent references,
validators, benchmark drivers, data, and generated evidence. KDA continues to own
the agent workflow; Project Control continues to own repository task state.

Implement candidate registration and preservation, strict evaluation contracts,
bounded CPU builds, serialized validation and timing, evidence-based selection,
and resumable records. Preserve `candidates.jsonl`, tabular benchmark evidence,
and `runs/` conventions. Promotion changes a comparison-group reference, never
silently overwrites candidate sources.

No GPU work is part of the initial implementation. Do not edit, fetch, switch,
or change gitlinks for either skill submodule. The user will announce readiness;
final dependency qualification and one bounded SM70 demonstration remain deferred.

## Source assessment

Inspected KDA at `1d599951c6eb39f73aff50137c043a9b47b1918c` and CUDA Kernel
Optimizer at `114a6cba4c194e18d3fe23a4fc2251c982f34309` in the separate
`cuda-optimized-skill` checkout. KDA defines the workflow and evidence conventions
but has no first-party executable evaluator, selector, or state parser.

| Mechanism | Decision |
| --- | --- |
| Independent branch builds and retained alternatives | Implement a smaller KDA-native equivalent. |
| Correctness before timing; pristine inputs and multiple cases | Task-owned independent harness with strict result checks. |
| Warmup, raw samples, dispersion, repeated evaluation | Retain the principles; no universal kernel ABI or tensor comparator. |
| Persistent candidate relationships and environment evidence | Extend KDA's existing file conventions. |
| Optimizer state/controller and method registry | Omit; duplicate KDA and Project Control responsibilities. |
| Profiling and architecture catalogs | Consume existing skill interfaces; do not duplicate. |
| Ablation | Related candidates and explicit experiment groups; no automatic campaign. |
| SASS checks | Scoped evidence attachments; no generic opcode-based promotion gate. |

The optimizer's branch runner is coupled to its `solve` ABI and bundled harness.
Its OOM retry can shrink a candidate's workload while retaining original
baseline timings. Its validation casts values to FP32, and its architecture
fallback assumes a newer GPU. These are source-inspection findings, not GPU
runtime results. Do not transfer these assumptions. Implement fresh code;
preserve the MIT notice if any optimizer implementation is later adapted.

## Contracts and evidence

Versioned task JSON declares workloads and input identities, trusted harness and
reference inputs, argv commands, numerical requirements, timing protocol,
objective, promotion rules, target/toolchain, launcher policy, and budgets.
Fresh request identities bind every result. Require complete case coverage,
executed workload identity, matching units/protocol, finite positive samples,
and successful process completion. OOM and unsupported cases are failures,
never implicit smaller benchmarks. Numerical semantics remain task-owned.

Candidate source snapshots and dependencies, built artifacts, trusted evaluation
inputs, commands, tools, environment, and dependency revisions have recorded
identities. Per-attempt evidence is retained; summaries and preferred references
are atomic. Interrupted or changed stages get new attempts. Existing unrelated
records are preserved. Comparison groups bind the evaluation contract and actual
hardware/software environment, excluding candidate-specific source identity.

Build fanout is explicitly CPU-only and bounded. All validation and timing are
serialized inside an execution batch. Ordinary installations may use explicit
direct mode; controlled hosts use an external launcher with no direct fallback.
The CUDA controller recipe keeps builds before its lease and GPU work inside
admission. No host path, physical device number, or topology is embedded.

Compare per-case medians through weighted geometric benefit ratios. Shuffle
candidate order reproducibly, measure the incumbent in the same rounds, and
confirm the leading challenger with fresh paired rounds. Bootstrap round
vectors, retain per-case regression checks, and keep the incumbent when
uncertainty or task criteria prevent promotion. Do not interpret profiler replay
timing as production throughput.

## Increments and acceptance

1. Contracts, candidate preservation, provenance, records and inspection.
2. Build/evaluation execution, selection and conservative resume.
3. Launcher integration, CLI fixture, documentation and regression tests.
4. Deferred: user-approved completed dependency revisions and admitted V100 demo.

Use configured Luna subagents for coherent implementation and independent
validation. Root owns integration and acceptance. Run focused standard-library
unit tests and an independent CPU-only CLI fixture. Include malformed/stale
results, incomplete cases, shape changes, NaN/Inf, noisy selection, interrupted
work, environment drift, failed alternatives, and denied admission. Synthetic
fixture timings exercise machinery and are never performance evidence.

## Upstream relationship

Verified on 2026-10-17: NVIDIA `https://github.com/NVlabs/kda.git` main is
`ef6ce617693ef0782b3ecb9f37e39bbf10226a90`; the initial fork has two additional
commits and no missing upstream commits. Added an `upstream` remote and fetched
main without merging it. Preserve normal ancestry and individually removable
components. Prefer upstream equivalents when they satisfy these contracts.

## Delivered and validated

Implemented the optional `kda_experiments` CLI, strict task/result contracts,
candidate snapshots, CPU-only build preparation, compiler target checks,
serialized validation and repeated measurements, independent confirmation,
comparison-group promotion, inspect/resume, and scoped evidence attachments.
The execution adapter submits one batch to the independently installed CUDA
controller and never falls back to direct execution after rejection. Runtime
code and its tests remain separately replaceable from upstream's agent flow.

Validation on 2026-10-17:

- `python3 -m unittest discover -s tests -v`: 59 tests passed in 117.673 seconds.
- Independent `python3 -m unittest tests.test_cli_integration -v`: 15 tests
  passed in 86.184 seconds against frozen package sources.
- Focused contract/engine and process/adapter suites passed; cancellation was
  also repeated across nested and full fake-controller chains.
- Source review identified and verified fixes for result-protocol gates,
  identity drift, stale promotion, denied-controller finalization, and both
  promotion crash-recovery windows. `git diff --check` passed.

All fixtures are CPU-only. Their fixed synthetic timing values exercise
selection machinery and make no performance claim. No CUDA runtime work,
real controller admission, profiling, or Volta qualification was performed.
Declared input manifests are the provenance boundary: include evaluation
drivers, references, launcher/site configurations and their transitive inputs.

A concurrent merge (`baae5f2`, incorporating `38ecc78`) updated the
ncu-report-skill gitlink during implementation. That independently produced
change was preserved. This work did not modify, fetch, switch, or qualify either
skill submodule. The user readiness hold remains in effect for dependency
integration and the SM70 demonstration.
