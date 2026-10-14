# DZ16 gotchas

These examples are specific to the DZ16 ESP32-S3 test setup. They are workflow lessons, not new product requirements or a template for a different assignment's bench workflow. Re-check the current PRD and bench instructions before reuse; the current firmware-by-firmware bug status remains in [`dz16/REPORT.md`](../../../../dz16/REPORT.md), and historical outcomes do not automatically apply to a new workflow or release.

## Gotchas

- **Check fixture support before diagnosing the device.** The first 1.3.0 automation run was blocked because the fixture's supported-version allowlist omitted 1.3.0. Confirm the reported `version` and `--expected-fw-version`, and update an intentional allowlist when support changes; do not bypass the fixture.
- **Do not treat UART state as proof of physical color.** On 1.3.0, named red/green and purple/cyan were physically confused even when commands and status reported the requested RGB. For an unchanged-color visual test on that firmware, use a distinct baseline such as steady blue, not red or green. Keep the named-color visual test as a defect detector; do not redefine incorrect output as expected behavior.
- **Re-establish state after reboot.** DZ16 reboot settings checks left Wi-Fi auto-connect disabled, so later K3 tests had unmet preconditions and could not establish BUG-01/BUG-02. Make each test establish or verify connectivity and saved credentials independently. Report blocked/xfail preconditions separately from a reproduced firmware defect.
- **Wait for reboot to finish before capturing the tested firmware.** A K3 test started while the board was rebooting produced a log under `unknown`; without a stable `version` response, do not attribute that capture to a firmware version or use it as defect evidence.
- **Match transcripts to the exact source revision and execution.** A saved transcript with the old green baseline cannot verify a test that now sets blue. Check the node ID, timestamp, firmware header, command sequence, and pytest outcome together. A changed source file or Allure report alone does not prove the hardware case ran.
- **Preserve repeated-run evidence deliberately.** DZ16 keeps only the latest and one `.prev.txt` transcript per test and date; another same-day rerun can overwrite older evidence. Export/copy needed captures before rerunning, and never edit raw UART logs to make them agree with current expectations.
- **Run the DZ16 launcher from its actual location.** `run-lamp.ps1` is under `dz16/`; from the repository root invoke `.\dz16\run-lamp.ps1`, or change to `dz16` first. `-All` includes interactive cases and enables `-s`; execute those only when the operator explicitly requested hardware testing and preconditions are confirmed.
- **Treat OTA as a state transition, not just a version change.** Record version/slot and lamp/Wi-Fi state before and after OTA; verify self-check and resulting state. A missing scene or setting after OTA is evidence of a persistence issue, but nearby boot warnings are not a proven cause unless the evidence establishes the link.

## Evidence anchors

- Firmware-specific defect matrix and observed outcomes: [`dz16/REPORT.md`](../../../../dz16/REPORT.md), sections 1, 5, and 6.
- DZ16 launch commands, markers, interactive selection, and log retention: [`dz16/README.md`](../../../../dz16/README.md).
- Physical-color and baseline example: [`dz16/tests/test_lamp.py`](../../../../dz16/tests/test_lamp.py), `test_invalid_rgb_visual`.
