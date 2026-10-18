# KernelBender consumer integration receipt

- Consumer: KDA optional, explicit experimental design route.
- Pinned component: `skills/KernelBender` at `bcbba51e0ba3ebeac10f5bfda68832ccdcfc43cf`.
- Skill entry: `skills/KernelBender/skills/kernelbender/SKILL.md`.
- Consumer surfaces: `README.md`, `docs/agent-flow.md`, and `prompts/basic-flow.md`.
- Test: `tests/test_kernelbender_consumer.py` extracts the route from the basic prompt and checks the initialized entry's frontmatter. It skips when the optional submodule is uninitialized.
- Evidence boundary: this integration adds an optional design route; it does not establish an incremental performance benefit. KDA's existing correctness and evaluation workflow remains authoritative.
- License: no license file selected in the pinned component.
- Validation status: focused consumer test passed; `python3 -m unittest discover -s tests -v` passed all 64 tests in 242.624 seconds. Native completion also enforces the same required regression gate.

The original conventional/library route remains available; the prompt route resolves to the initialized optional skill entry and its frontmatter. This is a file/consumer check, not a new end-to-end model activation or effectiveness trial. No host-global skill installation was made. The KDA engine/evaluator and other submodule pins are unchanged.
