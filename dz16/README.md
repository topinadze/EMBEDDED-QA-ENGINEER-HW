# HW-16 automated lamp verification

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

Close any serial terminal using the ESP32 port before starting pytest. Lamp tests do not connect to Wi-Fi or read Wi-Fi credentials. The interactive K3 checks use the device's already-saved Wi-Fi credentials and never ask for or log the password.

## Lamp test API

Tests use high-level, Allure-stepped methods on `DeviceDriver`: `lamp_on()`, `lamp_off()`, `lamp_set_color(name_or_rgb)`, `lamp_set_brightness(percent)`, `lamp_set_mode(mode)`, `lamp_set_timer(seconds)`, `lamp_save_scene(index)`, `lamp_load_scene(index)`, and `lamp_status()`. Setters return the raw UART response so each test can assert the firmware's exact success or error message; `lamp_status()` returns the parsed JSON object. These methods deliberately do not validate values locally, allowing negative tests to verify firmware-side input validation.

The pytest `device_driver` fixture remains responsible for opening/closing the UART, version validation, per-test cleanup, and the UART transcript attachment. This keeps device actions and their Allure steps in the driver, while fixtures handle test lifecycle.

## Interactive physical checks

Interactive tests check behavior that UART state cannot prove: lamp on/off and Wi-Fi indication, visible named/custom colors, brightness, rejected-command effects, lamp animation, timer shutoff, and reboot state. The tests set the expected state through `DeviceDriver`, capture UART/status evidence, then pause for an observation. The result and optional comment are attached to the Allure test. Answer `y` for pass, `n` for fail, or `c` to add an observation and then enter `y` or `n` for the result.

Interactive cases are excluded by default (`addopts` includes `-m "not interactive"`), so ordinary and CI runs do not wait for input. Interactive selection without `-s` fails during test setup, before the UART/device fixture opens the hardware; the `manual_check` fixture also guards its input use.

Run the manual visual checks on a bench with the target board attached:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m interactive --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli_level=DEBUG
```

### Interactive Wi-Fi/K3 checks

The K3 tests require saved Wi-Fi credentials and an active connection with a non-empty SSID and valid, non-zero IP. Run both together in their collected order: `test_k3_reconnects_saved_wifi` asks for two physical K3 presses (disconnect, then reconnect) and checks the reconnect event, IP, status, and dim-green indicator; `test_k3_disconnect_status_and_led` then checks a K3 disconnect, the reported disconnected status, and the dim-red indicator. Each test can also run individually, provided the board is connected before it starts. An autouse fixture in `TestWifiButtons` sends `reboot` if setup or the test call fails; the serial cleanup then skips lamp commands so it does not send input to the rebooting device.

Run both K3 checks with UART debug capture:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m "wifi and interactive" --port COM4 --expected-fw-version 1.4.0 --alluredir=allure-results -o log_cli=true -o log_cli_level=DEBUG tests\test_wifi.py::TestWifiButtons
```

Both tests are interactive and excluded from ordinary runs. Debug UART transcripts are saved with the other lamp-suite logs under `logs\automated\lamp\<version>\`.

To select one check, append its pytest node ID, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m interactive --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli_level=DEBUG "tests\test_lamp.py::TestLamp::test_named_color_visual[red-expected_rgb0]"
```

For CI or an unattended run, explicitly keep the exclusion:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "not interactive" --alluredir=allure-results
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

When live logging is set to `DEBUG`, pytest also saves a separate UART transcript for each test under `logs\automated\lamp\<version>\`. Filenames include the test name and capture timestamp, so repeated runs do not overwrite earlier logs. Normal `INFO` runs do not create these files.

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

Tests marked `persistent` modify saved device data. `test_scenes_by_version` writes test values to each of scenes 1–3 on firmware 1.5.0 and overwrites any existing data in those slots. `test_settings_survive_reboot` writes its test color, brightness, and mode to NVS. Run these only when those changes are acceptable:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini -m "lamp and persistent" --port COM4 --expected-fw-version 1.5.0 --alluredir=allure-results -o log_cli_level=DEBUG
```

The regular `lamp and not persistent` run excludes these tests. Invalid-scene checks are separately collected in the regular lamp group.

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

The automated tests verify UART responses and reported JSON state. Physical LED color and brightness must still be checked visually and recorded in `REPORT.md`; automation cannot observe the LED.
