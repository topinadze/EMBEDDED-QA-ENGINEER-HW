---
name: pytest-hardware-test-design
description: "Design and implement reliable embedded pytest cases using data-driven parameterization, isolated tests, and fixtures with appropriate scope and cleanup. Use when adding or refactoring hardware test code."
---

# Pytest hardware test design

## Test-case structure

- Keep one test focused on one behavior or one explicitly defined end-to-end scenario.
- Use descriptive test names and parameterize data variations with `pytest.mark.parametrize`; give each case readable values/IDs and assert the expected behavior for every data row.
- Include requirement IDs in Allure story/feature metadata or nearby test documentation.
- Assert device responses and reported state, not just that a command returned.
- Keep independent cases runnable alone and in a suite. State required initial conditions and restore state where safe. Explicitly define each case's Wi-Fi/link and authentication state; use named fixtures to establish and verify connected/disconnected and logged-in/logged-out preconditions over UART. Do not rely on preceding tests or implicit reboot state. Make fixture dependencies express setup order and document persistent effects.

## Isolation and fixtures

1. Use fixtures for shared resource lifecycle and cross-cutting setup, not as hidden test steps.
2. Choose the narrowest useful fixture scope. Hardware and UART handles normally belong to function scope so each test gets a clean serial lifecycle.
3. Make fixture acquisition and cleanup explicit with `yield`; ensure cleanup still runs after assertion failures. Prefer fixture-owned cleanup over test-body `try/finally` when the fixture can represent the resource or device-state lifecycle. Use `try/finally` only for a genuinely local operation the fixture cannot own.
4. Put reusable device operations in the driver; put scenario assertions in tests. Avoid duplicating raw UART parsing or silently swallowing failures.
5. Clean up timers, lamp state, or temporary resources only when the cleanup is safe for the test and cannot mask the primary result. If failure recovery reboots, avoid sending further commands during teardown.
6. Mark tests that alter NVS, scenes, credentials, or other persistent state. Document overwrite risk and required preparation.
7. Make setup failures explicit and distinguish them from product behavior under test.

## UART synchronization

- Synchronize each command/action on the expected UART response or state-transition phrase, then assert the captured response and resulting device state.
- Do not use `sleep()` or a timeout expiring as evidence that a command completed. A timeout is only an upper bound for waiting for the expected phrase; if it is absent, fail explicitly and attach/cite captured UART output.
- Use a bounded observation interval only when the requirement is that an event must not occur; assert that no matching UART event arrived during that interval. Keep rate-limit spacing or requirement-mandated dwell separate from operation-completion waits.

## Expected failures

- Mark a known, reproducible defect with `pytest.mark.xfail(reason=...)` and reference its bug ID plus the report/issue containing evidence.
- Do not use `xfail` for flaky setup, missing preconditions, or unverified hypotheses.
- Review `XPASS`: it indicates the expected failure did not occur. Re-check the behavior and remove the marker when the defect is resolved. Use strict xfail only when the project intentionally wants XPASS to fail the run.

## Validation

- Run pytest collection and focused non-hardware checks first.
- Confirm the exact launcher and pytest marker options before claiming a pack is fully selected. DZ17's default `pytest.ini` excludes `interactive` and `persistent`; verify that the pack's `-All` option overrides those exclusions and any package marker filter. Use collection-only output to confirm scope (not as execution evidence), and treat `-All` as opt-in to all physical/persistent side effects in that pack. See [DZ17 gotchas](../interactive-hardware-tests/references/dz17-gotchas.md).
- Never run serial, interactive, destructive, or persistent tests unless the user explicitly asked for hardware execution.
- Use the project configuration and supported firmware checks rather than bypassing fixtures to force a result.
- Consult project-specific hardware gotchas when applicable; do not generalize them to other firmware, boards, or assignments.
