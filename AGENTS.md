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

- **Skill Invocation**: Always invoke the matching skill from `.agents/skills/` as the very first action before analyzing, designing, implementing, executing, or validating embedded QA tasks.
- **Interactive Test Protocol**:
  - In all interactive tests (`@pytest.mark.interactive`), BEFORE performing any physical action or observation, inform the operator via preparation prompt (`manual_prepare`):
    1. **What to do**: exactly which button to press, which sensor/board to observe.
    2. **What to observe**: audible click, LED state/color/behavior, continuous stream numbers in console.
    3. **Time limit/duration**: clearly state how much time the operator has to observe or act (e.g. "Duration: ~5-10 seconds", "Measurement streams for 8 seconds").
    4. **Confirmation**: wait for explicit confirmation (`Press Enter when ready:`) before sending commands or expecting button presses.
  - For streaming or timed operations (such as continuous distance measurement, animations, auto-off timers): allow adequate time (e.g. 6-10 seconds) for physical observation, cleanly stop the stream/command (e.g. send Enter to stop distance streaming) and verify termination *before* prompting for manual verification. Never prompt for verification while the sensor/stream is still running.
  - Multi-line UART events: when a hardware action produces multiple simultaneous/immediate messages (e.g. button press event + action log), capture them reliably without buffer-consumption race conditions (e.g. using `wait_for_all` or `wait_for(..., since_index=mark)`).
- Keep expected behavior traceable to a requirement or an explicitly recorded known defect. Do not mark behavior as passed without the required UART or physical evidence.
- Never put Wi-Fi passwords, tokens, or other credentials into source, test output, reports, or saved UART logs.
- Treat hardware tests as stateful operations: identify the target and firmware first, keep tests isolated, and disclose reboot, persistent-state, or physical-interaction effects before running them.
- Never run hardware or interactive tests without an explicit request to execute them.
- Use debug UART capture when requested or needed to diagnose a failure; retain the per-test transcripts and summarize the evidence without replacing it with assumptions.
- For DZ16-specific test and evidence pitfalls, consult [DZ16 gotchas](./.agents/skills/interactive-hardware-tests/references/dz16-gotchas.md); treat `dz16/REPORT.md` and its linked artifacts as the source of truth for current bug status.
