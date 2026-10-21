# KernelBender consumer integration receipt

- Consumer: KDA optional, explicit experimental design route.
- Pinned component: `skills/KernelBender` at `2e19a747a3be2abfb12243db809a3e85ae8b5d42`.
- Skill entry: `skills/KernelBender/skills/kernelbender/SKILL.md`.
- Consumer surfaces: `README.md`, `docs/agent-flow.md`, and `prompts/basic-flow.md`.
- Test: `tests/test_kernelbender_consumer.py` extracts all three skill routes from the basic prompt and checks each initialized entry's frontmatter. It skips when the corresponding optional submodule is uninitialized.
- Evidence boundary: this integration adds an optional design route; it does not establish an incremental performance benefit. KDA's existing correctness and evaluation workflow remains authoritative.
- License: no license file selected in the pinned component.
- Initial validation at `bcbba51e0ba3ebeac10f5bfda68832ccdcfc43cf`: focused consumer test passed; the then-current unittest suite passed all 64 tests in 242.624 seconds.

The conventional/library route remains available. The original consumer test
was a path/frontmatter check; the [2026-10-21 closeout](integration-closeout-2026-10-21.md)
adds fresh-agent skill use, paired-contract validation, and current regression
results. Explicit invocation does not establish automatic host discovery or
incremental skill effectiveness. No host-global skill installation was made,
and KDA's engine/evaluator remains unchanged.
