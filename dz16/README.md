# HW-16 Wi-Fi, lamp, and OTA test suite

The test suite is based on the DZ14 pytest/serial/Allure pattern. Each test is an independent pytest case, opens the ESP32 UART, verifies the reported firmware version (1.3.0, 1.4.0, or 1.5.0), and attaches its complete UART transcript to the Allure result. UART TX/RX lines are also emitted through Python logging at `DEBUG`.

Run setup, test, and report commands with `dz16` as the current directory. From the repository root, enter it first:

```powershell
Set-Location .\dz16
```

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Close any serial terminal using the ESP32 port before starting pytest. Most lamp tests do not use Wi-Fi; the interactive FR-W6 lamp LED check toggles the saved network connection without reading a password. Wi-Fi station tests that require explicit credentials read them only from process environment variables; passwords are not stored in the repository or included in UART/Allure evidence.

### Wi-Fi tests

Configure Wi-Fi once in the ignored local `config/wifi_secrets.py` (copy `config/wifi_secrets.example.py`), or override settings with environment variables. Resolution is consistent: local defaults, then `HW16_WIFI_*` / `TEST_WIFI_*`, then per-run `--wifi-ssid` / `--wifi-password` options. Credentials are not committed. The wrong password must be at least eight characters and differ from the effective valid password.

```powershell
$env:HW16_WIFI_SSID = "<test SSID>"          # or $env:TEST_WIFI_SSID
$env:HW16_WIFI_PASSWORD = "<test password>"  # or $env:TEST_WIFI_PASSWORD
$env:HW16_WIFI_WRONG_PASSWORD = "<different password of at least 8 characters>"
$env:HW16_WIFI_MISSING_SSID = "HW16-NONEXISTENT-NETWORK"
```

`config/wifi_config.py` remains a compatibility facade for modules expecting direct config imports. Credential defaults belong in `config/wifi_secrets.py`, not the compatibility facade.

The ordinary non-persistent Wi-Fi cases cover scan metadata (FR-W4), short and incorrect passwords, and a missing SSID (FR-W1). They can disconnect the board and leave it offline. The successful-connect, disconnect-after-connect, and saved-credentials-after-reboot cases are marked `persistent` because they can replace the Wi-Fi credentials saved in NVS.

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "wifi and not interactive and not persistent" --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG tests\test_wifi.py
```

Run the credential-saving/persistence checks only when overwriting saved Wi-Fi credentials is acceptable:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "wifi and persistent and not interactive" --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG tests\test_wifi.py
```

### OTA tests

All OTA tests are excluded by default. Some OTA cases reboot or replace firmware, and the OTA-6 retry test also interrupts and restores the test access point; select them individually only after confirming the target firmware, network, and state-changing effects. OTA implementation/collection does not itself represent a test result.

The OTA suite checks version/partition, channel metadata, no-op updates, downgrade blocking, the no-Wi-Fi rejection, and the demo server reboot. The two channel-update scenarios (1.3.0 to 1.4.0 and 1.4.0 beta to 1.5.0) reflash firmware. OTA-6 is an interactive 1.5.0 force-reflash/retry check:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m "ota and interactive" --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG "tests\test_ota.py::TestOta::test_interrupted_download_can_be_retried"
```

Run the complete, ordered firmware-cycle workflow from the `dz16` directory with:

```powershell
.\run-ota-chain.ps1 -Port COM4
```

The chain first reads the active firmware version over the selected UART port, displays the route, and asks for the exact confirmation `OTA-CHAIN`. The route depends on the detected starting firmware:

| Starting firmware | Ordered checks and transitions | Final firmware |
|---|---|---|
| 1.3.0 | 1.3.0 checks → 1.4.0 checks → 1.5.0 checks → downgrade to 1.4.0 → downgrade to 1.3.0 | 1.3.0 |
| 1.4.0 | 1.4.0 checks → 1.5.0 checks → downgrade to 1.4.0 → downgrade to 1.3.0 → 1.3.0 checks → upgrade to 1.4.0 | 1.4.0 |
| 1.5.0 | 1.5.0 checks → downgrade to 1.4.0 → 1.4.0 checks → downgrade to 1.3.0 → 1.3.0 checks → upgrade to 1.4.0 → upgrade to 1.5.0 | 1.5.0 |

Wi-Fi settings use one precedence order everywhere: local defaults in the ignored `config/wifi_secrets.py`, then `HW16_WIFI_*` / `TEST_WIFI_*` environment variables, then per-run pytest options `--wifi-ssid` and `--wifi-password`. To initialize local defaults, copy `config/wifi_secrets.example.py` to `config/wifi_secrets.py` and set the access point credentials there. This local file is ignored by Git. The same overrides are available in the wrappers, for example `.\run-ota-chain.ps1 -WifiSsid "<SSID>" -WifiPassword "<password>"` or `.\run-wifi.ps1 -WifiSsid "<SSID>" -WifiPassword "<password>"`; environment variables or the ignored local defaults are preferable for passwords because command-line values can be visible to local process-inspection tools and shell history. Do not put credentials in source, reports, or UART transcripts.

The OTA chain requires a usable Wi-Fi configuration because OTA to 1.5.0 can erase credentials saved on the device (BUG-07). A Wi-Fi fixture allows two connection attempts (the initial attempt plus one retry), polling status briefly after each attempt so a delayed IP assignment can complete before disconnecting; configured-credential failures are reported rather than skipped. The password is redacted from UART evidence. Keep the access point available except when the interactive test explicitly asks you to disable and restore it. Transient OTA DNS/connection failures during update or downgrade are retried up to three times with a short delay; persistent failures return a clear connectivity error promptly instead of consuming the entire OTA timeout. Other failures, including an interrupted image download, are not automatically retried. Before each phase, the script re-reads the firmware over UART and stops if it differs from the expected version. Firmware-check phases run all independent checks even if one fails, then run a separate Wi-Fi recovery check; the chain proceeds to the next firmware only if that connection check passes. Check failures remain recorded and make the completed chain exit nonzero, even if all firmware transitions finish. Transition phases still stop on failure. The chain rejects unexpected skipped tests; the known BUG-06 retry outcome is reported as XFAIL, and a recovery fixture reboots the device when the OTA driver reports `update already in progress` so the following independent checks and firmware transitions can continue with OTA state cleared. Resolve reported failures and manually confirm the board's actual firmware before restarting. The script does not initially flash firmware. Each chain invocation gets a unique run ID, which is appended to the phase label in UART log and JUnit filenames, preventing same-day reruns from overwriting evidence under `logs\automated\ota\<version>\`.

Do not run the whole OTA group as an ordinary one-process suite: firmware-changing cases alter the expected version while pytest is still running. For individual firmware-changing scenarios, select the relevant node ID from `tests\test_ota.py` and pass the source version with `--expected-fw-version`.

| Requirement | Implemented test coverage |
|---|---|
| FR-W1, FR-W2, FR-W4 | Wi-Fi scan/connect/negative-input/status checks; saved credentials after reboot |
| FR-W5, FR-W6 | Existing interactive K3 and LED indication checks |
| OTA-1–OTA-7, OTA-9, OTA-12 | Version/channel, update/no-op/downgrade, disconnected rejection, update self-check, interruption retry, and demo-server checks |
| FR-W3 / OTA-8 | Not yet verified as a complete post-OTA Wi-Fi, lamp-setting, and scene-persistence scenario |
| OTA-10, OTA-11 | No automated destructive rollback/corrupt-image test added; use the existing manual evidence and controlled bench procedure |

The cases above describe test availability only. Update `REPORT.md` from actual UART/physical execution evidence; do not treat collection or implementation as PASS.

## Lamp test API

Tests use high-level, Allure-stepped methods on `DeviceDriver`: `lamp_on()`, `lamp_off()`, `lamp_set_color(name_or_rgb)`, `lamp_set_brightness(percent)`, `lamp_set_mode(mode)`, `lamp_set_timer(seconds)`, `lamp_save_scene(index)`, `lamp_load_scene(index)`, and `lamp_status()`. Setters return the raw UART response so each test can assert the firmware's exact success or error message; `lamp_status()` returns the parsed JSON object. These methods deliberately do not validate values locally, allowing negative tests to verify firmware-side input validation.

The pytest `device_driver` fixture remains responsible for opening/closing the UART, version validation, per-test cleanup, and the UART transcript attachment. This keeps device actions and their Allure steps in the driver, while fixtures handle test lifecycle.

## Interactive physical checks

Interactive tests check behavior that UART state cannot prove: lamp on/off and Wi-Fi indication, visible named/custom colors, brightness, rejected-command effects, lamp animation, timer shutoff, and reboot state. The shared `prepare_observation` helper presents the action, expected observation, and duration as separate, spaced sections. The `manual_prepare` and `manual_check` prompts start in their own padded console blocks; headings use terminal colors, while recognized lamp/LED color names (including “Blue lamp”) and valid RGB triplets are preceded by a small color-matched indicator dot. Captured output and `NO_COLOR`/`TERM=dumb` environments remain plain text. The preparation prompt waits for Enter before proceeding and Allure records each phase. The shared Wi-Fi indicator helper selects dim green only for a valid connection and dim red otherwise. Tests read Wi-Fi status before naming the expected indicator. UART/status evidence remains separate from operator observation; manual results and optional comments are attached to the Allure test. Answer `y` for pass, `n` for fail, or `c` to add an observation and then enter `y` or `n` for the result.

Interactive, OTA, and persistent cases are excluded by default (`addopts` includes `-m "not interactive and not ota and not persistent"`), so ordinary and CI runs do not wait for input, initiate firmware updates, or overwrite saved device state. Interactive selection without `-s` fails during test setup, before the UART/device fixture opens the hardware; the `manual_check` fixture also guards its input use.

Run the manual visual checks on a bench with the target board attached:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m interactive --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli_level=DEBUG
```

### Interactive Wi-Fi/K3 checks

The K3 tests require saved Wi-Fi credentials and an active connection with a non-empty SSID and valid, non-zero IP. Run both together in their collected order: `test_k3_reconnects_saved_wifi` asks for two physical K3 presses (disconnect, then reconnect) and checks the reconnect event, IP, status, and the LED indicator selected from the current Wi-Fi status; `test_k3_disconnect_status_and_led` then checks a K3 disconnect, the reported disconnected status, and the corresponding indicator. Each test can also run individually, provided the board is connected before it starts. An autouse fixture in `TestWifiButtons` sends `reboot` if setup, the test call, or an expected failure (xfail) occurs; the serial cleanup then skips lamp commands so it does not send input to the rebooting device. Both tests are marked `xfail` with references to BUG-01/BUG-02 in `REPORT.md`: on an affected firmware they report XFAIL, and if a firmware fixes the bug they report XPASS (not a run failure), which is the signal to remove the marker and update the bug status. The disconnect test collects the status and the LED observation before asserting, so both are always reported.

Run both K3 checks with UART debug capture:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m "wifi and interactive" --port COM4 --expected-fw-version 1.4.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG tests\test_wifi.py::TestWifiButtons
```

Both tests are interactive and excluded from ordinary runs. Debug UART transcripts for Wi-Fi tests are saved under `logs\automated\wifi\<version>\`.

To select one check, append its pytest node ID, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m interactive --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli_level=DEBUG "tests\test_lamp.py::TestLamp::test_named_color_visual[red]"
```

For CI or an unattended run, explicitly keep the exclusion:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "not interactive and not ota and not persistent" --alluredir=allure-results
```

## Run one test at a time

Run a single case against the firmware currently on the board:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m lamp --port COM4 --expected-fw-version 1.3.0 --alluredir=allure-results -o log_cli_level=DEBUG tests\test_lamp.py::TestLamp::test_lamp_on_off_and_status
```

## Run tests with UART debug output

Run commands from the `dz16` directory. Set pytest's live logging level to `DEBUG` to print every UART TX/RX line in the terminal while tests run. The same test transcript is attached to the Allure result:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "lamp and not persistent and not interactive" --port COM4 --expected-fw-version 1.3.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG
```

When live logging is set to `DEBUG`, pytest also saves a separate UART transcript for each test under `logs\automated\<category>\<version>\`, where the category is `lamp`, `wifi`, or `ota`. Filenames are `YYYYMMDD-<test name>.txt`, the same date format as the `run-YYYYMMDD-*-summary.txt` files. For each test name and date the latest run is kept as `.txt` and the one before it as `.prev.txt`; older runs that day are overwritten. The full capture time is inside the file header. Normal `INFO` runs do not create these files.

To debug one test, append its node ID to the command, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m lamp --port COM4 --expected-fw-version 1.3.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG "tests\test_lamp.py::TestLamp::test_lamp_on_off_and_status"
```

For tests that prompt for a physical observation, also pass `-s` and select the `interactive` marker, as shown above. Do not add `--clean-alluredir` when accumulating results from separate one-test-at-a-time runs; generate the Allure report after the run sequence is complete.

Select one parameterized check by its pytest node ID, or run the non-persistent lamp group:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "lamp and not persistent" --port COM4 --expected-fw-version 1.3.0 --alluredir=allure-results -o log_cli_level=DEBUG
```

Use `--expected-fw-version 1.3.0` for the currently flashed baseline, or change it to `1.4.0`/`1.5.0` after updating the device. The test fixture reads `version` from the device and fails if it does not match the requested version. Rainbow and scenes are expected to be unsupported on 1.3.0 and 1.4.0, and supported on 1.5.0.

## Persistent scene check

The `device_driver` fixture snapshots `lamp status` when a test starts and restores color, brightness, mode, remaining timer, and on/off state during cleanup. OTA-marked cases skip lamp restoration so teardown cannot rewrite settings on newly flashed firmware or obscure post-OTA persistence behavior.

Tests marked `persistent` modify firmware or saved device data. The default pytest selection excludes these cases. Lamp tests may overwrite scenes 1–3 and lamp settings; successful Wi-Fi connection tests can overwrite the saved access-point credentials; OTA update tests may replace the installed firmware. Run only the selected persistent scenario when its effects are acceptable:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "lamp and persistent" --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli_level=DEBUG
```

The regular `lamp and not persistent` run excludes these tests. Invalid-scene checks are separately collected in the regular lamp group.

## Full run against a firmware version (clean run for analysis)

Use this sequence when a full pass on one firmware should be analyzed afterwards (for example by Copilot) to update `REPORT.md`. All commands are run from `dz16`.

1. **Prepare the board.** Flash the target firmware, connect Wi-Fi with `connect` over UART (network and K3 checks need an active connection with SSID and IP), set the Wi-Fi environment variables above for the station tests, and close any other program using the COM port.

2. **Clean results of previous runs** so the analysis sees only the new run. This deletes the raw Allure results, the generated Allure report, and the per-test pytest UART logs of the version under test. The hand-written `run-*-summary.txt` files and the older root-level logs (`logs\*.txt`) are kept.

   ```powershell
   $version = "1.5.0"
   Remove-Item .\allure-results, .\allure-report -Recurse -Force -ErrorAction SilentlyContinue
   Remove-Item ".\logs\automated\lamp\$version\*" -Include "2*.txt" -ErrorAction SilentlyContinue
   Remove-Item ".\logs\automated\wifi\$version\*" -Include "2*.txt" -ErrorAction SilentlyContinue
   ```

   Do not clean between the steps below; clean only once, before the first step.

3. **Choose one run.**

   **Option A: interactive checks only** (lamp and Wi-Fi/K3) against 1.5.0 with UART debug capture. Answer each prompt with `y`/`n` (or `c` to add a comment first); press the physical K3 button when asked.

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m interactive --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG
   ```

   **Option B: full test suite** across all test categories via `run.ps1`:

   ```powershell
   .\run.ps1
   # Defaults to stable FW 1.4.0, excluding interactive & persistent checks.
   # For a full run with interactive prompts and persistent tests:
   .\run.ps1 -Interactive -Persistent
   # For beta FW 1.5.0:
   .\run.ps1 -Fw 1.5.0 -Interactive -Persistent
   ```

   You can also run category-focused scripts:
   - Lamp tests: `.\run-lamp.ps1` (or `.\run-lamp.ps1 -Fw 1.4.0 -Interactive -Persistent`)
   - Wi-Fi tests: `.\run-wifi.ps1` (or `.\run-wifi.ps1 -Fw 1.4.0 -Interactive -Persistent`)
   - OTA tests: `.\run-ota.ps1 -TestName test_current_channel_is_not_reinstalled` (or `.\run-ota.ps1 -Fw 1.5.0 -TestName test_interrupted_download_can_be_retried -Interactive`)

   For manual pytest execution, pass the desired markers:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m "lamp or wifi" --port COM4 --expected-fw-version 1.4.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG
   ```

4. **Capture the run in files.** Add these options to the pytest command of step 3 (replace `YYYYMMDD` with the run date):

   ```powershell
   --log-file=.\logs\automated\lamp\1.5.0\run-YYYYMMDD-full.log --log-file-level=DEBUG --junitxml=.\logs\automated\lamp\1.5.0\run-YYYYMMDD-junit.xml -rA
   ```

   - `run-*-full.log` is the complete DEBUG log of the whole run in one file: every UART TX/RX line, test boundaries, and a `MANUAL CHECK | <question> | result=PASS/FAIL | comment=...` line for each of your answers. It is written by pytest itself, so it works with `-s` and interactive prompts (a `| Tee-Object` pipe does not record typed answers and can delay prompts).
   - `run-*-junit.xml` holds one entry per test with status (passed/failed/xfail/skipped), duration, and the failure message.
   - `-rA` makes the console end with one line per test; copy the final summary line into the report notes if you want it quoted.

   The per-test UART logs and `allure-results` are still produced as before.

5. **Hand over for analysis.** Tell Copilot only the version and the run date, for example: "Analyze the 1.5.0 run of 2026-10-12 and update `REPORT.md`." It reads `run-*-junit.xml` and `run-*-full.log` first, then only the per-test UART logs of failed or unexpected tests, and `allure-results` only when something is missing. Optionally generate the HTML report for yourself: `allure generate .\allure-results --clean -o .\allure-report`.

After a failed or interrupted run, reboot the board and reconnect Wi-Fi before repeating a step.

## Allure report

Pytest writes raw Allure result data (JSON and attachments) to `dz16\allure-results`; that directory is not itself the browsable report. To create a persistent HTML report after running tests:

```powershell
allure generate .\allure-results --clean -o .\allure-report
allure open .\allure-report
```

The generated report is saved in `dz16\allure-report`. To serve a temporary report without keeping the generated HTML directory:

```powershell
allure serve .\allure-results
```

UART operations appear as named Allure steps (open/close, command TX, waits, and parsing); command responses, the complete per-test UART transcript, and manual observations are attached to the result. When running individual tests one by one, keep the existing `allure-results` directory between runs; generate the report after all desired tests finish.

The Wi-Fi, lamp, and OTA tests share the `DeviceDriver` connection API, including `wifi_connect_saved()` for a credentials-free reconnect from NVS. The lamp visual scenario explicitly disconnects to check the red Wi-Fi indication, then reconnects to check green; OTA preconditions use the same saved-network operation. The automated tests verify UART responses and reported JSON state. Physical LED color and brightness must still be checked visually and recorded in `REPORT.md`; automation cannot observe the LED.
