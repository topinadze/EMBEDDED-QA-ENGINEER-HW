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
