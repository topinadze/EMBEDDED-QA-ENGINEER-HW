# DZ17 — SENTRY SWM-2 Acceptance Testing & Autotests

This package implements automated and interactive pytest test suites and bench procedures for **SENTRY SWM-2 (fw_7)**, based on [`../fw_7/PRD.md`](../fw_7/PRD.md), [`../fw_7/HW-17.md`](../fw_7/HW-17.md), and manual check baselines in [`REPORT.md`](REPORT.md) and [`TEST_PLAN.md`](TEST_PLAN.md).

## Test Suite Architecture

```
dz17/
├── config/
│   ├── test_config.py          # Credential resolution (env vars, secrets, CLI overrides)
│   ├── wifi_config.py          # Wi-Fi and UART configuration compatibility facade
│   ├── wifi_secrets.example.py # Template for local credentials
│   └── wifi_secrets.py         # Local credentials (git-ignored)
├── drivers/
│   └── device_driver.py        # SENTRY SWM-2 UART driver (parsers for [BEACON], [LINK], [SONAR], [VALVE], etc.)
├── manual_checks.py            # Operator preparation prompts (manual_prepare) and verification (manual_check)
├── pytest.ini                  # Pytest markers and default exclusion of interactive & persistent tests
├── conftest.py                 # Fixtures: firmware/UART lifecycle and Beacon state teardown
├── tests/
│   ├── test_lamp.py            # LM-1 to LM-8, interactive lamp/status-LED observations
│   ├── lamp_test_helpers.py    # Shared lamp status, timer, power/configuration, and recovery steps
│   ├── test_lamp_helpers.py    # Unit tests for shared lamp helpers (no hardware)
│   ├── test_wifi.py            # WF-1 to WF-5 with LM-8 status-LED confirmations
│   ├── test_buttons.py         # §12: K1-K4 actions and button pairs
│   ├── test_distance.py        # DS-1 to DS-5: sonar measurement, stream, stats, filter, calibration
│   ├── test_relay.py           # RL-1 to RL-7: valve control, cycle accounting, schedule, auto, health
│   ├── test_guard.py           # Partial GD-1 to GD-3 coverage: status/zones, arming and panic
│   ├── test_alert.py           # Partial AL-1 to AL-5 coverage: generation, listing, acknowledgement, critical effects
│   ├── test_device_driver_parsers.py # Unit tests for driver UART parsers (no hardware required)
│   └── test_manual_checks.py   # Unit tests for manual check protocol (no hardware required)
├── run.ps1                     # Main test launcher
├── run-lamp.ps1                # Lamp test launcher
├── run-wifi.ps1                # Wi-Fi test launcher
├── run-buttons.ps1             # Buttons test launcher (runs with -s)
├── run-distance.ps1            # Distance test launcher
├── run-guard.ps1               # Guard test launcher (2.3.0, -s)
└── run-alert.ps1               # Alert Center test launcher (2.3.0, -s)
```

## Safety & Interactive Protocol (`AGENTS.md`)

- **Interactive Test Protocol (`manual_prepare`)**:
  All tests marked `@pytest.mark.interactive` present a clear 4-part preparation prompt to the operator before any physical action or observation:
  1. **What to do**: which button to press, where to position obstacle.
  2. **What to observe**: LED color, relay click, measurement stream.
  3. **Duration / time limit**: specified time (e.g. ~5-10 s).
  4. **Confirmation**: waits for Enter before proceeding (`Press Enter when ready:`).
  Every operator-facing notification (preparation, manual check, result, and invalid response) is separated by simple `=` divider lines, without a box or fixed-width wrapping. Preparation is cyan, checks are yellow, PASS is green, and FAIL/invalid input is red when the terminal supports ANSI color; headings, field labels, and input prompts are highlighted. Recognized lamp/LED color names (for example, “Blue lamp”) and valid RGB triplets also receive color-matched indicator dots. Captured output, `NO_COLOR`, and `TERM=dumb` remain plain text but retain the divider lines. The action, observation, and duration fields are separated by blank lines for readability.
- **Streaming Discipline**:
  Continuous streams (e.g. `distance log 100`, K3 sonar stream) are cleanly stopped (`distance stop` / second K3 tap) and confirmed stopped *before* prompting for manual verification.
- **Lamp RGB LED and status indication**:
  There is one RGB LED, not a separate Beacon emitter and board status LED. When lamp output is ON it shows the configured lamp color; when lamp output is OFF, the same LED shows connection/login status: RED means Wi-Fi disconnected, ORANGE means Wi-Fi connected but logged out, and GREEN means Wi-Fi connected and logged in. UART-reported state and the operator's physical observation are checked separately.
- **Multi-Line UART Captures**:
  UART log indexes (`mark = len(device_driver.uart_log)`) are recorded prior to prompts to avoid race conditions.
- **UART Transcript Retention**:
  With DEBUG logging enabled, one latest transcript is kept for each test within each firmware-version folder under `logs/automated/<category>/<firmware>/`. A newer run replaces the previous transcript for that same test and firmware; logs for other tests and firmware versions are retained.
- **Credentials**:
  Passwords and tokens are redacted from UART transcripts and Allure attachments; `wifi_secrets.py` is excluded by `.gitignore`.
  Free-text manual comments are sanitized for common password/token/secret key-value formats before
  logging and display; operators should still never enter credentials or secrets in a comment.
  Copy `config/wifi_secrets.example.py` to `config/wifi_secrets.py` and set the local Wi-Fi and
  device account credentials there. Alternatively, provide account values with `HW17_USER` /
  `HW17_PASSWORD` or `TEST_USER` / `TEST_PASSWORD`; environment values override the local file.
  Do not commit or share the local secrets file.

## Test Execution

### Configuration locations

| Setting | Where to configure it |
|---|---|
| Test selection defaults and marker definitions | [`pytest.ini`](pytest.ini). By default, pytest excludes tests marked `interactive` or `persistent`. |
| UART port, baud rate, expected firmware | [`conftest.py`](conftest.py): `--port`, `--baudrate`, `--expected-fw-version`. Hardware launchers default to `COM4`; pass `-Port` and `-Fw` to set the target explicitly. Direct pytest defaults to 115200 baud and detects a unique ESP32 port if `--port` is omitted. |
| Launcher defaults and run options | The relevant [`run-*.ps1`](.) script. Main/lamp/Wi-Fi/buttons/distance launchers default to firmware 2.1.0; Guard and Alert default to 2.3.0. |
| Wi-Fi and device-account defaults | Copy [`config/wifi_secrets.example.py`](config/wifi_secrets.example.py) to the git-ignored `config/wifi_secrets.py` and set `DEFAULT_WIFI_SSID`, `DEFAULT_WIFI_PASSWORD`, `DEFAULT_APP_USER`, and `DEFAULT_APP_PASSWORD`. Environment alternatives are `HW17_WIFI_SSID` / `HW17_WIFI_PASSWORD` or `TEST_WIFI_SSID` / `TEST_WIFI_PASSWORD`, and `HW17_USER` / `HW17_PASSWORD` or `TEST_USER` / `TEST_PASSWORD`. Per-run pytest options are `--wifi-ssid`, `--wifi-password`, `--app-user`, and `--app-password`. |
| Invalid Wi-Fi scenario inputs | Set `HW17_WIFI_WRONG_PASSWORD` (or `TEST_WIFI_WRONG_PASSWORD`) and `HW17_WIFI_MISSING_SSID` (or `TEST_WIFI_MISSING_SSID`) in the local environment. |
| Guard PIN | Set `HW17_GUARD_PIN` in the local environment. It must be four digits; do not put it in source or share it. |
| Generated logs and test results | `logs/automated/<category>/<firmware>/`; launchers also save dated run logs and JUnit XML. Per-test UART transcripts are written when DEBUG logging is enabled. |

For credentials, precedence is per-run CLI override, then `HW17_*`, then the corresponding
`TEST_*` variable, then `config/wifi_secrets.py` or the code default. Never commit or share
credentials.

Before every authenticated test, the fixture verifies a valid Wi-Fi connection and IP even when
the device already has an active session; when a test SSID is configured, the connected SSID must
match it exactly. If the current connection is invalid or on another network, it first tries
`reconnect` using the device's saved profile. If that does not establish a valid connection to the
configured SSID, it falls back to `connect` using the configured test SSID/password from the local
secrets file, environment, or launcher overrides. This fallback can save or replace the device's
persistent Wi-Fi profile; configure only the intended test network. The password is redacted from
UART/Allure evidence.

The fixture confirms `whoami` after Wi-Fi is ready. If the configured user is not logged in, it
logs out any different active account, waits for the logged-out response, then logs in with the
configured account and waits for both the login confirmation and matching `whoami` response.
Tests that only require Wi-Fi use `device_driver` with `ensure_wifi_connected`; tests that begin
with a deliberate logged-out or disconnected state use the lower-level `device_driver` fixture and
establish only the preconditions they need. `ensure_authenticated_device` exposes the same
Wi-Fi/account preparation for a second time within a test, such as after reboot. The fixture leaves
the session logged in during teardown.

### 1. Run Unit Tests (No hardware required)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest tests/test_device_driver_parsers.py tests/test_manual_checks.py
```

All DZ17 PowerShell launchers use the isolated `dz17\.venv`; they do not reuse the DZ16
environment or fall back to a system Python. Run the setup commands above from the `dz17` folder
before using a launcher.

### 2. Run Automated Hardware Suites (Non-interactive, non-persistent)
```powershell
# Run all automated tests on COM4 against FW 2.1.0
.\run.ps1 -Port COM4 -Fw 2.1.0

# Run the complete discovered DZ17 suite on FW 2.3.0, including interactive
# and persistent-state tests (see the safety note below).
.\run.ps1 -Port COM4 -Fw 2.3.0 -All

# Run an entire functional package, including interactive and persistent tests.
# Review required operator actions and persistent effects before using -All.
.\run-lamp.ps1 -Port COM4 -Fw 2.1.0 -All
.\run-wifi.ps1 -Port COM4 -Fw 2.1.0 -All
.\run-buttons.ps1 -Port COM4 -Fw 2.1.0 -All
.\run-distance.ps1 -Port COM4 -Fw 2.3.0 -All
.\run-guard.ps1 -Port COM4 -Fw 2.3.0 -All
.\run-alert.ps1 -Port COM4 -Fw 2.3.0 -All

# Run the default UART-only, non-persistent subsets.
.\run-lamp.ps1 -Port COM4 -Fw 2.1.0
.\run-wifi.ps1 -Port COM4 -Fw 2.1.0
.\run-distance.ps1 -Port COM4 -Fw 2.1.0

# Guard / Alert safe tests default to firmware 2.3.0 and exclude
# interactive and persistent-state cases.
.\run-guard.ps1 -Port COM4
.\run-alert.ps1 -Port COM4
```

The full-suite `run.ps1 -All` command runs every discovered test, including cases that require
operator interaction and cases marked persistent. It passes `-s` so interactive prompts work and
checks that the connected device reports firmware 2.3.0. Review the interactive and persistent-state
effects described below before running it; it may actuate the relay, change device settings, save
Wi-Fi configuration, and add alert-history entries. It does not flash firmware.

### 3. Run Interactive Hardware Tests (Requires operator action, uncaptured console `-s`)
```powershell
# Run interactive operator buttons tests (the K2 relay test actuates the relay)
.\run-buttons.ps1 -Port COM4 -Fw 2.1.0

# Run the full lamp pack with UART assertions only (manual physical checks skipped).
# Persistent-state tests still require the explicit -Persistent opt-in.
.\run-lamp.ps1 -Port COM4 -Fw 2.1.0 -Persistent

# Run the same lamp cases with operator physical observations enabled.
# This includes persistent scene/reboot checks: scene 1 and scene 2 are
# overwritten, and the device reboots. See the safety notes below.
.\run-lamp.ps1 -Port COM4 -Fw 2.1.0 -ManualChecks -Persistent

# The previous -Interactive spelling remains an alias for -ManualChecks.
.\run-lamp.ps1 -Port COM4 -Fw 2.1.0 -Interactive -Persistent -TestName "test_lamp_named_color_visual and red"

# Run automated logout/relogin verification that the Beacon remains off.
.\run-lamp.ps1 -Port COM4 -Fw 2.3.0 -TestName "test_lamp_logout_and_relogin_keeps_beacon_off"

# Check the observed status-LED mapping for each Wi-Fi/login combination.
# This is interactive and changes Wi-Fi/login state temporarily; the test restores both.
.\run-lamp.ps1 -Port COM4 -Fw 2.3.0 -Interactive -TestName "test_lamp_status_led_connection_login_mapping"

# Wi-Fi disconnect/reconnect tests include their corresponding status-LED
# physical confirmations (main Beacon lamp must be OFF).
.\run-wifi.ps1 -Port COM4 -Fw 2.1.0 -Interactive -TestName "test_wifi_disconnect"
.\run-wifi.ps1 -Port COM4 -Fw 2.1.0 -Interactive -TestName "test_wifi_reconnect"
# The unauthenticated button test verifies the status LED after logout and
# confirms K1 does not change it.
.\run-buttons.ps1 -Port COM4 -Fw 2.1.0 -TestName "test_button_unauthenticated_blocked"

# Run the interactive sonar measurement characterization.
# For each position, answer yes, enter the ruler-measured gap, position and hold
# the target after the preparation prompt, and the test captures one `distance`
# reading. Repeat until answering no; the final summary and aggregate assertion
# include every attempted position. The ±0.5 cm threshold is exploratory only.
.\run-distance.ps1 -Port COM4 -Fw 2.1.0 -Interactive

# Run every Distance test, including interactive and persistent cases.
# Requires operator interaction and may change persistent device state.
.\run-distance.ps1 -Port COM4 -All -Fw 2.3.0
```

Lamp Beacon scenarios each contain UART response/readback assertions plus optional
physical observations. Run them without prompts for UART-only validation, or pass
`-ManualChecks` (equivalent to `--manual-checks -s`) to enable the preparation and
operator-confirmation prompts. In UART-only mode, Allure marks those physical
checks as NOT RUN rather than passing them. The tests remain marked `interactive`
to identify scenarios capable of operator verification, and persistent-state
tests still require the explicit `-Persistent` opt-in. Coverage includes on/off/
toggle, named and custom colors, brightness, operating modes, timer expiry/
cancellation, scene restore, and persisted settings after reboot. Prompts describe
each observation and wait for readiness before device actions.

The lamp status-color mapping characterization is interactive but does not write
persistent state. It temporarily changes Wi-Fi/login state, requires the
device in NORMAL with Guard disarmed and higher-priority LED indications inactive,
and restores the configured Wi-Fi connection and user session after each case.
The lamp has one RGB LED: when lamp output is OFF, that same LED indicates Wi-Fi
and login status rather than becoming dark or acting as a separate board LED.
Expected observed colors are GREEN (connected/logged in), ORANGE (connected/
logged out), and RED (disconnected); this is not a PRD-defined color contract.
Lamp-off manual prompts use shared wording from `tests/lamp_test_helpers.py`;
after `lamp off`, an OFF toggle, logout, timer expiry, or reboot, they ask for
the status color expected for the verified connection/login state. The reboot
persistence case checks the OFF/status-color state after startup before turning
the lamp output on to inspect the saved scene.
The interactive negative-input sweep verifies every rejected
command and its unchanged UART readback while the operator confirms that the
Beacon remains visibly lit. Timer boundary and E507 checks likewise verify
UART state and include a physical observation when the lamp output changes.
On logout, the same LED is expected to change from the configured lamp color
to ORANGE; after login it remains OFF as a lamp output and shows GREEN. The
logout/relogin test does not issue protected lamp-status commands while logged out.

Lamp-setting checks establish and read back Beacon `ON` before changing color,
RGB, brightness, or mode, and confirm the lamp remains on with the requested
setting. The E507 timer test begins from a verified `ON` state, confirms the
actual `ON`→`OFF` transition, asks the operator to confirm the GREEN status
indication on the same RGB LED (Wi-Fi connected and user logged in), and only
then attempts to start a timer. Off-state and toggle checks verify the relevant
starting state and response, rather than accepting a no-op from a lamp that was
already in the target state. Scene save/change/load and reboot
persistence workflows request physical observations after each meaningful
output configuration, while keeping UART assertions separate from operator
evidence. The
`lamp_state` fixture captures the state and enforces a timer-off precondition
once for every lamp test, then restores captured power/settings after the test
and recovers Wi-Fi and the authenticated session when needed. The shared
`assert_lamp_status` and `assert_lamp_timer_active` helpers check UART readbacks
consistently; scenario-specific expected behavior remains asserted in the tests.
The revised cases are implementation-only until hardware execution.

Reusable lamp actions, status assertions, and Allure steps live in
[`tests/lamp_test_helpers.py`](tests/lamp_test_helpers.py); requirement-specific
assertions, scenario order, and manual observations stay in
[`tests/test_lamp.py`](tests/test_lamp.py). Put shared hardware behaviors in a
test-support module and decorate reusable actions with `@allure.step` so they
remain visible as nested Allure steps. Reserve `conftest.py` for pytest fixture
setup/teardown and shared fixture lifecycle; put low-level reusable UART
operations in `drivers/device_driver.py`.

The scene case permanently overwrites saved scene 1, but the fixture restores
the captured lamp settings and power state. The reboot case permanently
overwrites scene 2 with yellow/50%/blink and temporarily changes the current
settings to purple/75%/breathe. After a successful reboot and session recovery,
the fixture restores the pre-test lamp settings and power state. If reboot or
session recovery is not confirmed, it does not send further device commands.
Previous scene contents cannot be recovered. Do not select these cases if scene
1 or scene 2 must be preserved.

For the Distance launcher, `-All` selects every test marked `distance`, including
`interactive` and `persistent` cases, and enables uncaptured console input (`-s`).
Without `-All`, the default excludes both categories; `-Interactive` selects interactive
Distance cases, and `-Persistent` opts into persistent but non-interactive cases.
The operator distance-accuracy sweep runs before the reboot/persistence test so a reboot
failure cannot prevent the physical measurement check from being reached.

Across the Lamp, Wi-Fi, Buttons, Distance, Guard, and Alert launchers, `-All` selects every test
in that package, including interactive and persistent cases, and enables uncaptured console input
where required. The Buttons launcher targets the full button suite and accepts `-All` to make that
selection explicit. For Alert, full-history cleanup remains separately gated by the operator
confirmation at launcher startup.

### 4. Run 2.3.0 Guard and Alert Tests

Guard and Alert Center are 2.3.0-only features. The read-only/status and invalid-zone tests are
safe to select without persistent-state tests; valid-zone boundary checks alter the configured
Guard zone temporarily and restore it. Alert-generation/acknowledgement tests add entries to alert
history and are explicitly persistent. Critical-alert tests actuate the relay and switch NORMAL
to VERBOSE; the operator should observe the relay and confirm the Beacon lamp flashes purple.
Guard-alarm tests also actuate the relay and require operator observation of the physical effects.
The automated tests cover only a subset of GD-1
to GD-5 and AL-1 to AL-5; intrusion timing, alternate panic triggers, Guard PIN/log behavior,
20-alert retention, acknowledge-all, successful clear, invalid test levels, and the EMERGENCY
exception remain uncovered as detailed in [TEST_PLAN.md](TEST_PLAN.md). The Guard-panic test
acknowledges its generated critical alert during cleanup, but the alert-history entry remains.

```powershell
# Guard status and invalid-zone checks (safe default)
.\run-guard.ps1 -Port COM4

# Guard zone boundary check (temporarily changes zone, restores its initial value)
.\run-guard.ps1 -Port COM4 -Persistent

# Alert launcher asks whether to clear history before starting the pack.
# Answer y to review the list and receive a final approval prompt before cleanup,
# or n to keep history unchanged and continue without clearing.
.\run-alert.ps1 -Port COM4 -Persistent

# Explicit cleanup-only mode remains available when cleanup is intentionally run by itself.
.\run-alert.ps1 -Port COM4 -ClearHistory

# Include non-persistent and interactive Alert cases; still asks before cleanup.
.\run-alert.ps1 -Port COM4 -All
```

#### Understanding `selected`, `deselected`, and `skipped`

Pytest's `deselected` count means tests were collected but excluded by the launcher's marker
selector; they did not execute. It is not the same as `skipped`, where a selected test starts and
then reports that it cannot or should not proceed. The launcher excludes the destructive
`alert_cleanup` case from the main selection; when the operator answers `y`, it runs that case
separately before the selected Alert tests.

For the 2026-10-20 00:44–00:46 Alert run, pytest collected 21 cases: 10 hardware Alert cases were
selected and 11 were deselected. Those 11 were the 10 offline parser/cleanup unit-test cases in
`tests/test_alert.py` (they do not carry the `alert` marker) plus the one interactive
`alert_cleanup` case. The launcher excluded cleanup from that run's selected pack because it
acknowledges all alerts and erases the entire history. The current launcher asks the operator at
startup and runs the cleanup case separately only after approval. The 10 selected cases produced
8 passes and 2 failures; deselected cases did not contribute to that result.

To run only the offline Alert parser/cleanup checks without accessing hardware:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "not interactive and not persistent" tests\test_alert.py
```

The count can change when tests are added or parameterization changes. Use the pytest summary and
marker selection, rather than treating a non-zero `deselected` count as test failures.

The `alert clear` guard test creates its own pending alert and verifies that `alert clear`
returns E855 without clearing history. It does not acknowledge or clear pre-existing alerts;
cleanup targets only the alert created by that test. It can therefore run when older alerts are
pending. On the 2026-10-20 00:44–00:46 run on device-reported firmware 2.3.0, numeric
`alert ack <id>` was confirmed to acknowledge the preceding displayed ID instead of the requested
one (BUG-016); the latest-ACK command without an ID passed and was used for safe test cleanup.
The exact-ID check is a strict expected failure for confirmed BUG-016; it continues to assert the
AL-3 contract without compensating for the firmware defect. The duplicate-ACK diagnostic creates
three consecutive test alerts. It uses the displayed target ID on fixed behavior, or a one-ID-higher
selector only after readback confirms the known N-to-N−1 behavior, then checks W852 and verifies
that the repeated ACK changes no alert state. This selector shift diagnoses duplicate-ACK behavior;
it is not a workaround for the exact-ID requirement. If other alerts interrupt the generated
sequence, the diagnostic is skipped. Test cleanup uses `alert ack` without an ID only when the
latest pending alert belongs to the test; it verifies that generated alerts were acknowledged and
existing entries were preserved.

For normal Alert test-pack runs, the operator is first asked whether to clear history before the
selected Alert tests. Answering `n` (the default) leaves history untouched. Answering `y` starts
the cleanup check, which displays the current list and requires a second, explicit approval after
review; if approved, it acknowledges **all** pending alerts (including sonar/Guard alerts), then
deletes the **entire** Alert Center history and verifies that the list is empty. If final approval
is declined, history remains unchanged and the selected Alert tests continue. The cleanup-only
`-ClearHistory` option remains available, but is not needed for a normal Alert run; it reports a
non-zero exit when cleanup is skipped or otherwise not completed. Do not approve cleanup if any
pending alert or history entry must be preserved. Full-history cleanup is never run by distance,
lamp, or other non-Alert launchers; those tests check/clean only their own alerts.

Guard arming/disarming and panic tests require `HW17_GUARD_PIN` in the local environment; the PIN
is redacted from UART and Allure evidence. Configure it locally without sharing it in chat or
committing it. These tests also require `-s`, an unobstructed sensor path for arming, and operator
observation of the relay/LED:
```powershell
.\run-guard.ps1 -Port COM4 -Interactive
.\run-alert.ps1 -Port COM4 -Interactive

# Run one interactive Guard case by name, such as physical K4-hold PANIC.
.\run-guard.ps1 -Port COM4 -Interactive -TestName "test_k4_hold_triggers_panic_alarm"
```

Both launchers default to firmware 2.3.0 and safely exclude interactive and persistent tests.
Use `-Persistent` to opt into persistent but non-interactive cases, `-Interactive` to run
operator-interaction cases (including persistent effects), or `-All` to include every case in the
area. All modes capture live DEBUG output, JUnit results, and per-test UART transcripts under the
matching `logs\automated\guard\<firmware>` or `logs\automated\alert\<firmware>` folder.
`-TestName` filters to a pytest name substring; `-Markers` can supply a custom pytest marker
expression.

The Guard panic and critical-alert tests raise an alarm, open the relay, change NORMAL to VERBOSE,
then attempt cleanup to disarm/acknowledge and restore the relay/system state. Relay cycles and
alert-history entries are persistent. Inspect device state and bench preconditions before running
them.

### 5. Retest 2.1.0 xfail regressions on 2.3.0

The known-defect checks are version-aware: on 2.1.0 they xfail only for the documented symptom;
on 2.3.0 they require the PRD behavior normally. Run this focused set on a device-confirmed 2.3.0
image to verify the fixes. It includes persistent relay actuation and an interactive GPIO4 check:
```powershell
python -m pytest -c pytest.ini -s -o addopts='' --port COM4 --expected-fw-version 2.3.0 `
  tests/test_lamp.py::TestLamp::test_lamp_timer_unit_text `
  tests/test_distance.py::TestDistance::test_distance_averaging_max_boundary_20 `
  tests/test_distance.py::TestDistance::test_distance_stream_and_stop `
  tests/test_relay.py::TestRelay::test_relay_commands_and_cycle_count `
  tests/test_relay.py::TestRelay::test_relay_pulse_rejects_out_of_range_duration `
  tests/test_relay.py::TestRelay::test_relay_gpio4_indicator
```
These are test procedures, not execution results. Hardware tests must be run explicitly on the
indicated firmware, and their outcomes recorded separately in [REPORT.md](REPORT.md).

### 6. Run Persistent-State Tests

Explicitly selected persistent tests can change NVS and device settings:

- `test_lamp_scenes` overwrites scene 1. It restores the current lamp output but cannot recover the
  previous contents of scene 1.
- `test_lamp_persistence_after_reboot` overwrites scene 2 and temporarily sets the lamp to purple,
  75% brightness, and breathe mode before loading that scene. After a successful reboot and
  authenticated-session recovery, the `lamp_state` fixture restores the pre-test lamp settings and
  power state. If recovery is not confirmed, teardown does not send device commands; the previous
  scene 2 contents cannot be restored.
- `test_wifi_connect_success` saves the supplied Wi-Fi profile.
- `test_distance_persistence_after_reboot` sets the proximity alarm to 45 cm and filter on, then
  disables the alarm and restores the filter's initial enabled/disabled state. The prior numeric
  alarm threshold cannot be read back or restored by the current firmware interface.

Confirm these changes are acceptable before using persistent-suite options.

```powershell
.\run-lamp.ps1 -Port COM4 -Fw 2.1.0 -Persistent
.\run-wifi.ps1 -Port COM4 -Fw 2.1.0 -Persistent
.\run-distance.ps1 -Port COM4 -Fw 2.1.0 -Persistent
```

Relay tests actuate the valve and increment the persistent relay cycle counter. The K2 button test
also actuates the valve and increments the counter; it restores the initial relay state when
possible. Review the bench preconditions and persistent effects before explicitly running these
tests; relay checks are excluded from the default suite. With DEBUG UART capture enabled, relay
transcripts are saved under `logs/automated/relay/<firmware>/`. The non-interactive relay checks are:
```powershell
python -m pytest -c pytest.ini -m "relay and persistent and not interactive" --port COM4 --expected-fw-version 2.1.0 tests/test_relay.py
```

The GPIO4 indicator and RL-5 threshold-crossing checks are interactive and require uncaptured
console input (`-s`). RL-5 sets the alarm threshold to 30 cm, drives the relay, disables the alarm
afterward, and cannot restore a previous numeric threshold:
```powershell
python -m pytest -c pytest.ini -s -m "relay and persistent and interactive" --port COM4 --expected-fw-version 2.1.0 tests/test_relay.py
```

## Known Firmware Defects Tracked in Tests

| Bug ID | Description | Test Handling |
|---|---|---|
| **BUG-002** | `state 4` accepted from DEBUG | Tested in `test_button_pair_k4_k1_rejected_from_normal` (button path returns E302) |
| **BUG-003** | `lamp timer` start message reports `ms` instead of `s` | `test_lamp_timer_unit_text` marks xfail only on 2.1.0; the timer expiration is tested separately |
| **BUG-004** | Relay cycle counter increments twice per actual state transition | `test_relay_commands_and_cycle_count` marks xfail on 2.1.0 |
| **BUG-005** | GPIO4 relay indicator appears inverted | `test_relay_gpio4_indicator` marks xfail on 2.1.0 only when both observed states are inverted |
| **BUG-006** | Relay accepts a 99 ms pulse below the documented 100 ms minimum | `test_relay_pulse_rejects_out_of_range_duration` marks xfail on 2.1.0 |
| **BUG-008** | `distance 20` rejects maximum valid DS-1 sample count | `test_distance_averaging_max_boundary_20` marks xfail on 2.1.0 for E704 |
| **BUG-009** | `distance stop` omits documented W710 response code | `test_distance_stream_and_stop` marks xfail on 2.1.0 for missing W710 |
