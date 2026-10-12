---
name: interactive-hardware-tests
description: "Implement and execute pytest scenarios requiring physical buttons, LEDs, displays, sensors, or operator observation on embedded hardware. Use for manual prompts, UART-interactive cases, and bench procedures."
---

# Interactive hardware tests

## Design

- Mark operator-dependent cases `@pytest.mark.interactive`; preserve the repository's default exclusion of interactive cases from unattended test runs.
- Use the established manual-check fixture and require uncaptured console input (`-s`). Do not emulate a physical button by sending a console command unless the requirement explicitly calls for that.
- Before asking the operator to act, establish machine-verifiable preconditions and state the exact physical action and observation in the prompt.
- Capture machine-verifiable UART evidence separately from physical observations. Record pass/fail and optional operator comments through the established helper.
- Keep test steps and prompts self-explanatory; use Allure steps around phases, action prompts, UART waits, and visual checks.
- Design each case to run independently, including opening/closing its own UART fixture. Never assume a prior test has left the device in a suitable state.
- Consider failure recovery and teardown ordering. If a test reboots on failure, do not issue later commands against a rebooting device.

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
