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
- Keep independent cases runnable alone and in a suite. State required initial conditions and restore state where safe.

## Isolation and fixtures

1. Use fixtures for shared resource lifecycle and cross-cutting setup, not as hidden test steps.
2. Choose the narrowest useful fixture scope. Hardware and UART handles normally belong to function scope so each test gets a clean serial lifecycle.
3. Make fixture acquisition and cleanup explicit with `yield`; ensure cleanup still runs after assertion failures.
4. Put reusable device operations in the driver; put scenario assertions in tests. Avoid duplicating raw UART parsing or silently swallowing failures.
5. Clean up timers, lamp state, or temporary resources only when the cleanup is safe for the test and cannot mask the primary result. If failure recovery reboots, avoid sending further commands during teardown.
6. Mark tests that alter NVS, scenes, credentials, or other persistent state. Document overwrite risk and required preparation.
7. Make setup failures explicit and distinguish them from product behavior under test.

## Expected failures

- Mark a known, reproducible defect with `pytest.mark.xfail(reason=...)` and reference its bug ID plus the report/issue containing evidence.
- Do not use `xfail` for flaky setup, missing preconditions, or unverified hypotheses.
- Review `XPASS`: it indicates the expected failure did not occur. Re-check the behavior and remove the marker when the defect is resolved. Use strict xfail only when the project intentionally wants XPASS to fail the run.

## Validation

- Run pytest collection and focused non-hardware checks first.
- Never run serial, interactive, destructive, or persistent tests unless the user explicitly asked for hardware execution.
- Use the project configuration and supported firmware checks rather than bypassing fixtures to force a result.
- For DZ16 examples of firmware preconditions and state leakage between reboot/Wi-Fi tests, see [DZ16 gotchas](../interactive-hardware-tests/references/dz16-gotchas.md).
