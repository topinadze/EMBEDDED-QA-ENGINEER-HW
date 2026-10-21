# Embedded QA project guidance

Project-wide defaults for AI coding agents (Copilot, Codex, Cursor, Antigravity); focused procedures live in the linked skills and file-specific instructions.

## Workflow

- For hardware QA work, follow the orchestrator workflow: route requirement analysis, test design, implementation, interactive execution, and evidence handling to the focused skills in [`.agents/skills/`](./.agents/skills/).
  - `requirements-to-test-cases`: requirements to traceable test cases.
  - `pytest-hardware-test-design`: parameterization, isolation, fixtures.
  - `allure-test-reporting`: `allure.step`, self-explanatory tests, evidence.
  - `interactive-hardware-tests`: button/LED/operator checks.
  - `uart-debug-evidence`: per-test UART transcripts in debug mode.
  - `hardware-qa-code-validation`: independent validation before completion.
- Orchestrator agent: `.github/agents/embedded-hw-qa-orchestrator.agent.md` (Copilot). Other tools: follow the skills in the order above.
- Before reporting completion, have the read-only `HW QA Code Validator` agent (or a fresh read-only review following `hardware-qa-code-validation`) check changed test code and evidence. The validator must not modify files or claim a test passed unless it ran and observed the result.

## Rules

- **Skill Invocation**: Always invoke the matching skill from `.agents/skills/` as the very first action before analyzing, designing, implementing, executing, or validating embedded QA tasks.
- **Interactive Test Protocol**: Follow `interactive-hardware-tests`; before each physical action, use `manual_prepare` to state the action, observation, duration, and readiness confirmation. Stop streams and verify termination before physical verification. Capture related multi-line UART events atomically or from a recorded buffer index.
- Keep expected behavior traceable to a requirement or an explicitly recorded known defect. Do not mark behavior as passed without the required UART or physical evidence.
- For UART-driven behavior, wait for and assert the expected response/event phrase. A timeout is only an upper bound, never evidence of success; if the phrase is missing, fail with captured UART. Use bounded quiet windows only when verifying that an event must not occur.
- Prefer yield fixtures for reusable device preconditions and cleanup; avoid test-body `try/finally` when a fixture can own the lifecycle. Make setup state and cleanup failures explicit.
- Each hardware test must establish and verify its required connectivity and authentication state over UART. Do not rely on prior tests or assumed reboot state; disclose persistent side effects and restore prior state only when safe.
- Never put Wi-Fi passwords, tokens, or other credentials into source, test output, reports, or saved UART logs.
- Treat hardware tests as stateful operations: identify the target and firmware first, keep tests isolated, and disclose reboot, persistent-state, or physical-interaction effects before running them.
- Never run hardware or interactive tests without an explicit request to execute them.
- Use debug UART capture when requested or needed to diagnose a failure; retain the per-test transcripts and summarize the evidence without replacing it with assumptions.
