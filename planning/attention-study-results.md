# Profiler-informed V100 attention study

Completed on 2026-10-18. The qualified engine was merged and pushed to `main`
at `669b3a1` before this work. Follow-up delivery is on
`codex/attention-decode-study`; no second merge is implied.

## Qualified result

The strict FP32 `gqa-parallel-merge` candidate was promoted over the strongest
existing valid baseline, `split16`: **1.42958×** weighted geometric improvement,
95% paired-round bootstrap interval **[1.42908, 1.43015]**. Every case improved;
every per-case lower bound exceeded 1.1177×. This is evidence for the six frozen
workloads, not a general attention algorithm or cross-device speedup claim.

The task uses represented FP16 Q/K/V, eight query heads and two KV heads,
FP32 accumulation/normalization/probabilities/output, and an independent FP64
oracle over the exact represented inputs. Eighteen seeded inputs and six guards
cover tails, cancellation, independent GQA normalization, single-key and
high-contrast scores. The six performance cases have equal weight. Each batch
uses five randomized exploration rounds and five fresh paired confirmation
rounds, ten warmups, and seven samples averaging 32 complete resident operators.
Promotion requires 2% supported improvement and at most 5% per-case regression.

The final control's medians of five exploration-round medians, in microseconds:

| D | L | Corrected cuBLAS baseline | Split-16 baseline | New strict winner |
|---:|---:|---:|---:|---:|
| 64 | 512 | 132.000 | 21.024 | 13.120 |
| 64 | 4096 | 138.880 | 60.096 | 53.760 |
| 70 | 512 | 136.480 | 23.968 | 13.408 |
| 70 | 4096 | 139.584 | 63.296 | 56.288 |
| 128 | 512 | 136.448 | 30.432 | 14.400 |
| 128 | 4096 | 134.880 | 70.976 | 63.360 |

All 720 recorded timing records across five successful comparisons were independently audited.
The primary [promotion run](../runs/attention-decode-study/workspace/engine-strict/runs/kda-experiments/attempts/d0de801b-8535-439d-8398-25c0e3cb95c8/summary.json)
compared the revision, its parent and split-16. The final
[corrected-baseline control](../runs/attention-decode-study/workspace/evidence/corrected-baseline-comparison.json)
repeated the comparison with a sanitizer-clean materialized baseline and retained
the winner. The independent verifier reproduced raw-sample identities, weighted
scores, bootstrap intervals, regression gates and promotion evidence; see the
[primary audit](../runs/attention-decode-study/evidence/independent-review/strict-merge-attempt-audit.md).

## Evidence-driven design

Exactly four new optimization versions were explored: warp ownership, shared
GQA K/V staging, mixed materialization, and the profiler-informed merge revision.
The first two strict alternatives were slower than split-16. The revision keeps
the GQA parent's partial kernel byte-identical, including 32 splits and 16-key
tiles. It replaces only the merge: parallel stable split weights and normalizer,
then coalesced feature accumulation by 128 threads. Its contemporaneous
exploration point advantage over its parent was 1.684×; the combined merge
replacement is attributed, not its individual instruction changes.

Five complete-operator NCU captures used CUDA 12.9.86, Nsight Compute 2025.2.1
and its matching reader. Four diagnostic captures used the four distinct V100
UUIDs; the winning capture used the canonical timing UUID. The parent merge had
8 blocks of 32 threads, 53 registers/thread, 0.08058 eligible warps/scheduler,
9.183 long-scoreboard cycles/issue, and only 0.3095% peak DRAM throughput.
All 51 sampled PCs matched source and exact-binary SASS; 169 long-scoreboard
samples mapped to the partial-vector accumulation. This supported addressing
the dependent merge rather than treating it as bandwidth saturation.

The new merge records 34 registers/thread and 19/19 mapped/matching PCs. Its
recorded replay duration is 8.000 us versus the parent's 49.824 us on another
UUID. Those are diagnostic observations, not a quantified throughput gain;
acceptance uses the unprofiled canonical-device measurements. PM timelines are
unsupported on Volta. Raw API duration labels are dimensional `s` while the
numeric values agree with nanoseconds; the consumer verifies explicit CSV
microsecond units and preserves both original fields. See the
[diagnosis](../runs/attention-decode-study/workspace/docs/profile-diagnosis.md),
[attribution](../runs/attention-decode-study/workspace/evidence/merge-attribution.json),
and [winning profile](../runs/attention-decode-study/workspace/profiles/gqa-parallel-merge/profile-manifest.json).

## Correctness findings and qualification

The winner, split-16 and corrected materialized control each passed memcheck,
racecheck and synccheck over all 24 inputs, with zero tool errors/hazards and
passing independent numerical checks. Failed alternatives remain preserved:

- `mixed-materialized` passed normal seeded validation but racecheck exposed
  24 errors and numerical failures. Synccheck reported zero tool errors while
  the application itself failed numerical checks. Its entire timing matrix is
  disqualified from optimization claims, including its apparent single-case
  advantage. It was never promoted. See the
  [independent raw-log audit](../runs/attention-decode-study/evidence/independent-review/mixed-attempt-audit.md).
- The original materialized baseline has the same shared-maximum read versus
  scratch-reuse race. A focused control reproduced 24 hazards (4 errors,
  20 warnings). A separate `materialized-corrected` snapshot adds one CTA
  barrier and passed all three tools. This is a baseline correctness repair,
  not a fifth optimization strategy. The initial comparison with the unsafe
  baseline remains historical evidence, not a qualified speedup claim. See
  [control logs](../runs/attention-decode-study/workspace/sanitizers/baseline-audit/manifest.json).
- The pinned KernelWiki materialized source contains the same scratch-reuse
  pattern. The finding is recorded for its independent maintainer; neither
  submodule source nor gitlink was changed. The corrected downstream source is
  [available here](../runs/attention-decode-study/workspace/candidate-sources/materialized-corrected/).

The first fanout used the wrong UUID field; the first benchmark adapter assumed
an absent request field; and three mixed-contract cases omitted `query_length`.
All failed attempts were retained. Corrections preceded accepted measurements;
old contract bytes were recovered from signed-off task history. Eleven focused
CPU checks now cover the task driver and both contracts' frozen fixture coverage.
The original engine's 63 regressions passed before the main merge.

## Execution policy and delivery

CUDA per-device NCU coordination is delivered separately at installed/source
commit `b70d76b` (`skills_dev` cherry-pick `bfa9238`) on
`codex/cuda-profiler-device-lock`. Seventeen focused regressions passed. Native
counter collections overlapped for 0.6831576824 seconds on distinct UUIDs;
a competing same-UUID admission was rejected. Benchmark/sanitizer host isolation
and controller reservations remain authoritative. See the
[policy qualification](../runs/attention-decode-study/evidence/cuda-policy/native-qualification.json).

The study consumed **2270.288 summed admitted GPU-seconds (37.838 minutes)**
including policy qualification, failed attempts, quiescence and cleanup, below
the 60-minute limit. All reservations released; the final compute-process query
was empty. Task code, contracts, fixtures and source history live in the ignored,
independently versioned workspace, keeping task-specific code out of upstream
KDA's generic tree.

The [portable archive](../runs/attention-decode-study/delivery/attention-decode-study-20261018.tar.gz) contains
5,887 files (758,942,811 compressed bytes). Every relative content digest,
size and symlink identity passed sequential verification. The source bundle
preserves the complete signed-off task history at `4ba784f`. See the
[content manifest](../runs/attention-decode-study/delivery/CONTENT-MANIFEST.json),
[archive receipt](../runs/attention-decode-study/delivery/archive.json), and
[acceptance record](../runs/attention-decode-study/evidence/acceptance.json).

Archive SHA-256: `62b11ea83172827bae4cee0b67b56a16c906e3265197d1716a740ea260201e61`.

Raw artifacts remain local; shared artifact hosting is a separate follow-up. KernelWiki remains pinned
to `244283cb8b57d1695af61aaa5e0cf5a04edfe9c9` and ncu-report-skill to
`bbb60a67fcb44c65510386c7dd41bc327fb91d25`. Newer-GPU qualification and profiler
binding coexistence remain separate work.
