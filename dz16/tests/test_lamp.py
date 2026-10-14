from __future__ import annotations

from collections.abc import Callable

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation, wifi_indicator_color

NAMED_COLORS = (
    pytest.param("red", [255, 0, 0], id="red"),
    pytest.param("green", [0, 255, 0], id="green"),
    pytest.param("blue", [0, 0, 255], id="blue"),
    pytest.param("white", [255, 255, 255], id="white"),
    pytest.param("yellow", [255, 180, 0], id="yellow"),
    pytest.param("purple", [160, 0, 255], id="purple"),
    pytest.param("cyan", [0, 255, 255], id="cyan"),
)

INVALID_RGB_VALUES = (
    pytest.param((300, 0, 0), id="r300_g0_b0"),
    pytest.param((0, 0, 300), id="r0_g0_b300"),
    pytest.param((-1, -1, -1), id="r-1_g-1_b-1"),
    pytest.param((256, 0, 0), id="r256_g0_b0"),
)


def _response_text(lines: list[str]) -> str:
    return "\n".join(lines)


def _assert_response(lines: list[str], expected: str) -> None:
    output = _response_text(lines)
    assert expected.casefold() in output.casefold(), (
        f"Expected {expected!r} in UART response:\n{output}"
    )


def _has_response(lines: list[str], expected: str) -> bool:
    return expected.casefold() in _response_text(lines).casefold()


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("Smart Lamp")
@pytest.mark.lamp
class TestLamp:
    @allure.story("FR-L1: Lamp on/off")
    @allure.title("Lamp on and off update the reported state")
    @pytest.mark.smoke
    @pytest.mark.positive
    def test_lamp_on_off_and_status(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        _assert_response(device_driver.lamp_on(), "[LAMP] on")
        assert device_driver.lamp_status()["lamp"] == "on"

        _assert_response(device_driver.lamp_off(), "[LAMP] off")
        assert device_driver.lamp_status()["lamp"] == "off"

    @allure.story("FR-L8: Lamp status JSON")
    @allure.title("Lamp status contains all required JSON fields")
    def test_lamp_status_json_shape(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        status = device_driver.lamp_status()
        assert set(status) == {"lamp", "color", "brightness", "mode", "timer_s"}
        assert status["lamp"] in {"on", "off"}
        assert isinstance(status["color"], list) and len(status["color"]) == 3
        assert all(isinstance(channel, int) for channel in status["color"])
        assert isinstance(status["brightness"], int)
        assert isinstance(status["mode"], str)
        assert isinstance(status["timer_s"], int)

    @allure.story("FR-L1/FR-W6: Physical lamp and Wi-Fi indication")
    @allure.title("Lamp on/off switches the LED and restores Wi-Fi indication")
    @pytest.mark.interactive
    def test_lamp_on_off_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the test will turn the RGB lamp on, then off",
            expected="the RGB lamp is lit; after it turns off, check the Wi-Fi status LED",
            duration="about 5 seconds per observation",
        )
        on_response = device_driver.lamp_on()
        on_status = device_driver.lamp_status()
        on_visible = manual_check("Is the RGB LED visibly lit while the lamp is on?")
        soft.check(_has_response(on_response, "[LAMP] on"), "UART confirms lamp on")
        soft.check(on_status["lamp"] == "on", "Status reports lamp on")
        soft.check(on_visible, "LED is visibly lit while the lamp is on")

        off_response = device_driver.lamp_off()
        off_status = device_driver.lamp_status()
        wifi_status = device_driver.wifi_status()
        indicator_color = wifi_indicator_color(
            DeviceDriver.wifi_connection_is_valid(wifi_status)
        )
        prepare_observation(
            manual_prepare,
            action="the lamp has been turned off",
            expected=f"the status LED shows {indicator_color} for the reported Wi-Fi state",
            duration="about 5 seconds",
        )
        wifi_indicator_visible = manual_check(
            f"After lamp off, does the LED show the expected {indicator_color} "
            "Wi-Fi indication?"
        )
        soft.check(_has_response(off_response, "[LAMP] off"), "UART confirms lamp off")
        soft.check(off_status["lamp"] == "off", "Status reports lamp off")
        soft.check(wifi_indicator_visible, "LED returns to Wi-Fi indication")
        soft.assert_all()

    @allure.story("FR-L2/FR-L4: Named colors")
    @allure.title("Named color {color_name} sets its documented RGB value")
    @pytest.mark.parametrize("color_name,expected_rgb", NAMED_COLORS)
    @pytest.mark.positive
    def test_named_color_rgb(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        color_name: str,
        expected_rgb: list[int],
    ) -> None:
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_color(color_name),
            f"[LAMP] color set: {color_name}",
        )
        assert device_driver.lamp_status()["color"] == expected_rgb

    @allure.story("FR-L4: Physical named color")
    @allure.title("LED physically displays named color {color_name}")
    @pytest.mark.interactive
    @pytest.mark.parametrize("color_name,expected_rgb", NAMED_COLORS)
    def test_named_color_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
        color_name: str,
        expected_rgb: list[int],
    ) -> None:
        prepare_observation(
            manual_prepare,
            action=f"the lamp will be set to {color_name}",
            expected=f"the LED visibly shows {color_name}",
            duration="about 3 seconds",
        )
        device_driver.lamp_on()
        response = device_driver.lamp_set_color(color_name)
        status = device_driver.lamp_status()
        color_visible = manual_check(
            f"Look at the LED: does it visibly show {color_name}?"
        )
        soft.check(_has_response(response, f"[LAMP] color set: {color_name}"), "UART confirms color set")
        soft.check(status["color"] == expected_rgb, f"Status color is {expected_rgb}")
        soft.check(color_visible, f"Physical LED color matches {color_name}")
        soft.assert_all()

    @allure.story("FR-L3: Custom RGB")
    @allure.title("Custom RGB values are accepted and reported")
    @pytest.mark.positive
    def test_custom_rgb(self, device_driver: DeviceDriver, firmware_version: str) -> None:
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_color((255, 0, 128)),
            "[LAMP] color set: (255,0,128)",
        )
        assert device_driver.lamp_status()["color"] == [255, 0, 128]

    @allure.story("FR-L3/FR-L4: Physical custom RGB")
    @allure.title("LED physically displays custom RGB (255, 0, 128)")
    @pytest.mark.interactive
    def test_custom_rgb_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the lamp will be set to custom RGB (255, 0, 128)",
            expected="the LED shows a pink/magenta-like color",
            duration="about 3 seconds",
        )
        device_driver.lamp_on()
        response = device_driver.lamp_set_color((255, 0, 128))
        status = device_driver.lamp_status()
        color_visible = manual_check(
            "Does the LED visibly show the expected pink/magenta-like custom color "
            "for RGB (255, 0, 128)?"
        )
        soft.check(_has_response(response, "[LAMP] color set: (255,0,128)"), "UART confirms color set")
        soft.check(status["color"] == [255, 0, 128], "Status color is [255, 0, 128]")
        soft.check(color_visible, "Physical LED shows pink/magenta")
        soft.assert_all()

    @allure.story("FR-L3: RGB range validation")
    @allure.title("Out-of-range RGB {rgb} is rejected without changing the color")
    @pytest.mark.parametrize("rgb", INVALID_RGB_VALUES)
    @pytest.mark.negative
    def test_invalid_rgb_is_rejected(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        rgb: tuple[int, int, int],
    ) -> None:
        device_driver.lamp_set_color("green")
        response = device_driver.lamp_set_color(rgb)
        status = device_driver.lamp_status()
        _assert_response(response, "error: rgb values must be 0-255")
        assert status["color"] == [0, 255, 0]

    @allure.story("FR-L3: Physical invalid-RGB rejection")
    @allure.title("Invalid RGB {rgb} leaves the physical color unchanged")
    @pytest.mark.interactive
    @pytest.mark.parametrize("rgb", INVALID_RGB_VALUES)
    def test_invalid_rgb_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
        rgb: tuple[int, int, int],
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the lamp will be set to steady green as the baseline",
            expected="note the LED appearance; it should be unchanged after the invalid RGB is tested",
            duration="about 3 seconds per observation",
        )
        device_driver.lamp_on()
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_color("green")
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady green LED and confirm when ready to send an invalid RGB."
        )
        soft.check(baseline_status["color"] == [0, 255, 0], "Baseline status color is green")
        soft.check(baseline_visible, "Baseline LED is steady green")

        prepare_observation(
            manual_prepare,
            action=f"the test will send invalid RGB {rgb}",
            expected="the LED remains steady green",
            duration="about 3 seconds",
        )
        response = device_driver.lamp_set_color(rgb)
        status = device_driver.lamp_status()
        unchanged = manual_check(
            "After the invalid RGB was rejected, does the LED remain green?"
        )
        soft.check(_has_response(response, "error: rgb values must be 0-255"), "UART rejects invalid RGB")
        soft.check(status["color"] == [0, 255, 0], "Status color stays green")
        soft.check(unchanged, "LED remains green")
        soft.assert_all()

    @allure.story("FR-L2: Unknown named color")
    @allure.title("Unknown color is rejected without changing the color")
    @pytest.mark.negative
    def test_unknown_color_is_rejected(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_color("yellow")
        response = device_driver.lamp_set_color("orange")
        status = device_driver.lamp_status()
        _assert_response(response, "error: unknown color 'orange'")
        assert status["color"] == [255, 180, 0]

    @allure.story("FR-L2: Physical unknown-color rejection")
    @allure.title("Unknown color leaves the physical LED unchanged")
    @pytest.mark.interactive
    def test_unknown_color_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the lamp will be set to steady yellow as the baseline",
            expected="note the LED appearance; it should be unchanged after the unknown color is tested",
            duration="about 3 seconds per observation",
        )
        device_driver.lamp_on()
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_color("yellow")
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady yellow LED and confirm when ready to send an unknown color."
        )
        soft.check(baseline_status["color"] == [255, 180, 0], "Baseline status color is yellow")
        soft.check(baseline_visible, "Baseline LED is steady yellow")

        prepare_observation(
            manual_prepare,
            action="the test will request unknown color 'orange'",
            expected="the LED remains steady yellow",
            duration="about 3 seconds",
        )
        response = device_driver.lamp_set_color("orange")
        status = device_driver.lamp_status()
        unchanged = manual_check(
            "After 'orange' was rejected, does the LED remain yellow?"
        )
        soft.check(_has_response(response, "error: unknown color 'orange'"), "UART rejects unknown color")
        soft.check(status["color"] == [255, 180, 0], "Status color stays yellow")
        soft.check(unchanged, "LED remains yellow")
        soft.assert_all()

    @allure.story("FR-L5: Brightness")
    @allure.title("Brightness {brightness} is accepted and reported")
    @pytest.mark.parametrize("brightness", (0, 30, 50, 70, 100))
    @pytest.mark.positive
    def test_valid_brightness(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        brightness: int,
    ) -> None:
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_brightness(brightness),
            f"[LAMP] brightness set: {brightness}%",
        )
        assert device_driver.lamp_status()["brightness"] == brightness

    @allure.story("FR-L5: Physical brightness")
    @allure.title("LED brightness is visually appropriate at {brightness}%")
    @pytest.mark.interactive
    @pytest.mark.parametrize("brightness", (0, 30, 50, 70, 100))
    def test_brightness_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
        brightness: int,
    ) -> None:
        expected = (
            "off"
            if brightness == 0
            else f"steady white at the requested {brightness}% brightness"
        )
        prepare_observation(
            manual_prepare,
            action=f"the lamp will be set to {brightness}% brightness",
            expected=f"the LED appears {expected}",
            duration="about 3 seconds",
        )
        device_driver.lamp_on()
        device_driver.lamp_set_color("white")
        device_driver.lamp_set_mode("solid")
        response = device_driver.lamp_set_brightness(brightness)
        status = device_driver.lamp_status()
        instruction = (
            "Is the LED off at 0%?"
            if brightness == 0
            else f"Does the LED appear steadily lit at the requested {brightness}% brightness?"
        )
        physically_correct = manual_check(instruction)
        soft.check(_has_response(response, f"[LAMP] brightness set: {brightness}%"), "UART confirms brightness")
        soft.check(status["brightness"] == brightness, f"Status brightness is {brightness}")
        soft.check(physically_correct, f"Physical LED brightness is right at {brightness}%")
        soft.assert_all()

    @allure.story("FR-L5: Brightness range validation")
    @allure.title("Out-of-range brightness {brightness} is rejected without changing state")
    @pytest.mark.parametrize("brightness", (-5, 101, 150))
    @pytest.mark.negative
    def test_invalid_brightness_is_rejected(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        brightness: int,
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_color("white")
        device_driver.lamp_set_brightness(50)
        response = device_driver.lamp_set_brightness(brightness)
        status = device_driver.lamp_status()
        _assert_response(response, "error: brightness must be 0-100")
        assert status["brightness"] == 50
        assert status["color"] == [255, 255, 255]

    @allure.story("FR-L5: Physical invalid-brightness rejection")
    @allure.title("Invalid brightness {brightness} leaves the LED unchanged")
    @pytest.mark.interactive
    @pytest.mark.parametrize("brightness", (-5, 101, 150))
    def test_invalid_brightness_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
        brightness: int,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the lamp will be set to steady white at 50% brightness",
            expected="remember its appearance as baseline; it should remain unchanged after the invalid value",
            duration="about 3 seconds per observation",
        )
        device_driver.lamp_on()
        device_driver.lamp_set_color("white")
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_brightness(50)
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady white LED at 50% brightness and remember its "
            "appearance; confirm when ready to test the invalid value."
        )
        soft.check(baseline_status["brightness"] == 50, "Baseline status brightness is 50")
        soft.check(baseline_visible, "Baseline LED is steady white at 50%")

        prepare_observation(
            manual_prepare,
            action=f"the test will send invalid brightness {brightness}%",
            expected="the LED remains unchanged from the 50% white baseline",
            duration="about 3 seconds",
        )
        response = device_driver.lamp_set_brightness(brightness)
        status = device_driver.lamp_status()
        unchanged = manual_check(
            f"After brightness {brightness} was rejected, does the LED look "
            "unchanged from the 50% white baseline?"
        )
        soft.check(_has_response(response, "error: brightness must be 0-100"), "UART rejects invalid brightness")
        soft.check(status["brightness"] == 50, "Status brightness stays 50")
        soft.check(status["color"] == [255, 255, 255], "Status color stays white")
        soft.check(unchanged, f"LED unchanged after invalid brightness {brightness}")
        soft.assert_all()

    @allure.story("FR-L6: Lamp modes")
    @allure.title("Mode {mode} is accepted and reported")
    @pytest.mark.parametrize("mode", ("solid", "blink", "breathe"))
    @pytest.mark.positive
    def test_supported_modes(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        mode: str,
    ) -> None:
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_mode(mode),
            f"[LAMP] mode set: {mode}",
        )
        assert device_driver.lamp_status()["mode"] == mode

    @allure.story("FR-L6: Physical lamp modes")
    @allure.title("LED visibly follows the {mode} mode")
    @pytest.mark.interactive
    @pytest.mark.parametrize("mode", ("solid", "blink", "breathe", "rainbow"))
    def test_mode_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
        mode: str,
    ) -> None:
        if mode == "rainbow" and firmware_version != "1.5.0":
            pytest.skip(
                f"Rainbow mode is not implemented in firmware {firmware_version}."
            )

        expected_behavior = {
            "solid": "steady blue light",
            "blink": "blue light blinking at about 1 Hz (roughly 0.5 s on / 0.5 s off)",
            "breathe": "blue light smoothly pulsing with an approximately 3-second period",
            "rainbow": "a complete smooth color cycle through the rainbow in approximately 5 seconds",
        }[mode]
        device_driver.lamp_on()
        device_driver.lamp_set_color("blue")
        device_driver.lamp_set_brightness(50)
        device_driver.lamp_set_mode("solid")
        prepare_observation(
            manual_prepare,
            action=f"the LED mode will be switched to '{mode}'",
            expected=f"{expected_behavior} at 50% brightness",
            duration="up to 5 seconds",
        )
        response = device_driver.lamp_set_mode(mode)
        status = device_driver.lamp_status()

        visually_correct = manual_check(
            f"Observe long enough to check the timing. Does the LED visibly show "
            f"{expected_behavior} at 50% brightness?"
        )
        soft.check(_has_response(response, f"[LAMP] mode set: {mode}"), "UART confirms mode set")
        soft.check(status["mode"] == mode, f"Status mode is {mode}")
        soft.check(visually_correct, f"Physical LED behavior matches mode '{mode}'")
        soft.assert_all()

    @allure.story("FR-L6: Unknown lamp mode")
    @allure.title("Unknown mode is rejected")
    @pytest.mark.negative
    def test_unknown_mode_is_rejected(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        _assert_response(
            device_driver.lamp_set_mode("disco"),
            "error: unknown mode 'disco'",
        )

    @allure.story("FR-L6: Rainbow mode by firmware version")
    @allure.title("Rainbow mode follows the support level for firmware {firmware_version}")
    def test_rainbow_mode_by_version(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        response = device_driver.lamp_set_mode("rainbow")
        if firmware_version != "1.5.0":
            _assert_response(response, "error: mode 'rainbow' not implemented yet")
            return

        _assert_response(response, "[LAMP] mode set: rainbow")
        assert device_driver.lamp_status()["mode"] == "rainbow"

    @allure.story("FR-L7: Timer expiration")
    @allure.title("Timer switches the lamp off after its duration")
    @pytest.mark.positive
    def test_timer_auto_off(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_timer(10),
            "[LAMP] auto-off in 10 s",
        )
        assert device_driver.wait_for("timer expired, lamp off", timeout=12.0), (
            "Timer expiration was not logged within twelve seconds."
        )
        assert device_driver.lamp_status()["lamp"] == "off"

    @allure.story("FR-L7: Physical timer auto-off")
    @allure.title("Timer auto-off physically extinguishes the lamp")
    @pytest.mark.interactive
    def test_timer_auto_off_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_color("white")
        device_driver.lamp_set_mode("solid")
        wifi_status_before_timer = device_driver.wifi_status()
        expected_indicator_before_timer = wifi_indicator_color(
            DeviceDriver.wifi_connection_is_valid(wifi_status_before_timer)
        )
        prepare_observation(
            manual_prepare,
            action="a 5-second auto-off timer starts",
            expected=(
                "the steady white lamp turns off when the timer expires, leaving "
                f"the {expected_indicator_before_timer} Wi-Fi indication"
            ),
            duration="about 8 seconds",
        )
        timer_response = device_driver.lamp_set_timer(5)
        timer_expired = device_driver.wait_for("timer expired, lamp off", timeout=8.0)
        status = device_driver.lamp_status()
        wifi_status = device_driver.wifi_status()
        indicator_color = wifi_indicator_color(
            DeviceDriver.wifi_connection_is_valid(wifi_status)
        )
        prepare_observation(
            manual_prepare,
            action="the 5-second timer has expired and UART status has been checked",
            expected=f"the lamp is off and the LED shows {indicator_color}",
            duration="about 5 seconds",
        )
        visually_off = manual_check(
            "After the 5-second timer expired, did the lamp light turn off and "
            f"the LED return to the expected {indicator_color} Wi-Fi indication?"
        )
        soft.check(_has_response(timer_response, "[LAMP] auto-off in 5 s"), "UART confirms timer armed")
        soft.check(timer_expired, "Timer expiration was logged within eight seconds")
        soft.check(status["lamp"] == "off", "Status reports lamp off after expiry")
        soft.check(visually_off, "Lamp physically off with Wi-Fi indication")
        soft.assert_all()

    @allure.story("FR-L7: Timer cancellation and status")
    @allure.title("Timer cancellation clears the remaining time")
    @pytest.mark.positive
    def test_timer_cancel_and_remaining_time(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_timer(30),
            "[LAMP] auto-off in 30 s",
        )
        assert device_driver.lamp_status()["timer_s"] > 0
        _assert_response(
            device_driver.lamp_set_timer(0),
            "[LAMP] timer cancelled",
        )
        assert device_driver.lamp_status()["timer_s"] == 0

    @allure.story("FR-L7: Timer input validation")
    @allure.title("Timer rejects invalid values and use while lamp is off")
    @pytest.mark.negative
    def test_timer_validation(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        device_driver.lamp_off()
        _assert_response(
            device_driver.lamp_set_timer(10),
            "error: lamp is off",
        )
        device_driver.lamp_on()
        _assert_response(
            device_driver.lamp_set_timer(5000),
            "error: timer must be 1-3600 s (0 = cancel)",
        )

    @allure.story("FR-L7: Physical timer rejection when lamp is off")
    @allure.title("Setting timer while lamp is off leaves the lamp physically off")
    @pytest.mark.interactive
    def test_timer_when_lamp_off_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the lamp will be turned off before attempting to set a timer",
            expected="the lamp remains off; only Wi-Fi status indication should be visible",
            duration="about 3 seconds per observation",
        )
        device_driver.lamp_off()
        status_before = device_driver.lamp_status()
        wifi_status = device_driver.wifi_status()
        indicator_color = wifi_indicator_color(
            DeviceDriver.wifi_connection_is_valid(wifi_status)
        )
        prepare_observation(
            manual_prepare,
            action="the lamp is off and the Wi-Fi status has been checked",
            expected=f"the LED shows {indicator_color}",
            duration="about 3 seconds",
        )
        lamp_is_off = manual_check(
            f"Is the lamp light off, with only the expected {indicator_color} "
            "Wi-Fi indication visible?"
        )
        soft.check(status_before["lamp"] == "off", "Status confirms lamp is off")
        soft.check(lamp_is_off, "Lamp physically off")

        prepare_observation(
            manual_prepare,
            action="the test will attempt 'lamp timer 5' while the lamp is off",
            expected="the command is rejected and the lamp light remains off",
            duration="about 3 seconds",
        )
        response = device_driver.lamp_set_timer(5)
        status_after = device_driver.lamp_status()
        remains_off = manual_check(
            f"After 'lamp timer 5', does the lamp remain off with only the "
            f"{indicator_color} Wi-Fi indication visible?"
        )
        soft.check(_has_response(response, "error: lamp is off"), "UART returns error: lamp is off")
        soft.check(status_after["lamp"] == "off", "Status lamp remains off")
        soft.check(status_after["timer_s"] == 0, "No timer armed")
        soft.check(remains_off, "Lamp physically remains off")
        soft.assert_all()

    @allure.story("FR-L10: Scenes")
    @allure.title("Scene {scene} save/load follows the support level of {firmware_version}")
    @pytest.mark.parametrize("scene", (1, 2, 3))
    @pytest.mark.persistent
    def test_scenes_by_version(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        scene: int,
    ) -> None:
        if firmware_version != "1.5.0":
            _assert_response(
                device_driver.lamp_save_scene(scene),
                "error: scenes not implemented yet",
            )
            _assert_response(
                device_driver.lamp_load_scene(scene),
                "error: scenes not implemented yet",
            )
            return

        device_driver.lamp_on()
        device_driver.lamp_set_color((17, 34, 51))
        device_driver.lamp_set_brightness(37)
        device_driver.lamp_set_mode("solid")
        _assert_response(
            device_driver.lamp_save_scene(scene),
            f"[LAMP] scene {scene} saved",
        )
        device_driver.lamp_set_color((90, 80, 70))
        device_driver.lamp_set_brightness(24)
        device_driver.lamp_set_mode("breathe")
        _assert_response(
            device_driver.lamp_load_scene(scene),
            f"[LAMP] scene {scene} loaded",
        )
        status = device_driver.lamp_status()
        assert status["color"] == [17, 34, 51]
        assert status["brightness"] == 37
        assert status["mode"] == "solid"

    @allure.story("FR-L10: Scene input validation")
    @allure.title("Scene indexes outside 1-3 are rejected")
    @pytest.mark.parametrize("command", ("lamp scene save 7", "lamp scene load 7"))
    @pytest.mark.negative
    def test_invalid_scene_index(
        self, device_driver: DeviceDriver, firmware_version: str, command: str
    ) -> None:
        if firmware_version != "1.5.0":
            pytest.skip(
                f"Scenes are not implemented in firmware {firmware_version}."
            )
        _assert_response(
            device_driver.send_command(command),
            "error: scene must be 1-3",
        )

    @allure.story("FR-L10: Empty scene loading")
    @allure.title("Loading an empty scene is rejected or reports scene is not implemented")
    @pytest.mark.negative
    def test_empty_scene_load_is_rejected(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        response = device_driver.lamp_load_scene(2)
        if firmware_version != "1.5.0":
            _assert_response(response, "error: scenes not implemented yet")
            return

        output = _response_text(response)
        assert any(
            marker.casefold() in output.casefold()
            for marker in ("error: scene 2 is empty", "[LAMP] scene 2 loaded")
        ), f"Unexpected response to scene load 2: {output}"

    @allure.story("FR-L10: Physical empty scene load rejection")
    @allure.title("Loading an empty scene leaves the physical lamp state unchanged")
    @pytest.mark.interactive
    def test_empty_scene_load_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        if firmware_version != "1.5.0":
            pytest.skip(
                f"Scenes are not implemented in firmware {firmware_version}."
            )
        prepare_observation(
            manual_prepare,
            action="the lamp will be set to steady cyan at 60% brightness",
            expected="note the LED appearance; it should remain unchanged when empty scene 2 is loaded",
            duration="about 3 seconds per observation",
        )
        device_driver.lamp_on()
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_color("cyan")
        device_driver.lamp_set_brightness(60)
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady cyan LED at 60% brightness and confirm when ready."
        )
        soft.check(baseline_status["color"] == [0, 255, 255], "Baseline color is cyan")
        soft.check(baseline_visible, "Baseline LED is steady cyan at 60%")

        prepare_observation(
            manual_prepare,
            action="the test will try to load empty scene 2",
            expected="the LED remains steady cyan at 60% brightness",
            duration="about 3 seconds",
        )
        response = device_driver.lamp_load_scene(2)
        status_after = device_driver.lamp_status()
        unchanged = manual_check(
            "After attempting to load empty scene 2, does the LED remain steady cyan at 60%?"
        )
        output = _response_text(response)
        soft.check(
            "error: scene 2 is empty" in output.casefold()
            or "[lamp] scene 2 loaded" in output.casefold(),
            f"UART response: {output}",
        )
        soft.check(status_after["color"] == [0, 255, 255], "Color unchanged")
        soft.check(status_after["brightness"] == 60, "Brightness unchanged")
        soft.check(unchanged, "Physical LED unchanged")
        soft.assert_all()

    @allure.story("FR-L9: Persistent lamp settings")
    @allure.title("Lamp settings persist across reboot and lamp starts off")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_settings_survive_reboot(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
        soft: SoftChecks,
    ) -> None:
        prepare_observation(
            manual_prepare,
            action="the test changes saved lamp settings then reboots the board",
            expected="after reboot the lamp is off and the LED shows its Wi-Fi status color",
            duration="about 5 seconds",
        )
        device_driver.lamp_on()
        device_driver.lamp_set_color((17, 34, 51))
        device_driver.lamp_set_brightness(42)
        device_driver.lamp_set_mode("solid")
        assert device_driver.reboot(timeout=30.0), (
            "Firmware did not report ready after reboot."
        )
        status = device_driver.lamp_status()
        wifi_status = device_driver.wifi_status()
        indicator_color = wifi_indicator_color(
            DeviceDriver.wifi_connection_is_valid(wifi_status)
        )
        prepare_observation(
            manual_prepare,
            action="the board has rebooted and its Wi-Fi status has been checked",
            expected=f"the lamp is off and the LED shows {indicator_color}",
            duration="about 5 seconds",
        )
        wifi_indicator_visible = manual_check(
            "After reboot, is the lamp light off and does the LED show the expected "
            f"{indicator_color} Wi-Fi indication?"
        )
        soft.check(status["lamp"] == "off", "Lamp is off after reboot")
        soft.check(status["color"] == [17, 34, 51], "Color persisted")
        soft.check(status["brightness"] == 42, "Brightness persisted")
        soft.check(status["mode"] == "solid", "Mode persisted")
        soft.check(wifi_indicator_visible, "LED shows Wi-Fi indication after reboot")
        soft.assert_all()

    @allure.story("FR-L11: Unknown lamp command")
    @allure.title("Unknown lamp subcommand '{command}' is rejected")
    @pytest.mark.parametrize("command", ("lamp blabla", "lamp loremipsun"))
    @pytest.mark.negative
    def test_unknown_lamp_command(
        self, device_driver: DeviceDriver, firmware_version: str, command: str
    ) -> None:
        _assert_response(
            device_driver.send_command(command),
            "error: unknown lamp command. See 'help'",
        )

    @allure.story("Help: Lamp command discovery")
    @allure.title("Help lists Smart Lamp commands")
    @pytest.mark.smoke
    def test_help_lists_lamp_commands(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        output = _response_text(device_driver.send_command("help", timeout=1.0))
        for command in (
            "lamp on",
            "lamp color",
            "lamp brightness",
            "lamp mode",
            "lamp timer",
            "lamp status",
        ):
            assert command in output, f"Help output does not include {command!r}."
