# DZ17 — SENTRY SWM-2 manual acceptance testing

This package prepares the manual acceptance work defined in [`../fw_7/HW-17.md`](../fw_7/HW-17.md). It is based on the fw_7 PRD and bench instructions, with dz16 used only as a source of reusable workflow ideas and historical regression candidates.

**This stage is manual-only.** No pytest automation is included. The operator completed the beta OTA transition from firmware 2.1.0 to 2.3.0; the upgrade and self-check succeeded, and the partial OTA-10 comparison is recorded in [`REPORT.md`](REPORT.md). Remaining OTA scenarios and the 2.3.0 acceptance checklist are outstanding. Do not mark a case complete without the required evidence from the actual device.

## Authoritative materials

- Requirements: [`../fw_7/PRD.md`](../fw_7/PRD.md)
- Required scenarios and submission format: [`../fw_7/HW-17.md`](../fw_7/HW-17.md)
- Flashing, initial firmware check, UART settings: [`../fw_7/README.md`](../fw_7/README.md)
- Bench wiring and physical observations: [`../fw_7/WIRING.md`](../fw_7/WIRING.md)
- Local OTA server and its error fixtures: [`../fw_7/tools/README.md`](../fw_7/tools/README.md)
- Case IDs, execution sequence, PRD correspondence, and historical bug applicability: [`TEST_PLAN.md`](TEST_PLAN.md)

## Before testing

1. Assemble and inspect the bench using `fw_7/WIRING.md`. All modules must be powered from 3.3 V; do not connect a module to the ESP32-S3 5 V pin.
2. Confirm the target ESP32-S3, UART port, 115200 8N1 terminal, HC-SR04, relay/diode, and the buttons. Record the bench and host details in `REPORT.md`.
3. Flash the supplied `fw_7/sentry_fw7_v2.1.0_merged.bin` using the `erase-flash` procedure in `fw_7/README.md`. Erasing flash removes existing NVS data. Record the operation and confirm `version`, partition, image state, and boot log before continuing.
4. Establish Wi-Fi and account setup through the serial console. The account and saved device settings persist; record non-secret identifiers only. Never save the Wi-Fi password or other credentials in UART captures, this report, screenshots, or the submission archive.
5. Perform the 2.1.0 checklist first, then the beta OTA to 2.3.0, verify OTA-10 state retention, and perform the 2.3.0 checklist. Follow the exact OTA and local-server scenarios in `TEST_PLAN.md`.
6. Do not start OTA or persistent-state scenarios until the tester has recorded the current firmware, active partition, account and configuration state, and accepted the described change/reboot effects. Do not run destructive or interactive checks implicitly.

## Evidence handling

Save raw UART captures, including command and response, under `logs/manual/` with filenames that identify the test case, firmware version, date, and OTA transition where applicable. Keep pre- and post-OTA evidence attributable to the same run. Include physical observations (for example relay click, diode state, RGB color, button response, and sensor target/distance) as separate notes or media; UART output alone does not prove a physical result.

Redact Wi-Fi passwords before retaining or sharing a capture. Keep evidence unchanged otherwise; add interpretation in `REPORT.md`, not by editing away contradictory output. Link each checklist result and bug reproduction to its evidence path.

The root `.gitignore` excludes `dz17/logs/automated/` for possible future use; manual evidence in `dz17/logs/manual/` is not covered by that rule. This package does not create automated tests or automated logs.

## Status vocabulary

- `NOT RUN`: no execution evidence collected.
- `PARTIAL`: only some required observations or steps were verified.
- `PASS`: every stated UART, state, and physical observation for the case is supported by retained evidence.
- `FAIL`: observed behavior differs from the cited PRD requirement; create/link a bug report.
- `BLOCKED`: a documented precondition or required hardware/service was unavailable. Do not count this as a product failure.
