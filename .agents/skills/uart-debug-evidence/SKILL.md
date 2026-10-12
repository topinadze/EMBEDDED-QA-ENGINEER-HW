---
name: uart-debug-evidence
description: "Capture and analyze per-test UART logs for embedded firmware debugging, especially pytest DEBUG runs. Use when diagnosing serial behavior, preserving reproducible evidence, or updating a test report from logs."
---

# UART debug evidence

## Capture

1. Reuse the repository's UART driver and pytest fixture so all TX/RX output is captured consistently.
2. For debug capture, use the project's live logging configuration (for DZ16, `-o log_cli=true -o log_cli_level=DEBUG`). Run from the test directory expected by its configuration.
3. Confirm the fixture records test node ID, detected firmware version, capture timestamp (in the header), and the full transcript. Files are named `YYYYMMDD-<test name>.txt`, keeping at most the latest and one `.prev.txt` per test and date. In DZ16, per-test debug logs are stored under `dz16/logs/automated/lamp/<version>/`.
4. Keep one transcript per test so test names and parameter IDs identify the evidence. Retain a concise run summary when it improves investigation.
5. Preserve the distinction between the Allure result/attachments, live console output, and the persisted per-test UART transcript.

## Analyze

- Reconstruct chronological TX/RX and correlate with test steps and operator input.
- Identify the exact first unexpected response, missing event, timeout, or state transition. Include relevant surrounding lines.
- Separate harness/precondition failures, UART transport failures, assertion failures, and confirmed firmware defects.
- Corroborate claims with status/version output or physical observations when required.
- Update traceability tables and known-bug records with version-specific outcome and evidence path; do not generalize one firmware result to other versions.

## Security and retention

- Do not log, publish, or commit Wi-Fi passwords, tokens, or other secrets. Redact before sharing evidence.
- Keep raw evidence intact where permitted; annotate findings separately rather than editing away contradictory output.
- Do not state that a test passed unless the actual pytest result and required evidence show it.
