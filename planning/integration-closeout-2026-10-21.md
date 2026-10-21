# KDA integration closeout — 2026-10-21

This is an integration and offline evidence check, not a new GPU campaign.
NVIDIA KDA `acdd793` was merged without conflicts as `1937f50`; the original
branches and unpublished work were preserved. Upstream's Hugging Face exporter
is included. The optional experiment engine and its public interfaces remain
unchanged. Project Control returned `no_work` for this request; work proceeded
under the user's explicit integration authorization, without changing Todo state.

## Components and qualification

The README and third-party notices identify the exact consumed gitlinks.
KernelBender's accepted consolidation (`2e19a74`, runtime implementation
`96b3ee5`) and KernelWiki's consolidation (`68c017a`) supply the paired design
and hardware knowledge. The final Wiki pin is
`542ed702ac662422d55b19186562b29abbb5da29`, including the safety correction.
ncu-report-skill remains at `bbb60a6`: the newer available `685fed8` changes only
Todo configuration, with identical skill, helpers, and tests.

KernelBender remains an explicit experimental design aid, KernelWiki owns
architecture contracts, ncu-report-skill owns report interpretation, and KDA
owns independent correctness and promotion. No skill responsibilities or
scheduler behavior were duplicated. KernelWiki/ncu MIT license copies match
their component files; KernelBender has no selected repository license. The
consolidation provenance retains access-gated Atlas locators and local source
identities without importing the Atlas archive or prose.

KernelWiki's current attention pages and artifact guidance now disqualify the
original materialized implementation and withdraw comparisons using its timing.
Unsafe materialized timings are removed from current performance metadata;
historical sources, raw records, and frozen artifact bytes remain intact.
`materialized-corrected` is a separate downstream control, not a repair of those
historical results. Archive-integrity checks do not certify race freedom.

## Existing optimization evidence

The independent audit in
`runs/integration-closeout-20261021/audit/audit-receipt.md` accounts for all
720 benchmark records across five saved comparisons, binding raw samples to
requests, cases, fixtures, source snapshots, builds, binaries, and native results.
It reproduces the accepted `gqa-parallel-merge` promotion over `split16`:
1.4295805392x, 95% paired interval [1.4290759133, 1.4301499678]. The later
corrected-baseline control retains the same winner. The archive, source bundle,
and selected profile/binary/source identities match their receipts.

Recorded memcheck, racecheck, and synccheck pass for `split16`, the winner,
and `materialized-corrected` over 24 inputs. Original `materialized` has
24 race hazards (4 errors, 20 warnings); `mixed-materialized` has 24 race errors
and application-level numerical failures. Their timing comparisons remain
disqualified. No stored selection receipt or preferred pointer was rewritten.

One historical audit script assumes that a rejected attempt's incumbent is
still the current preferred candidate. That assertion fails after a later valid
promotion. The audit records the original failure and a read-only, history-aware
check of the later pointer; all earlier sample/identity assertions pass. This
is a limitation of that task-local auditor, not an experiment-engine defect.

The study consumed 37.84 admitted GPU minutes under its 60-minute budget.
These offline checks do not rerun kernels, sanitizers, controller admission or
release, and do not add new performance evidence. Qualification remains scoped
to the captured V100/SM70 toolchain and six decode workloads. Newer GPUs,
profiler binding coexistence, and causal skill effectiveness remain unqualified.

## Skill consumption and regressions

A fresh Luna agent explicitly read and used all three pinned skill entries.
KernelBender produced a retrospective merge-design brief; exact SM70 Wiki
queries and source-following distinguished experimental implementation evidence
from source-reported hardware contracts. ncu-report-skill's real metrics, stall,
and timeline helpers re-read the hash-bound winner report with explicit
2025.2.1 bindings. All ten recorded commands succeeded, 19/19 sampled PCs
matched the binary, and the unavailable Volta PM timeline remained unavailable.
The winner's ten long-scoreboard samples are distinct from the parent's 169;
replay diagnostics are not throughput evidence.

The outputs, exact commands, entry hashes, report/binary identities, and limits
are in `runs/integration-closeout-20261021/skill-use/receipt.md`, `receipt.json`,
`invocations.jsonl`, `design-brief.md`, and `kernelbender-use.md`. The receipt
hash is `2f2535623d8f644672a19b8093b1b4d49e6e2b43a1a07d12c7eafb259e741e7f`.
The skill entries are unchanged by the subsequent Wiki safety documentation
commit. This establishes explicit path consumption, not automatic discovery,
host registration, a new optimization discovery, or incremental skill benefit.

Tests ran in an isolated `/tmp/kda-integration-test-env` with pytest, PyYAML,
and NumPy; no project dependency or user environment was changed:

| Check | Result | Log under `runs/integration-closeout-20261021/` |
| --- | --- | --- |
| Complete KDA suite, including upstream export tests | 98 passed, 1 skipped, 29 subtests passed | `tests/kda-pytest.log` |
| KernelBender component suite | 34 passed | `tests/kernelbender-final.log` |
| ncu-report-skill offline compatibility | 10 passed | `tests/ncu-report.log` |
| KernelWiki full suite | 274 passed | Subagent tool transcript, execution session `52276` |
| Wiki corpus validation | 1,095 pages, 44 asset bundles, 14 ledgers valid | `tests/wiki-validation.log` |
| Paired hardware contracts | 17 passed | `tests/knowledge-pair.json` |
| Archived Volta evidence | 9 cases valid | `tests/wiki-archived-evidence.json` |
| Final explicit-entry consumer checks | 3 passed | `tests/final-consumer.log` |

The Wiki full-suite run completed before the final prose-only cleanup; final
validation and the source-following query were checked afterward. Its raw test
output is retained in the subagent tool transcript rather than a separate log.
The fresh skill exercise captured Wiki entry revision `68c017a` and exact page
output bytes during the correction; final safety retrieval is separately saved
in `tests/final-attention-page.txt` at the final committed Wiki revision.

The optional real `kernel-builder` export round trip was skipped because the
executable is absent. The initial KernelBender run had four missing-NumPy
environment errors; its log is retained, and the complete suite passed after
installing NumPy only in the isolated environment. No remaining engine defect
was demonstrated. The documented full-suite command now uses pytest so the
upstream function-based export tests are executed rather than silently omitted.

Independent integration review caught and removed one remaining unqualified
online-versus-materialized comparison before committing the Wiki correction.
All frozen `benchmark_runs/` paths and the active CUDA runner's source digest
were preserved; only current guidance, qualification metadata, and the changed
README's provenance digest were updated.

## Initial local delivery

All new raw logs and agent outputs are under ignored
`runs/integration-closeout-20261021/`; the original evidence is preserved.
Component corrections were committed before KDA's final gitlink update. At
this initial delivery, component commits were available locally and not yet
fetchable from their GitHub URLs. No push or local-main merge was performed
until the subsequent publication authorization below. No host-global skill
installation, service restart, or GPU campaign was performed.

Verified incremental component bundles and their SHA-256/size manifest are in
`runs/integration-closeout-20261021/components/`. The KernelBender bundle
requires base `bcbba51e0ba3ebeac10f5bfda68832ccdcfc43cf`; the Wiki bundle
requires `244283cb8b57d1695af61aaa5e0cf5a04edfe9c9`. Both bases already exist
in the local submodule histories. These are local recovery artifacts, not
publication or full standalone source archives.

## Publication follow-up

The user subsequently authorized component-first publication and merging the
completed branches onto `main`. KernelBender `main` now publishes `2e19a74`;
KernelWiki `main` and its preserved legacy `master` publish `542ed70`. The
completed Wiki safety branch is also published. Component pushes preceded KDA
publication, and independent fresh remote clones check that all three exact
KDA submodule pins can be fetched. The older ncu-report-skill pin remains
intentional; its latest main differs only in Todo configuration.

KDA's completed feature, integration, and backup branch histories are contained
in `main`, including the fetched NVIDIA `upstream/main`. Merges were fast-forward
updates with no history rewriting or branch deletion. The clean standalone
KernelBender and KernelWiki checkouts were synchronized to their published
`main` branches. The validated implementation and submodule pins are unchanged
by this publication follow-up; existing regression results still apply.

Publication checks, remote-ref identities, and fresh-fetch verification are
retained under ignored `runs/publication-20261021/`. The initial local-only
availability limitation above is superseded by this publication.
