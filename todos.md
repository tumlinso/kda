

<!-- todo-orchestrator:v2-managed:start -->
# Todo Orchestrator v2 Projection

Project revision: `24`

## Workstreams
- `KDA-ATTENTION-STUDY` | kind: task | status: done | parent: - | objective: After merging the qualified engine, coordinate per-device CUDA profiling maintenance and complete a bounded strict/mixed-precision attention optimization study with independent references, explicit dispatch, evidence-driven revision, conservative engine selection and archived evidence.
- `KDA-EXPERIMENT-ENGINE` | kind: task | status: done | parent: - | objective: Deliver the approved portable experiment engine with strict correctness gates, reproducible benchmarking, persistent evidence and CPU-only validation. Defer all GPU execution and dependency qualification until the user announces readiness. Do not touch skill submodules or gitlinks.
- `KDA-SKILLS-SYNC` | kind: task | status: done | parent: - | objective: Fetch the published fork heads, retain exact compatible skill gitlinks, verify CPU-only consumer interfaces and correct stale dependency documentation. Do not edit dependency source or run GPU work.
- `KDA-SM70-DEVICE-QUALIFICATION` | kind: task | status: done | parent: - | objective: Complete a bounded native SM70 qualification of the shipped KDA engine: independent numerical correctness and negative control, real repeated CUDA-event timing, evidence-based selection, controller receipts and release, sanitizer checks, interrupted-run resume, and one profiling/diagnosis path through completed skills. Preserve task-owned kernels and raw evidence outside tracked KDA source.
- `KDA-KB-INTEGRATE` | kind: integration | status: done | parent: - | objective: Consume the versioned KernelBender handoff, pin the optional skill and add a small invocation route to the existing KDA workflow.
<!-- todo-orchestrator:v2-managed:end -->
