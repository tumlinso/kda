# Bounded profiler-informed attention study

## Status and boundaries

The qualified experiment engine was merged onto `main` and pushed at
`669b3a1` before this study began. The merge preserved the fork's history and
did not combine an unrelated NVIDIA upstream update. Future upstream KDA
updates remain separate merges and must preserve the ordinary fork relationship.

The independent engineering review found the KDA evaluation engine and its
bounded V100 reduction evidence ready for real kernel work. It also identified
the remaining question this study addresses: whether an agent can use
architecture knowledge and measured profiler evidence to improve a difficult
kernel. The review was read-only and did not independently replay the archived
qualification. See [the review](engineering-review-2026-10-18.md) and
[the device qualification](device-qualification.md) for evidence and limits.

Use all four identical V100s opportunistically under the CUDA controller.
Limit the campaign to **60 summed GPU-minutes**, counting admitted duration
multiplied by reserved GPU count, including policy qualification, quiescence,
and cleanup. Reserve the final 10 GPU-minutes for confirmation and qualification.
CPU-only preparation does not use this budget. Keep final performance timing
isolated on one canonical GPU UUID.

This work may change KDA documentation and the separate CUDA skill's profiling
policy. It must not edit KernelWiki or ncu-report-skill sources or change their
submodule pins. Keep task kernels, inputs, and raw study artifacts in the
ignored, independently versioned workspace at
`runs/attention-decode-study/workspace`.

## Profiling policy

Update the CUDA skill so admitted NCU jobs lock their selected UUIDs
exclusively, in sorted order, while sharing the global profiling gate with
other per-device profiles. Timed benchmarks take the global gate exclusively.
Keep exclusive controller admission for each UUID, owner-specific intent
records, conservative host-wide exclusion when device identity is absent,
legacy marker behavior, cancellation cleanup, and explicitly requested PCIe or
NVLink isolation. Do not change Project Control allocation or schema.

Before running the attention task, pass focused concurrency, ownership, legacy
behavior, cancellation, and lock-order regressions. Then pass a native smoke
with overlapping NCU captures on distinct V100s and correct reports/device
identities; same-device contention must reject or serialize. Check that every
reservation is released and no child process remains. For this study's
independent resident kernels, explicitly disable PCIe-root and NVLink-domain
isolation when requesting per-device profiling. Concurrent replay profiles
are diagnostic evidence, not comparable throughput measurements.

## Task and numerical contracts

Freeze a dense causal GQA decode task with `Q=[1,8,1,D]` and
`K,V=[1,2,L,D]`. Use contiguous finite FP16-represented inputs and an
independent FP64 reference computed from those exact representations. The six
equally weighted performance cases cross `D ∈ {64, 70, 128}` with
`L ∈ {512, 4096}`. Freeze one benchmark seed and two held-out validation seeds
for each shape. Add correctness-only cases for a single key, odd tails, zero
scores, cancellation, independent GQA-head normalization, and high-contrast
scores. The default input domain is `|Q,K,V| ≤ 0.25`; identify stress cases
with `|Q,K| ≤ 4` as outside that domain.

Evaluate two separately identified precision tracks:

| Track | Contract |
|---|---|
| Strict | FP32 accumulation, normalization, probabilities, and output; output error at most `1.5e-4 + 2e-4 × |reference|`. |
| Mixed | FP16 intermediate probabilities and operands are permitted; accumulation, normalization, and output remain FP32; output error at most `1e-3 + 2e-3 × |reference|`. |

Both tracks require maximum-score absolute error at most `2e-5` and normalizer
error at most `1e-7 + 5e-4 × |reference|`. Also report mixed-track errors
against the strict output bound. Use distinct comparison groups and preferred
references for the two tracks. Freeze limits before evaluating candidates and
never relax them after a failure.

Adapt task-owned copies of the MIT-licensed KernelWiki oracle and baseline
source, retaining attribution and source revisions. Adapt the trusted native
runner to KDA's existing request/result contract; add no public experiment
engine API.

## Experiment and measurement sequence

First validate and measure three existing baselines across all six cases:
materialized cuBLAS, unsplit online attention, and split-16 online attention.
Freeze a transparent baseline portfolio that selects the strongest measured
route for each shape before comparing new candidates.

Explore at most four new candidate versions:

1. A distinct warp/CTA ownership strategy.
2. A GQA-aware strategy that shares K/V work while keeping query-head
   normalization independent.
3. A mixed-precision materialized path using FP16 probabilities and represented
   V values with FP32 accumulation.
4. One revision of the most promising valid candidate, motivated by actual
   profiler evidence.

A split-count change alone is not a distinct strategy. Record each candidate's
hypothesis, expected mechanism, falsifier, parent, and changes. Shape/layout
dispatch is allowed; input-value-dependent dispatch and benchmark-specific
shortcuts are excluded. Count conversions, materialization, partial merges,
and dispatch in operator timing. Preserve failed alternatives.

Parallelize CPU-only preparation and distribute independent correctness
prechecks across admitted GPUs. After policy qualification, allow up to four
simultaneous NCU captures on distinct UUIDs, with at most five attention
reports total. Bind every report to its actual UUID, binary, workload, and
environment. Attach a profile to an engine run only when it matches that run's
canonical environment; keep cross-device diagnostic evidence separately
identified.

Measure CUDA events around the complete resident operator, including required
conversions, materialization, partial reductions, merges, and dispatch. Exclude
allocation, transfers, and reference work. Use ten warmups, then seven raw
samples averaging 32 calls each. Run five randomized exploration rounds and
five fresh paired confirmation rounds on the same canonical GPU. Do not pool
samples across UUIDs or use profiler replay time as throughput.

Compare with equal case weights using weighted geometric improvement and
95% round-bootstrap intervals with 5,000 resamples. Require at least 2%
supported improvement and no per-case regression greater than 5% for promotion.
Compare candidates within their precision track; report mixed-precision results
as an accuracy/performance tradeoff separate from strict-track improvements.

## Acceptance and delivery

Correctness gates precede timing. OOM, unsupported cases, and numerical failures
remain failures; do not shrink or omit required workloads. Run memcheck on
finalists over representative cases and tails, and racecheck/synccheck on
custom-kernel finalists. An independent verifier checks oracle semantics,
candidate identities, raw statistics, precision-track separation, profile
provenance, and resource release. The root agent owns GPU scheduling and final
acceptance.

The study succeeds by completing an inspectable evidence-driven loop with
several distinct alternatives and a profiler-informed revision. A confirmed
improvement or a well-supported explanation for rejecting the alternatives is
a valid outcome. Deliver a concise report, versioned candidate history, raw
measurements, error summaries, profiler analyses, and a portable archive with
relative content manifests and verified hashes. Commit and push the KDA and
CUDA-policy changes separately. Do not imply a further follow-up branch merge.

Newer-GPU qualification, profiler-binding coexistence, shared artifact
hosting, sparse or prefill attention, and a dedicated fused Tensor Core
attention implementation remain separate follow-ups.
