---
name: uart-debug-evidence
description: "Capture and analyze per-test UART logs for embedded firmware debugging, especially pytest DEBUG runs. Use when diagnosing serial behavior, preserving reproducible evidence, or updating a test report from logs."
---

# UART debug evidence

## Capture

1. Reuse the repository's UART driver and pytest fixture so all TX/RX output is captured consistently.
2. For debug capture, use the project's documented live logging configuration and run from the test directory expected by its configuration.
3. Confirm the fixture records test node ID, detected firmware version, capture timestamp (in the header), and the full transcript. Follow the project's log naming and retention policy; verify whether a rerun can overwrite same-day evidence.
4. Keep one transcript per test so test names and parameter IDs identify the evidence. Retain a concise run summary when it improves investigation.
5. Preserve the distinction between the Allure result/attachments, live console output, and the persisted per-test UART transcript.
6. For interactive DZ17 cases, capture the operator's console/Telegram result through the manual-check evidence path; do not infer it from UART output or assume the UART transcript contains the full prompt/response. Preserve the distinct artifacts and correlate them by test/run.

## Analyze

- Reconstruct chronological TX/RX and correlate with test steps and operator input.
- Identify the exact first unexpected response, missing event, timeout, or state transition. Include relevant surrounding lines.
- Separate harness/precondition failures, UART transport failures, assertion failures, and confirmed firmware defects.
- Corroborate claims with status/version output or physical observations when required.
- For DZ17 Telegram evidence, confirm that the accepted callback/text reply belongs to the authorized chat and active prompt; an expired/stale response is not evidence for the current case. See [DZ17 gotchas](../interactive-hardware-tests/references/dz17-gotchas.md).
- Update traceability tables and known-bug records with version-specific outcome and evidence path; do not generalize one firmware result to other versions.

## Security and retention

- Do not log, publish, or commit Wi-Fi passwords, tokens, or other secrets. Redact before sharing evidence.
- Keep raw evidence intact where permitted; annotate findings separately rather than editing away contradictory output.
- Do not state that a test passed unless the actual pytest result and required evidence show it.
- Consult project-specific evidence-retention guidance when available; do not generalize another project's paths or retention policy.
