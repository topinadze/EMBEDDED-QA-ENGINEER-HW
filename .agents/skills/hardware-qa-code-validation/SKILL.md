---
name: hardware-qa-code-validation
description: "Independently validate embedded QA test changes, fixtures, assertions, Allure output, execution safety, and claimed test results. Use before considering test automation work complete."
---

# Hardware QA code validation

Validate the implementation and its evidence independently; do not equate plausible code or collection with a passing test.

## Procedure

1. Identify the changed test files, fixtures, pytest configuration, driver code, requirement source, and report/evidence affected by the change.
2. Check that each new test traces to a requirement or known bug and asserts the exact expected output/state/observation.
3. Check data-driven coverage, input boundaries, isolation, fixture scope, cleanup behavior, persistent-state markers, and failure recovery.
4. Check interactive safeguards: explicit markers, console input protection, physical-action prompts, independent setup, and no credential disclosure.
5. Check Allure metadata, readable titles, meaningful steps, attachments, and consistency between test/bug IDs and report.
6. Run safe validations proportionate to the change: syntax/type or lint checks, focused unit tests, pytest collection, and `git diff --check`.
7. Do not execute hardware, interactive, OTA, flash, destructive, or persistent-state tests unless the user explicitly requested that execution.
8. For execution claims, inspect actual command output and the corresponding transcript/report artifact. State unverified results as unverified.
9. Report actionable defects with severity, file/line, evidence, and minimal fix suggestion. If none are found, state the scope and checks performed.

## Completion criteria

- No unsupported pass/fix claims.
- No regression in default test selection or interactive safeguards.
- Expected test cases collect and the focused safe checks pass.
- Evidence and report status accurately reflect firmware and execution outcomes.
- Unrun hardware checks and environmental limitations are called out.
