---
description: "Use when editing the DZ17 HW-17 acceptance report, PRD checklist, bug reports, or version matrix."
name: "DZ17 Acceptance Report"
applyTo: "dz17/REPORT.md"
---

# DZ17 acceptance report

- Treat `fw_7/HW-17.md` as the assignment and required deliverable structure; use `fw_7/PRD.md` as the expected-behavior source.
- Keep the PRD checklist, detailed bug reports, version matrix, security findings, and release conclusion aligned to the same version-specific evidence.
- Do not carry legacy bug IDs/statuses forward without a documented mapping to fw_7 requirements. Mark a regression only when evidence establishes a prior fix and subsequent recurrence.
- Verify artifact timestamps and distinguish full-suite runs from focused reruns before calling a result “latest.”
- A skipped precondition is not a product failure. `NOT RUN` security exploration does not mean no findings exist.
- Keep operator feedback, UART assertions, Allure results/attachments, and retained UART transcripts distinct in every status statement. Prompt-format or offline-unit-test changes are not hardware acceptance evidence; preserve run results unless their own artifacts support a correction.
- Verify pack selection from the exact launcher and collection output. A `-All` collection count describes selected tests only, not executed or passed tests; document physical or persistent effects before recommending execution.
- Consult the DZ17-specific [interactive test gotchas](../../.agents/skills/interactive-hardware-tests/references/dz17-gotchas.md) when describing manual observations, RGB LED checks, or Telegram evidence.
