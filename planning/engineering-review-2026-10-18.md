# Comprehensive KDA engineering review

**Source:** User-provided review, saved October 18, 2026. The assessment below is
preserved as supplied, with Markdown formatting for headings and tables. Saving
this review does not independently reverify its claims.

**Merge status:** The original hold was superseded by the user's subsequent
explicit authorization to merge onto `main` first and implement the agreed
attention-study plan. The assessment below remains the original read-only review;
the later implementation authorization is separate from its findings.

---

Read-only assessment · October 18, 2026 · KDA, KernelWiki, and ncu-report-skill

## 1. Verified project state

All three components are present in the review. The current records show a substantially more complete system than NVIDIA’s original prompt-led KDA prototype.

| Component | Current state | Evidence |
|---|---|---|
| KDA | Executable experiment engine implemented; real SM70 qualification completed | 63 CPU regressions and bounded V100 hardware run |
| KernelWiki | All 10 Volta bootstrap tasks completed | Six representative kernel families, source-backed knowledge, archived experiment evidence |
| ncu-report-skill | Volta-compatible code and guidance present | V100 report parsing and source-line attribution demonstrated |
| Integration | Both dependency forks pinned in KDA | Exact Git submodule commits, documented consumer checks |

KDA currently pins:

* KernelWiki: 244283cb8b57d1695af61aaa5e0cf5a04edfe9c9
* ncu-report-skill: bbb60a67fcb44c65510386c7dd41bc327fb91d25

These are specified in KDA’s README.md and docs/experiment-engine.md.

The most important verified result so far is the real-device qualification. KDA compiled three SM70 reduction candidates, rejected the deliberately incorrect one before timing, compared the two correct candidates using repeated CUDA-event measurements, and retained the winning implementation according to its declared promotion criteria.

The recorded aggregate advantage of the warp-shuffle implementation was approximately 1.074×, specific to the six tested workload cases. The result does not claim to establish a generally superior reduction algorithm.

The same test exposed a real cancellation defect: the production CLI failed to install existing signal handlers, allowing the admitted launcher to continue after its parent exited. The implementing team corrected the wiring, retained the failed attempt as evidence, and repeated qualification. The corrected engine passed its SIGTERM cleanup and fresh-resume checks.

That is stronger evidence than a suite consisting entirely of mocked GPU runs.

The final qualification also processed an actual Nsight Compute 2025.2.1 report, with 1,207 recorded metrics and all 22 sampled PCs mapped to source. Its unsupported Volta PM-timeline capability was reported as unavailable rather than fabricated.

These claims are documented in kda/planning/device-qualification.md. The raw qualification archive is retained locally; this review has not independently rerun the device experiment.

## 2. Architecture and integration assessment

The architecture is coherent, and the decision to keep the optimization engine separate from KernelWiki and ncu-report-skill was correct.

### KDA agent workflow

Research · candidate design · implementation · diagnosis · next experiment

### KernelWiki

Architecture-aware source and optimization knowledge

### ncu-report-skill

Profiler collection, metrics, stalls and diagnosis

### kda_experiments

Immutable candidates → build → correctness → paired benchmarks → confirmation → evidence-backed selection

The engine is implemented in a distinct kda_experiments/ package. Its integration into KDA’s original workflow is limited to a few documentation and prompt changes. It does not import or duplicate either skill’s internals.

This is a strong maintainability decision. KernelWiki’s architecture catalog, the profiler’s version-specific capabilities, and the candidate-evaluation engine can evolve independently.

### What the engine genuinely implements

| Capability | Assessment |
|---|---|
| Candidate registration and ancestry | Implemented |
| Immutable source snapshots and build identities | Implemented |
| Independent, task-defined correctness validation | Implemented |
| Multiple required workload cases | Implemented |
| Serialized GPU evaluations | Implemented |
| Candidate-order randomization | Implemented |
| Weighted geometric performance comparison | Implemented |
| Fresh paired confirmation | Implemented |
| Confidence and per-case regression gates | Implemented |
| Crash, cancellation and resume handling | Implemented and hardware-tested in a bounded case |
| Profiling, SASS and ablation attachments | Implemented as evidence attachments |
| Automatic kernel generation | Agent responsibility, not engine functionality |
| Automatic profiler-directed candidate generation | Not implemented as a separate engine |
| Automatic ablation and SASS-based optimization | Not implemented as standalone search machinery |

The code supports the implemented rows, rather than merely describing them. In particular, contracts.py rejects missing workload cases, invalid numerical results and unsupported compiler targets. selection.py calculates the candidate benefits and bootstrap confidence intervals. engine.py binds results to source, binary, toolchain and environment identities before permitting promotion.

I also inspected store.py and runner.py. They implement append-only experiment records, atomic preferred-candidate updates, process-group cleanup and immutable candidate identifiers.

I found no architectural reason to replace this engine with CUDA Kernel Optimizer.

KDA has incorporated the most useful transferable evaluation mechanisms while avoiding that project’s task-specific ABI and unsafe assumptions about changing workloads or numerical precision.

## 3. KernelWiki port review

### First-class SM70 coverage established

KernelWiki is no longer simply a Blackwell knowledge base with some Volta notes.

The current fork has first-class SM70 architecture registration, exact V100 aliases, architecture-aware retrieval, source provenance, executable kernel bundles, and native benchmark evidence.

The six representative kernel families are all retrievable through the V100 route. The original Hopper and Blackwell routes remain accessible, including source-following and code-artifact retrieval.

The archived evidence checker validates nine historical cases across the representative families. Its supporting tests include relocated evidence verification and deliberate corruption of source, binary and receipt identities.

### What the kernel results teach

| Family | Substantive finding | Remaining performance opportunity |
|---|---|---|
| GEMM | cuBLAS dominates the tested dense/small-M custom PTX implementations; CUTLASS wins one ragged comparison | Better native fragment pipelines and fused consumers |
| Softmax / RMSNorm | CTA-row reductions and aligned vector operations beat initial baselines | Shape crossovers, fusion and complete-operator tuning |
| Attention | 16-way split-KV cuts tested decode latency from 148.48 to 66.56 µs | Tensor Core attention, GQA packing, broader split policy |
| Grouped/gated | Paired SIMT wins balanced groups, but split cuBLAS wins a weighted-skewed case | Distribution-sensitive dispatch and better grouped matrix engines |
| W4A16 | Predecode + cuBLAS substantially beats the tested direct SIMT decoder | Fused decoding that feeds native matrix hardware |
| Recurrent state | Retaining state cuts long-prefill latency from 6,993.6 to 398.0 µs | Better state ownership, justified chunking, decode tuning |

Two findings deserve particular attention.

First, the 17.57× recurrent-state improvement is real for its measured end-to-end kernel-launch sequence, but it combines fewer launches with altered state ownership. It does not isolate a 17.57× improvement in arithmetic execution.

Second, the W4A16 result is a useful negative experiment. The direct decoding path is much slower than predecode plus cuBLAS for the tested weights and shapes. That does not establish that fused low-bit decoding is intrinsically inferior. It establishes that this particular SIMT implementation does not recover enough efficiency to beat the established matrix path.

Those are exactly the distinctions a trustworthy optimization knowledge base should preserve.

### KernelWiki’s remaining limitation

It has a credible initial Volta corpus, not a mature library of extensively optimized V100 kernels.

Most performance comparisons cover selected shapes on one V100 SXM2 16 GB, with narrow numerical contracts and limited profiling repetitions.

This is appropriate for the original bootstrap. The entries are useful because they preserve baselines, rejected candidates, tested boundaries and evidence. They do not need further infrastructure development before KDA can use them.

I would not reopen the completed KernelWiki epic simply because many of the kernels have optimization headroom.

## 4. ncu-report-skill port review

### Native V100 profiling demonstrated

The profiler port is substantially more than an architecture-specific reference document.

The shared report-processing code now handles older ncu_report capabilities, unavailable metrics, different report formats, and the absence of Volta PM-sampling timelines.

The native source-attribution fixture is particularly convincing:

| Evidence | Recorded result |
|---|---|
| GPU | Tesla V100-SXM2-16GB |
| Toolchain | CUDA 12.9.86, Nsight Compute 2025.2.1 |
| Correctness | 32,768 dependent-load chains passed |
| Sampled PCs | 44 |
| Source-mapped PCs | 44/44 |
| Exact-binary SASS matches | 44/44 |
| Long-scoreboard samples at target line | 16,288, matching NCU’s source export |

The profiler also parsed KDA’s later real-device qualification report.

The implementation appropriately distinguishes unsupported PM timelines from missing source counters. It does not turn absent metrics into zero measurements or use profiler replay time for performance comparisons.

### The main profiler improvement I’d consider

The current analyze_reports.py still uses a broad metric list spanning several GPU generations. It preserves unavailable values correctly, but that can make the summary sparse and obscure which counters matter for the selected device.

The Volta reference already contains an architecture-specific diagnostic map. A lightweight refinement could select the most relevant available metrics for the report’s architecture without changing the shared analysis engine.

There is also a multi-installation compatibility risk worth testing. ncu_utils.py first attempts normal Python import resolution before consulting the explicitly selected profiler’s Python bindings. On a host with multiple Nsight Compute installations, it is possible to select one profiler executable while importing bindings from another installation.

That is not a demonstrated failure in the V100 runs. It is a concrete portability test worth adding now that you have access to multiple GPU generations.

The separate ncu-report-skill Project Control Todo authority is currently unreadable (todo_read_database_open_failed). This is an operational visibility issue, not evidence that the code port failed.

## 5. Engineering findings requiring attention

I found no demonstrated critical defect in the current corrected engine. The strongest remaining concerns are concentrated in portability, operational guidance, and breadth of qualification.

| Priority | Finding | Recommended action |
|---|---|---|
| High | KDA’s getting-started instructions still clone the original upstream repository | Correct the instructions to distinguish installing your fork from installing upstream KDA, including SSH submodule requirements |
| High | The complete engine has only been hardware-qualified on one V100 workload | Run one bounded real optimization experiment on a newer GPU, exercising the same correctness, selection, profiler and recovery contracts |
| High | The agent-led research → diagnosis → improved kernel loop has not yet been demonstrated as a complete substantial optimization campaign | Exercise one real kernel with several meaningfully different candidates and an actual profiler-informed revision |
| Medium | ncu-report-skill supports multiple profiler generations but their coexistence is not qualified | Test reader-binding selection when old and new NCU installations coexist |
| Medium | Evidence archives are primarily local and some are large | Preserve portable manifests and establish a reliable artifact location if multiple machines or agents will reproduce results |
| Low | Documentation contains small stale assumptions, including the original empty Todo-authority statement | Correct when touching those files; no documentation overhaul needed |

### Why I prioritize the full optimization experiment

KDA has demonstrated that its evaluator can select correctly among supplied candidates.

What has not yet been demonstrated to the same standard is that an agent using the complete system can consistently make intelligent improvements to a difficult kernel.

That is a different capability.

For instance, a suitable evaluation would begin with one of the Volta attention kernels, use KernelWiki for architectural guidance and ncu-report-skill for diagnosis, generate a handful of genuinely different implementations, and use kda_experiments to validate and compare them.

The result need not beat cuBLAS or a highly optimized upstream implementation. It should demonstrate that the agent’s decisions follow evidence and that the process can produce a meaningful improvement—or a well-supported explanation of why its alternatives failed.

This would test the actual purpose of KDA without creating another framework.

## 6. Assessment against the original goals

| Original objective | Review verdict |
|---|---|
| Make Volta first-class | Achieved for the initial architecture and kernel-knowledge scope |
| Preserve existing Hopper/Blackwell support | Retrieval preserved; full hardware regression not newly demonstrated |
| Integrate KernelWiki and ncu-report-skill | Achieved through pinned dependencies and consumer checks |
| Incorporate valuable CUDA Kernel Optimizer machinery | Achieved selectively |
| Implement a repeatable optimization feedback loop | Evaluation loop implemented; real-device qualification passed |
| Preserve correctness and avoid benchmark exploitation | Strong contracts and tests; cannot guarantee arbitrary task validators are sound |
| Make optimization evidence reproducible | Strong artifact identities; portable raw archive delivery can improve |
| Remain useful on future GPUs | Architecturally credible, not yet hardware-proven across generations |
| Avoid unnecessary duplicated frameworks | Achieved |
| Support a future creativity/design skill | Suitable foundation; that skill is correctly out of scope |

A critical distinction in the correctness assessment is that KDA does not—and should not—attempt to invent universal numerical tolerances. It delegates the mathematical oracle to the task and verifies that the declared validation was performed against the required cases.

That is an appropriate boundary. It means the reliability of future experiments still depends on strong task contracts and independent references.

## 7. Final assessment

### Ready for real kernel engineering work

Qualified on V100; newer GPU support and extended optimization quality need additional demonstrations.

I would not commission another large implementation epic.

The KDA fork now has the core machinery we wanted: a coherent agent workflow, an executable and conservative candidate evaluator, versioned evidence, working Volta knowledge, native profiling, and demonstrated controller-backed GPU execution.

More importantly, it has kept those responsibilities separate. Nothing I inspected suggests that KDA needs to absorb KernelWiki, replace the profiling skill, or maintain a second optimization framework.

There are two meaningful next questions.

Can it run the same workflow reliably on newer hardware? Its target selection and evaluation contracts are designed to permit this, but that is not the same as empirical qualification.

Can an agent use the system to discover substantially better implementations of a difficult kernel? The candidate evaluator is ready for this test. The quality of the agent’s research, hypotheses, implementation choices, and profiler interpretation is not yet established by the bounded reduction demonstration.

Those are the next tests I would prioritize, alongside the small installation-documentation correction and multi-version profiler compatibility check.

### Review limitations

This was a read-only source and evidence review. I inspected the principal implementation modules, test structure, architecture integration, source-backed performance reports, and existing hardware-qualification records. I did not execute new tests, reprofile the GPU, replay the full archived experiments, or independently verify every file in the approximately 193 MB local qualification archive.

The review therefore supports a strong judgment about architecture and implemented mechanisms, with the recorded native evidence supporting bounded functionality. It does not certify the absence of undiscovered defects or generalized optimization performance.

Overall: KDA is ready to move from development into serious use and measured improvement. The infrastructure does not need substantial further construction before that begins.
