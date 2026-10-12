# Embedded QA project guidance

Single source of truth for AI coding agents (Copilot, Codex, Cursor, Antigravity).

## Workflow

- For hardware QA work, follow the orchestrator workflow: route requirement analysis, test design, implementation, interactive execution, and evidence handling to the focused skills in [`.agents/skills/`](./.agents/skills/).
  - `requirements-to-test-cases`: requirements to traceable test cases.
  - `pytest-hardware-test-design`: parameterization, isolation, fixtures.
  - `allure-test-reporting`: `allure.step`, self-explanatory tests, evidence.
  - `interactive-hardware-tests`: button/LED/operator checks.
  - `uart-debug-evidence`: per-test UART transcripts in debug mode.
  - `hardware-qa-code-validation`: independent validation before completion.
- Orchestrator agent: `.github/agents/embedded-hw-qa-orchestrator.agent.md` (Copilot). Other tools: follow the skills in the order above.
- Before reporting completion, have an independent validator (`hw-qa-code-validator`, or a fresh read-only review following `hardware-qa-code-validation`) check changed test code and evidence. The validator must not modify files or claim a test passed unless it ran and observed the result.

## Rules

- Keep expected behavior traceable to a requirement or an explicitly recorded known defect. Do not mark behavior as passed without the required UART or physical evidence.
- Never put Wi-Fi passwords, tokens, or other credentials into source, test output, reports, or saved UART logs.
- Treat hardware tests as stateful operations: identify the target and firmware first, keep tests isolated, and disclose reboot, persistent-state, or physical-interaction effects before running them.
- Never run hardware or interactive tests without an explicit request to execute them.
- Use debug UART capture when requested or needed to diagnose a failure; retain the per-test transcripts and summarize the evidence without replacing it with assumptions.

