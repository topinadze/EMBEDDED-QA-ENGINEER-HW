from __future__ import annotations

from collections.abc import Callable
import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation, wifi_indicator_color


def _response_text(lines: list[str]) -> str:
    return "\n".join(lines)


def _assert_response(lines: list[str], expected: str) -> None:
    output = _response_text(lines)
    assert expected.casefold() in output.casefold(), (
        f"Expected {expected!r} in UART response:\n{output}"
    )


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("System Diagnostics & Peripherals")
@pytest.mark.system
class TestSystem:
    @allure.story("Section 6: CLI Help")
    @allure.title("help lists all system, Wi-Fi, OTA, lamp, and button commands")
    @pytest.mark.smoke
    @pytest.mark.positive
    def test_help_command(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Request help menu via UART"):
            lines = device_driver.send_command("help", timeout=1.0)
            output = _response_text(lines)

        with allure.step("Verify major command categories and entries in help output"):
            expected_entries = (
                "connect",
                "disconnect",
                "status",
                "scan",
                "distance",
                "relay on",
                "relay off",
                "led on",
                "led off",
                "led auto",
                "led rgb",
                "version",
                "ota check",
                "ota update",
                "sysinfo",
                "temp",
                "sensor status",
                "reboot",
                "Smart Lamp:",
                "Buttons:",
            )
            for entry in expected_entries:
                assert entry.casefold() in output.casefold(), (
                    f"Help output missing command or section {entry!r}:\n{output}"
                )

    @allure.story("Section 6: Command Line Interface")
    @allure.title("Unknown command '{command}' is rejected with help pointer")
    @pytest.mark.parametrize("command", ("blabla", "foobar", "sensor invalid"))
    @pytest.mark.negative
    def test_unknown_command_rejected(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        command: str,
    ) -> None:
        with allure.step(f"Send unknown command '{command}'"):
            lines = device_driver.send_command(command)

        with allure.step("Verify standard unknown command error response"):
            _assert_response(
                lines, "unknown command, type 'help' for available commands"
            )

    @allure.story("Section 6: System Information")
    @allure.title("sysinfo outputs hardware, chip, heap, and uptime telemetry")
    @pytest.mark.smoke
    @pytest.mark.positive
    def test_sysinfo_reporting(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Send 'sysinfo' command"):
            lines = device_driver.sysinfo(timeout=1.0)
            output = _response_text(lines)

        with allure.step("Verify ESP32-S3 chip details and system metrics"):
            for keyword in ("ESP32-S3", "cores", "MHz", "Flash", "Free heap", "uptime"):
                assert keyword.casefold() in output.casefold(), (
                    f"sysinfo output missing keyword {keyword!r}:\n{output}"
                )

    @allure.story("Section 6: Temperature Telemetry")
    @allure.title("temp command reports valid ESP32 chip temperature")
    @pytest.mark.positive
    def test_chip_temperature(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Send 'temp' command"):
            lines = device_driver.temp(timeout=1.0)

        with allure.step("Verify reported temperature is within realistic operating bounds"):
            temp = DeviceDriver.parse_chip_temperature(lines)
            assert temp is not None, f"Could not parse chip temperature from: {lines!r}"
            assert 5.0 <= temp <= 90.0, (
                f"Reported temperature {temp} C is outside realistic operating range (5..90 C)"
            )

    @allure.story("Section 6: Sensor Status Telemetry")
    @allure.title("sensor status reports distance, relay, LED, Wi-Fi, and temperature")
    @pytest.mark.positive
    def test_sensor_status_reporting(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Send 'sensor status' command"):
            lines = device_driver.sensor_status(timeout=1.0)

        with allure.step("Verify parsed sensor status contains all fields"):
            status = DeviceDriver.parse_sensor_status(lines)
            assert status["relay"] in ("ON", "OFF"), (
                f"Relay state missing or unexpected: {status['relay']!r}"
            )
            assert status["wifi"] in ("connected", "disconnected"), (
                f"WiFi state missing or unexpected: {status['wifi']!r}"
            )
            assert status["led"] is not None, "LED state missing from sensor status"
            assert status["temperature"] is not None, "Temperature missing from sensor status"
            assert 5.0 <= status["temperature"] <= 90.0, (
                f"Temperature {status['temperature']} C is outside realistic bounds"
            )

    @allure.story("Section 6: Relay Control")
    @allure.title("relay on and relay off toggle relay state and update sensor status")
    @pytest.mark.positive
    def test_relay_control(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        try:
            with allure.step("Turn relay ON"):
                lines_on = device_driver.relay_on()
                _assert_response(lines_on, "relay ON")

            with allure.step("Verify sensor status confirms Relay: ON"):
                status_on = DeviceDriver.parse_sensor_status(device_driver.sensor_status())
                assert status_on["relay"] == "ON", f"Expected Relay ON, got: {status_on['relay']}"

            with allure.step("Turn relay OFF"):
                lines_off = device_driver.relay_off()
                _assert_response(lines_off, "relay OFF")

            with allure.step("Verify sensor status confirms Relay: OFF"):
                status_off = DeviceDriver.parse_sensor_status(device_driver.sensor_status())
                assert status_off["relay"] == "OFF", f"Expected Relay OFF, got: {status_off['relay']}"
        finally:
            with allure.step("Cleanup: Ensure relay is turned OFF"):
                device_driver.relay_off()

    @allure.story("Section 6 / FR-W6: LED Modes")
    @allure.title("led on, led off, and led auto control white LED and restore Wi-Fi auto mode")
    @pytest.mark.positive
    def test_led_control(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        try:
            with allure.step("Turn LED ON (manual white)"):
                lines_on = device_driver.led_on()
                _assert_response(lines_on, "LED ON")

            with allure.step("Turn LED OFF"):
                lines_off = device_driver.led_off()
                _assert_response(lines_off, "LED OFF")

            with allure.step("Restore LED to auto Wi-Fi indication mode"):
                lines_auto = device_driver.led_auto()
                _assert_response(lines_auto, "LED auto")

            with allure.step("Verify sensor status reports auto mode"):
                status = DeviceDriver.parse_sensor_status(device_driver.sensor_status())
                assert status["led"] is not None and "auto" in str(status["led"]).lower(), (
                    f"Expected LED in auto mode, got: {status['led']!r}"
                )
        finally:
            with allure.step("Cleanup: Restore LED to auto mode"):
                device_driver.led_auto()

    @allure.story("Section 6: LED RGB Cycle")
    @allure.title("led rgb executes 5-second color cycle and completes with done")
    @pytest.mark.positive
    def test_led_rgb_cycle(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Trigger 'led rgb' command"):
            lines = device_driver.send_command("led rgb", timeout=0.5)
            _assert_response(lines, "RGB cycle 5s")

        with allure.step("Wait for RGB cycle completion"):
            completed = device_driver.wait_for("RGB done", timeout=7.0)
            assert completed, "UART did not log 'RGB done' within 7 seconds."

    @allure.story("Section 6: Ultrasonic Distance Sensor")
    @allure.title("distance <N> performs timed distance measurements and reports done")
    @pytest.mark.positive
    def test_distance_timed_measurement(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Send 'distance 2' command for 2-second measurement"):
            lines = device_driver.send_command("distance 2", timeout=0.5)
            _assert_response(lines, "measuring for 2 seconds")

        with allure.step("Wait for distance measurements and completion marker"):
            completed = device_driver.wait_for("done", timeout=4.0)
            assert completed, "Distance measurement did not report 'done' within 4 seconds."

    @allure.story("Section 6: Device Reboot")
    @allure.title("reboot command counts down 3-2-1 and reboots device")
    @pytest.mark.persistent
    def test_reboot_command(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        with allure.step("Send reboot command and wait for boot completion"):
            rebooted = device_driver.reboot(timeout=30.0)
            assert rebooted, "Device did not successfully reboot within 30 seconds."

        with allure.step("Verify device responds to status after reboot"):
            status = device_driver.lamp_status()
            assert status["lamp"] == "off", "Lamp must be off after reboot (FR-L1)."


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("Physical Peripherals & Sensors")
@pytest.mark.system
@pytest.mark.interactive
class TestSystemInteractive:
    @allure.story("Section 6: Continuous Distance Measurement")
    @allure.title("Continuous distance measurement streams data until Enter is pressed")
    def test_distance_continuous_interactive(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="place an obstacle in front of the HC-SR04 sensor and move it 5-35 cm",
            expected="UART distance readings change as the obstacle moves",
            duration="8 seconds of streaming, then the test stops the stream",
        )
        with allure.step("Send 'distance' command to start continuous measurements"):
            device_driver.send_command("distance", timeout=0.1)

        with allure.step("Observe continuous distance readings for 8 seconds"):
            lines = device_driver.read_for(8.0)
            has_distance_stream = any(
                "distance:" in line.lower() or "timeout" in line.lower() for line in lines
            )
            soft.check(has_distance_stream, "Continuous distance stream received via UART")

        with allure.step("Send Enter to stop continuous measurement"):
            device_driver.stop_continuous_measurement()
            after_stop = device_driver.read_for(1.5)
            still_streaming = any("distance:" in line.lower() for line in after_stop)
            soft.check(not still_streaming, "Distance streaming stopped after Enter")

        with allure.step("Prompt operator to verify distance values changed with obstacle movement"):
            moving_reflected = manual_check(
                "Did distance values in console update continuously as you moved your hand/obstacle?"
            )
            soft.check(moving_reflected, "Distance values responded to physical obstacle movement")

        soft.assert_all()

    @allure.story("Section 6: Relay Physical Operation")
    @allure.title("Relay physically toggles ON and OFF with audible click")
    def test_relay_control_physical(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="watch and listen to the physical relay as the test switches it on then off",
            expected="an audible click and relay indicator LED change for both states",
            duration="about 5-10 seconds total",
        )
        try:
            with allure.step("Send 'relay on' and verify physical click"):
                device_driver.relay_on()
                clicked_on = manual_check(
                    "Did the relay audibly click and turn ON (indicator LED on relay active)?"
                )
                soft.check(clicked_on, "Relay ON confirmed physically")

            with allure.step("Send 'relay off' and verify physical click"):
                device_driver.relay_off()
                clicked_off = manual_check(
                    "Did the relay audibly click and turn OFF (indicator LED on relay off)?"
                )
                soft.check(clicked_off, "Relay OFF confirmed physically")

            soft.assert_all()
        finally:
            device_driver.relay_off()

    @allure.story("Section 6 / FR-W6: LED Physical Modes")
    @allure.title("LED physically switches between manual ON (white), OFF, and auto Wi-Fi mode")
    def test_led_control_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="observe the onboard LED as the test selects manual ON, manual OFF, and auto",
            expected="steady white, fully off, then Wi-Fi status indication",
            duration="about 5 seconds per state",
        )
        try:
            with allure.step("Send 'led on' and verify steady white illumination"):
                device_driver.led_on()
                white_lit = manual_check("Is the LED steadily illuminated white?")
                soft.check(white_lit, "LED is white in manual ON mode")

            with allure.step("Send 'led off' and verify LED turns off"):
                device_driver.led_off()
                is_off = manual_check("Is the LED completely turned off?")
                soft.check(is_off, "LED is OFF in manual OFF mode")

            with allure.step("Send 'led auto' and verify return to Wi-Fi indication"):
                wifi_status = device_driver.wifi_status()
                indicator_color = wifi_indicator_color(
                    DeviceDriver.wifi_connection_is_valid(wifi_status)
                )
                prepare_observation(
                    manual_prepare,
                    action="the test is about to select LED auto mode",
                    expected=f"the LED shows {indicator_color} for the current Wi-Fi status",
                    duration="about 5 seconds",
                )
                device_driver.led_auto()
                auto_mode = manual_check(
                    f"Has the LED returned to the expected {indicator_color} Wi-Fi indication?"
                )
                soft.check(auto_mode, "LED returned to Wi-Fi auto indication")

            soft.assert_all()
        finally:
            device_driver.led_auto()

    @allure.story("Section 6: LED RGB Visual Cycle")
    @allure.title("LED visibly cycles through RGB colors for 5 seconds")
    def test_led_rgb_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="watch the RGB LED while the test runs its color cycle",
            expected="a smooth transition across the rainbow spectrum",
            duration="5 seconds, followed by 'RGB done' in UART",
        )
        with allure.step("Trigger 'led rgb' command"):
            device_driver.send_command("led rgb", timeout=0.5)

        with allure.step("Wait for RGB cycle completion in UART"):
            completed = device_driver.wait_for("RGB done", timeout=7.0)
            soft.check(completed, "UART reported 'RGB done'")

        with allure.step("Verify visual observation of 5-second color cycle"):
            cycled = manual_check(
                "Did the RGB LED visibly cycle smoothly through colors for approximately 5 seconds?"
            )
            soft.check(cycled, "Smooth 5s RGB cycle visually confirmed")

        soft.assert_all()

    @allure.story("Section 6: Reboot Physical Countdown and Reset")
    @allure.title("Reboot visibly counts down 3-2-1 and resets the DevKit board")
    @pytest.mark.persistent
    def test_reboot_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="watch the board LEDs and console while the device reboots",
            expected="3-2-1 countdown, board LEDs flashing on restart, and 'ready' state",
            duration="about 5-10 seconds",
        )
        with allure.step("Send reboot command"):
            rebooted = device_driver.reboot(timeout=30.0)
            soft.check(rebooted, "Device rebooted and reported ready via UART")

        with allure.step("Verify physical reboot observation"):
            observed = manual_check(
                "Did you observe the 3-2-1 countdown and physical board restart (LEDs flashing on boot)?"
            )
            soft.check(observed, "Physical reboot and countdown observed")

        soft.assert_all()


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("Physical Buttons")
@pytest.mark.system
@pytest.mark.interactive
class TestSystemButtons:
    @allure.story("Section 6: Button K1 (GPIO41)")
    @allure.title("Button K1 triggers 10-second distance measurement")
    def test_button_k1_distance(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="press physical button K1 (GPIO41) once when prompted",
            expected="UART button event, 10-second distance stream, and '[K1] done'",
            duration="10 seconds",
        )
        mark = len(device_driver.uart_log)
        with allure.step("Prompt operator to press physical button K1"):
            confirmed = manual_check(
                "Press button K1 (GPIO41) on the DevKit board now, then confirm."
            )
            soft.check(confirmed, "Operator confirmed pressing K1")

        with allure.step("Verify UART reports button 1 press and starts distance measurement"):
            found = device_driver.wait_for_all(
                ["button 1 pressed (GPIO41)", "[K1] distance 10s"],
                timeout=5.0,
                since_index=mark,
            )
            soft.check(found["button 1 pressed (GPIO41)"], "UART reported 'button 1 pressed (GPIO41)'")
            soft.check(found["[K1] distance 10s"], "UART reported '[K1] distance 10s...'")

        with allure.step("Wait for 10-second measurement completion"):
            completed = device_driver.wait_for("[K1] done", timeout=14.0, since_index=mark)
            soft.check(completed, "UART reported '[K1] done' within 14 seconds")

        soft.assert_all()

    @allure.story("Section 6: Button K2 (GPIO40)")
    @allure.title("Button K2 toggles relay ON and OFF")
    def test_button_k2_relay_toggle(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="press physical button K2 (GPIO40) once when prompted",
            expected="an audible relay click, relay LED change, and UART '[K2] relay' event",
            duration="about 5 seconds",
        )
        try:
            mark = len(device_driver.uart_log)
            with allure.step("Prompt operator to press button K2 once"):
                confirmed = manual_check("Press button K2 (GPIO40) once now, then confirm.")
                soft.check(confirmed, "Operator confirmed pressing K2")

            with allure.step("Verify UART reports button 2 press and relay toggle"):
                found = device_driver.wait_for_all(
                    ["button 2 pressed (GPIO40)", "[K2] relay"],
                    timeout=5.0,
                    since_index=mark,
                )
                soft.check(found["button 2 pressed (GPIO40)"], "UART reported button 2 pressed (GPIO40)")
                soft.check(found["[K2] relay"], "UART reported [K2] relay toggle")

            with allure.step("Visual / acoustic check of relay click"):
                clicked = manual_check("Did the relay audibly click and change state?")
                soft.check(clicked, "Relay audibly clicked")

            soft.assert_all()
        finally:
            device_driver.relay_off()

    @allure.story("Section 6: Button K3 (GPIO39)")
    @allure.title("Button K3 triggers Wi-Fi disconnect / reconnect action")
    def test_button_k3_wifi_toggle(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="press physical button K3 (GPIO39) once when prompted",
            expected="UART button event and a Wi-Fi action beginning with '[K3] wifi'",
            duration="about 5-10 seconds",
        )
        mark = len(device_driver.uart_log)
        with allure.step("Prompt operator to press button K3 once"):
            confirmed = manual_check("Press button K3 (GPIO39) once now, then confirm.")
            soft.check(confirmed, "Operator confirmed pressing K3")

        with allure.step("Verify UART reports button 3 press and Wi-Fi action"):
            found = device_driver.wait_for_all(
                ["button 3 pressed (GPIO39)", "[K3] wifi"],
                timeout=5.0,
                since_index=mark,
            )
            soft.check(found["button 3 pressed (GPIO39)"], "UART reported button 3 pressed (GPIO39)")
            soft.check(found["[K3] wifi"], "UART reported [K3] wifi action")

        soft.assert_all()

    @allure.story("Section 6: Button K4 (GPIO38)")
    @allure.title("Button K4 toggles diode ON and OFF")
    def test_button_k4_diode_toggle(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        manual_check: Callable[[str], bool],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="press physical button K4 (GPIO38) once when prompted",
            expected="the discrete diode toggles and UART reports '[K4] diode'",
            duration="about 5 seconds",
        )
        mark = len(device_driver.uart_log)
        with allure.step("Prompt operator to press button K4 once"):
            confirmed = manual_check("Press button K4 (GPIO38) once now, then confirm.")
            soft.check(confirmed, "Operator confirmed pressing K4")

        with allure.step("Verify UART reports button 4 press and diode toggle"):
            found = device_driver.wait_for_all(
                ["button 4 pressed (GPIO38)", "[K4] diode"],
                timeout=5.0,
                since_index=mark,
            )
            soft.check(found["button 4 pressed (GPIO38)"], "UART reported button 4 pressed (GPIO38)")
            soft.check(found["[K4] diode"], "UART reported [K4] diode toggle")

        with allure.step("Visual check of diode"):
            diode_toggled = manual_check("Did the discrete diode (GPIO4) physically toggle state?")
            soft.check(diode_toggled, "Diode physically toggled")

        soft.assert_all()
