---
name: interactive-hardware-tests
description: "Implement and execute pytest scenarios requiring physical buttons, LEDs, displays, sensors, or operator observation on embedded hardware. Use for manual prompts, UART-interactive cases, and bench procedures."
---

# Interactive hardware tests

## Design

- Mark operator-dependent cases `@pytest.mark.interactive`; preserve the repository's default exclusion of interactive cases from unattended test runs.
- Use the established manual-check fixture and require uncaptured console input (`-s`). Do not emulate a physical button by sending a console command unless the requirement explicitly calls for that.
- **Operator Preparation Protocol (`manual_prepare`)**:
  - Before asking the operator to act or triggering a physical observation, present a clear preparation prompt (`manual_prepare`):
    1. **What to do**: which exact button to press (e.g. K1/K2/K3/K4), where to place an obstacle, or what physical state to configure.
    2. **What to observe**: audible relay clicks, LED colors/blinks, reboot countdowns, or streaming values.
    3. **Duration / Time limit**: state how long the observation will last or how much time the operator has (e.g. "Duration: ~5-10 seconds", "Wait for streaming ~8 seconds").
    4. **Readiness confirmation**: pause until the operator explicitly confirms readiness (e.g. `Press Enter when ready:`).
- **Streaming & Timed Operations Discipline**:
  - For streaming or continuous commands (e.g. `distance`, animations):
    * Allow adequate observation time (e.g. 6-10 seconds) so the operator can comfortably observe the physical phenomenon and console stream.
    * Explicitly terminate the stream (e.g. send `\n` to stop `distance`, confirm stopped state) **before** calling `manual_check`.
    * Never prompt for verification while the device is actively flooding the serial console with measurement logs.
- **Multi-Message UART Event Capture**:
  - When physical events trigger multiple immediate UART log messages (e.g. button press log `button 2 pressed (GPIO40)` plus action log `[K2] relay ON`), record the UART buffer index before prompting or acting (`mark = len(device_driver.uart_log)`).
  - Use atomic multi-message matchers (such as `device_driver.wait_for_all(texts, since_index=mark)`) or inspect existing logs from the recorded mark (`wait_for(text, since_index=mark)`) to avoid race conditions where reading the first log drains serial buffers and starves subsequent checks.
- Capture machine-verifiable UART evidence separately from physical observations. Record pass/fail and optional operator comments through the established helper.
- Keep test steps and prompts self-explanatory; use Allure steps around phases, action prompts, UART waits, and visual checks.
- Design each case to run independently, including opening/closing its own UART fixture. Never assume a prior test has left the device in a suitable state.
- Consider failure recovery and teardown ordering. If a test reboots on failure, do not issue later commands against a rebooting device.
- For DZ16 firmware-specific examples (including physical LED color defects), consult [DZ16 gotchas](./references/dz16-gotchas.md); do not generalize those defects to other firmware or boards.

## Execution safeguards

1. Execute interactive hardware tests only after the user explicitly asks to run them.
2. Confirm target port, expected firmware, initial connectivity/state, saved-credential requirements, and any physical or persistent side effects.
3. Run only the selected test(s) with the configured pytest markers and `-s`.
4. Explain each physical action at the point it is needed; wait for the user's response rather than guessing.
5. Stop or mark blocked when the required state or hardware is unavailable. Do not turn unmet preconditions into product defects.
6. After execution, verify the actual pytest outcome, Allure result, and UART transcript; update the report only to the extent evidence supports.

## Safety

- Do not ask users to paste credentials into chat or allow secrets into UART logs.
- Do not flash firmware, perform OTA, erase storage, or alter persistent settings unless explicitly in scope and approved.
- Warn when a failure recovery action will reboot or otherwise change the board's state.
