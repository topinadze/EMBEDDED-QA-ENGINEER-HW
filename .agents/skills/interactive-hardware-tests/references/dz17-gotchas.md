# DZ17 gotchas

These notes apply to the DZ17 SENTRY SWM-2 test harness and its ESP32-S3 setup. They are workflow and evidence guidance, not new PRD requirements. Check the current [DZ17 test plan](../../../../dz17/TEST_PLAN.md), [acceptance report](../../../../dz17/REPORT.md), and [README](../../../../dz17/README.md) for current procedures and run evidence.

## Operator prompts and physical checks

- **One RGB LED has two roles.** With Beacon on, it displays the configured lamp color. With Beacon off, it indicates Wi-Fi/login state: red = disconnected, orange = connected/logged out, green = connected/logged in. Confirm logical state over UART and the physical appearance with the operator; never treat one as proof of the other.
- **Prepare before action.** Before a physical action or observation, give the operator the exact action, expected observation, duration/time limit, and a readiness confirmation. For streaming checks, stop the stream and verify it stopped before asking for a visual verdict.
- **Login-state icons are cues, not state checks.** Button prompts may show logged-in/logged-out context for K1–K4. Fixtures and UART must establish the real precondition; do not derive authentication from prompt text or a visual icon.
- **Make color checks visually useful without changing the requirement.** Console prompts identify the named color and RGB values, with an ANSI sample when supported; captured/no-color output retains readable text. Telegram prompts show the named color and RGB numbers and may attach a PNG reference swatch. The sample is not a measurement; the operator judges the physical LED.
- **Keep evidence channels distinct.** A prompt or readiness acknowledgment does not pass a check. Record the operator's manual result/comment through the helper, retain UART assertions/transcripts separately, and correlate them with the same test/run. Report `NOT RUN` if a required physical observation was not made.

## Telegram operator mode

- Console remains the default; Telegram is opt-in. The helper accepts callbacks/text only from the configured private chat and matches callbacks to the prompt message; unthreaded text must have a later chat message ID than the prompt (the timestamp check alone cannot distinguish messages sent in the same second). Responses to another/older prompt are ignored.
- Only one pytest process may poll a given bot token at a time. Telegram API/configuration errors and response timeouts must fail explicitly; do not silently fall back to console or treat a sent message as operator confirmation.
- Free-text comments are evidence and are redacted for common secret-like key/value patterns, but operators must not enter passwords, tokens, or other secrets.

## Test selection and evidence

- DZ17's `pytest.ini` defaults exclude `interactive` and `persistent` tests. `-All` semantics are launcher-specific: inspect the script's test path, marker expression, and addopts overrides instead of trusting the flag name. `run-distance.ps1 -All` is verified to select the entire target module, including unmarked offline helpers and interactive, persistent, and long-range cases.
- Collection is the proof of selection, not execution. The current Distance module collects 44 cases with `-All`: 21 offline helper cases and 23 device-facing cases. Other pack counts and `-All` behavior must be confirmed with their own collection; the counts can change.
- Treat `-All` as a safety opt-in: it can exercise hardware, change persistent state, or require operator actions. Do not execute it without explicit authorization and confirmed preconditions.
- Per-test UART transcripts, JUnit, Allure output, terminal output, and Telegram responses are distinct artifacts. Verify timestamps, node IDs, firmware, and overwrite/retention behavior before calling a run latest or attributing a result.

## Evidence anchors

- [DZ17 README interaction and launcher guidance](../../../../dz17/README.md#safety--interactive-protocol-agentsmd).
- [DZ17 acceptance report and retained outcomes](../../../../dz17/REPORT.md).
- [Manual prompt implementation](../../../../dz17/manual_checks.py) and [prompt tests](../../../../dz17/tests/test_manual_checks.py).
