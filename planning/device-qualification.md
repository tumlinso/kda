# V100 device qualification

The user authorized native device qualification after both dependency ports
completed. This qualifies the implemented experiment workflow on one real SM70
device, not every GPU generation or kernel in the independent knowledge corpus.

## Question and boundaries

Can KDA build independent native candidates, reject an incorrect implementation,
validate against an independent reference, compare actual event measurements,
preserve/promote only supported results, resume interrupted work, and consume
architecture and profiler evidence through its existing dependency interfaces?

Keep task-specific CUDA sources, references, drivers, configuration, builds and
raw results in a separate workspace at `/tmp/kda-sm70-qualification-20261018`.
Archive it under ignored `runs/` before completion. No skill submodule changes.
All CUDA execution, sanitizer use, and profiling require the installed CUDA
controller's admission. CPU compilation precedes admission. Site paths and
resource identity belong only to task configuration and archived evidence.

Budget: one selected V100; two valid FP32 reduction strategies and one wrong
negative control; six representative workload cases plus held-out validation
inputs; repeated exploration and independent confirmation; a bounded sanitizer
check and one targeted NCU report. Validate interruption/resume once. Individual
commands have deadlines, and total admitted execution is limited to 30 minutes.
Do not run a broad optimization campaign or automatically add ablation/SASS work.

## Acceptance

- Native `sm_70` compilation using a verified compatible toolkit; executable,
  trusted harness/reference, toolchain, workload, skills and engine identities.
- Actual runtime identity agrees with the selected GPU and target. Controller
  lease, quiescence, serialized execution and post-run acceptance are recorded.
- Independent higher-precision reference with an authored FP32 numerical
  contract, odd/tail lengths, cancellation and dynamic-range inputs, and seed
  coverage. The wrong implementation fails and never reaches timing.
- Valid candidates pass correctness and representative memory/race/sync checks.
- Real CUDA-event samples exclude setup/transfers, have warmup/repetition,
  synchronization and error checks, and drive selection/retention correctly.
- A real interrupted admitted batch cannot publish a successful/promoted result;
  resumption uses fresh attempts and valid reusable builds, with no leaked GPU
  work or reservations after completion.
- KernelWiki evidence informs the implementation; one real NCU 2025.2 report is
  analyzed by ncu-report-skill. Unavailable Volta dimensions stay unavailable,
  and replay time is never substituted for unprofiled kernel performance.
- An independent verifier checks sources and archived results. Fix concrete
  framework integration defects with focused regressions, run required CPU
  regressions, document the exact qualification scope, commit and push changes.

## Initial environment inspection

Live controller inspection found four idle Tesla V100-SXM2-16GB devices (SM70)
with driver 580.178.04. CUDA 12.9.86 supports `sm_70`; Nsight Compute is
2025.2.1. The installed CUDA controller uses a retained compatibility bootstrap
into the current bundled Project Control runtime; plain system Python cannot
import that bootstrap. A task-local site entrypoint will select those verified
runtime inputs without weakening identity checks or changing the CUDA skill.
Actual selected UUID, installed paths, versions and receipts remain archived
task configuration. Recheck availability under admission before executing.

The initial admitted site check succeeded and released its reservation. Its
three idle observations took 22.25 seconds, exceeding the controller's default
10-second window. The KDA launcher therefore gained an optional, validated
site-configured quiescence policy; this task requests a 60-second window and
retains three required idle observations. The engine contains no host-specific
defaults. All 61 CPU regressions pass with that integration.

## Defect found by the device cancellation check

The first native comparison completed successfully, but a subsequent real
SIGTERM test exposed missing CLI wiring: the runner's cleanup handlers existed
and had helper-level tests, yet the production CLI never installed them. The
parent exited while its admitted launcher continued running. That failed test
is retained as failed evidence. Root stopped that exact launcher, verified
released reservations through the supported host API, and observed an empty
GPU compute-process list before further admission.

Commit `4e67415` installs the existing handlers before both public CLI dispatch
and the internal worker. Two new CPU-only tests exercise the real entry points
with a descendant that ignores SIGTERM; they verify child termination,
controller cleanup, and absence of successful result or preference publication.
The expanded CPU suite passed 63 tests. Device qualification is repeated using
the corrected engine, rather than transferring the earlier result across its
changed engine fingerprint.

## Qualified result

The corrected engine passed the real-device cancellation check: SIGTERM after
validation and the first native timing response produced exit 143, no successful
summary or preference change, automatic descendant cleanup and released
admission. A fresh resumed attempt reused matching CPU builds, repeated every
correctness gate, and produced 120 fresh benchmark responses. The old engine's
attempt is explicitly rejected for reuse after the engine identity changed.

Two native reduction strategies pass six cases with three seeds each against
an independent higher-precision reference and an authored FP32 error contract.
The wrong negative control fails all cases and never reaches timing. Five
exploration and five fresh confirmation rounds use CUDA events around complete
resident two-kernel calls. The corrected-engine comparison retains warp-shuffle:
the shared-memory challenger scores 0.93107656 (95% round-bootstrap interval
0.92794714–0.93246784). The inverse aggregate improvement for warp-shuffle is
1.0740255× across these six cases; it is not a transferable architecture claim.
The earlier accepted comparison exercised actual promotion; the fresh engine
comparison correctly initializes/retains the incumbent in a distinct group.

Memory, race and synchronization checking each pass on both exact binaries for
the tiny odd and large odd streaming inputs. Raw results report zero errors and
zero race hazards/warnings; all four numerical checks per tool pass. The legacy
crash classifier remains partial/nonconclusive and its race label conflicts
with the raw zero-hazard result. That label is preserved, not treated as a
measured race. No dependency implementation was changed to accommodate it.

One admitted Nsight Compute 2025.2.1 full report on the winning first stage was
parsed by the pinned ncu-report-skill: 1207 metrics, 22/22 sampled PCs mapped to
source, and an explicit unsupported SM70 PM-timeline result. The profile is
attached to the corrected run's exact binary, case and environment, with a
diagnostic metric role excluded from selection. Its 91.0062% diagnostic DRAM
throughput and 509 long-scoreboard samples at the load/accumulation line support
a streaming-memory diagnosis for that stage only. The controller's generic
inventory separately names an unused default NCU executable with a failed
version probe; actual producer identity comes from the frozen selected adapter,
runtime probe and preserved collection-version transcript.

All nine admissions are released according to the supported host owner API;
final GPU compute-process inventory is empty. Total admitted time is
1742.697158 seconds, below the 1800-second limit. The original failed cancellation
attempt and its explicit cleanup evidence remain preserved alongside the
successful corrected test. Independent review recomputed statistics from raw
results and checked numerical/source contracts, sanitizer evidence, profile
attachment identities and release records.

This is bounded framework qualification on one V100, CUDA 12.9 and this workload
contract. Tensor Core kernels, other mathematical operations, GPUs and software
environments require their own evidence. No broad optimization campaign or
new architecture catalog was introduced. Task-owned kernels, reference code,
configuration and raw artifacts stay outside tracked generic KDA.

## Regression and evidence delivery

The final unchanged-source regression suite passed 63 tests in 126.400 seconds.
This includes the CPU end-to-end fixture and both production CLI cancellation
regressions. Both skill submodules remain clean at their validated pins. The
normal NVIDIA upstream relationship and merge base remain unchanged; no
unrelated upstream update was combined with this qualification.

The full task workspace is preserved locally in
`runs/sm70-qualification-20261018/evidence.tar.gz` (ignored by Git), with its
external `SHA256SUMS` and an internal per-file content manifest. It contains
`QUALIFICATION.md`, the independent review, task Git history, trusted contracts
and sources, candidate snapshots, binaries, raw requests/results, controller
receipts/artifacts, sanitizer logs, NCU report/analysis and final 63-test log.
The original `/tmp/kda-sm70-qualification-20261018` workspace is also retained.
These are local reproducibility artifacts, not uploaded by the source push.

Archive verification read every member sequentially and matched all 1752 file
hashes against the internal manifest. Archive size 193279681 bytes; SHA256:
`cfd7ed0abf795017aa3ed4c787497675b02e5ccdb515910850ed9fe36b5dd72f`.
