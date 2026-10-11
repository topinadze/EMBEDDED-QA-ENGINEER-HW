from __future__ import annotations

from collections.abc import Callable

import allure
import pytest

from drivers.device_driver import DeviceDriver

NAMED_COLORS = (
    ("red", [255, 0, 0]),
    ("green", [0, 255, 0]),
    ("blue", [0, 0, 255]),
    ("white", [255, 255, 255]),
    ("yellow", [255, 180, 0]),
    ("purple", [160, 0, 255]),
    ("cyan", [0, 255, 255]),
)


def _response_text(lines: list[str]) -> str:
    return "\n".join(lines)


def _assert_response(lines: list[str], expected: str) -> None:
    output = _response_text(lines)
    assert expected.casefold() in output.casefold(), (
        f"Expected {expected!r} in UART response:\n{output}"
    )


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
    ) -> None:
        on_response = device_driver.lamp_on()
        on_status = device_driver.lamp_status()
        on_visible = manual_check("Is the RGB LED visibly lit while the lamp is on?")
        _assert_response(on_response, "[LAMP] on")
        assert on_status["lamp"] == "on"
        assert on_visible

        off_response = device_driver.lamp_off()
        off_status = device_driver.lamp_status()
        wifi_indicator_visible = manual_check(
            "After lamp off, has the LED returned to Wi-Fi indication "
            "(dim green if connected, dim red if disconnected)?"
        )
        _assert_response(off_response, "[LAMP] off")
        assert off_status["lamp"] == "off"
        assert wifi_indicator_visible

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
        color_name: str,
        expected_rgb: list[int],
    ) -> None:
        device_driver.lamp_on()
        response = device_driver.lamp_set_color(color_name)
        status = device_driver.lamp_status()
        color_visible = manual_check(
            f"Look at the LED: does it visibly show {color_name}?"
        )
        _assert_response(response, f"[LAMP] color set: {color_name}")
        assert status["color"] == expected_rgb
        assert color_visible, f"Physical LED color did not match {color_name}."

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
    ) -> None:
        device_driver.lamp_on()
        response = device_driver.lamp_set_color((255, 0, 128))
        status = device_driver.lamp_status()
        color_visible = manual_check(
            "Does the LED visibly show the expected pink/magenta-like custom color "
            "for RGB (255, 0, 128)?"
        )
        _assert_response(response, "[LAMP] color set: (255,0,128)")
        assert status["color"] == [255, 0, 128]
        assert color_visible

    @allure.story("FR-L3: RGB range validation")
    @allure.title("Out-of-range RGB {rgb} is rejected without changing the color")
    @pytest.mark.parametrize(
        "rgb",
        ((300, 0, 0), (0, 0, 300), (-1, -1, -1), (256, 0, 0)),
    )
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
    @pytest.mark.parametrize("rgb", ((300, 0, 0), (0, 0, 300), (-1, -1, -1), (256, 0, 0)))
    def test_invalid_rgb_visual(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        rgb: tuple[int, int, int],
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_color("green")
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady green LED and confirm when ready to send an invalid RGB."
        )
        assert baseline_status["color"] == [0, 255, 0]
        assert baseline_visible

        response = device_driver.lamp_set_color(rgb)
        status = device_driver.lamp_status()
        unchanged = manual_check(
            "After the invalid RGB was rejected, does the LED remain green?"
        )
        _assert_response(response, "error: rgb values must be 0-255")
        assert status["color"] == [0, 255, 0]
        assert unchanged

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
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_color("yellow")
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady yellow LED and confirm when ready to send an unknown color."
        )
        assert baseline_status["color"] == [255, 180, 0]
        assert baseline_visible

        response = device_driver.lamp_set_color("orange")
        status = device_driver.lamp_status()
        unchanged = manual_check(
            "After 'orange' was rejected, does the LED remain yellow?"
        )
        _assert_response(response, "error: unknown color 'orange'")
        assert status["color"] == [255, 180, 0]
        assert unchanged

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
        brightness: int,
    ) -> None:
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
        _assert_response(response, f"[LAMP] brightness set: {brightness}%")
        assert status["brightness"] == brightness
        assert physically_correct, (
            f"Physical LED brightness was not as expected at {brightness}%."
        )

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
        brightness: int,
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_color("white")
        device_driver.lamp_set_mode("solid")
        device_driver.lamp_set_brightness(50)
        baseline_status = device_driver.lamp_status()
        baseline_visible = manual_check(
            "Observe the steady white LED at 50% brightness and remember its "
            "appearance; confirm when ready to test the invalid value."
        )
        assert baseline_status["brightness"] == 50
        assert baseline_visible

        response = device_driver.lamp_set_brightness(brightness)
        status = device_driver.lamp_status()
        unchanged = manual_check(
            f"After brightness {brightness} was rejected, does the LED look "
            "unchanged from the 50% white baseline?"
        )
        _assert_response(response, "error: brightness must be 0-100")
        assert status["brightness"] == 50
        assert status["color"] == [255, 255, 255]
        assert unchanged, f"LED visibly changed after invalid brightness {brightness}."

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
        mode: str,
    ) -> None:
        if mode == "rainbow" and firmware_version != "1.5.0":
            pytest.skip(
                f"Rainbow mode is not implemented in firmware {firmware_version}."
            )

        device_driver.lamp_on()
        device_driver.lamp_set_color("blue")
        device_driver.lamp_set_brightness(50)
        response = device_driver.lamp_set_mode(mode)
        status = device_driver.lamp_status()

        expected_behavior = {
            "solid": "steady blue light",
            "blink": "blue light blinking at about 1 Hz (roughly 0.5 s on / 0.5 s off)",
            "breathe": "blue light smoothly pulsing with an approximately 3-second period",
            "rainbow": "a complete smooth color cycle through the rainbow in approximately 5 seconds",
        }[mode]
        visually_correct = manual_check(
            f"Observe long enough to check the timing. Does the LED visibly show "
            f"{expected_behavior} at 50% brightness?"
        )
        _assert_response(response, f"[LAMP] mode set: {mode}")
        assert status["mode"] == mode
        assert visually_correct, f"Physical LED behavior did not match mode '{mode}'."

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
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_color("white")
        device_driver.lamp_set_mode("solid")
        _assert_response(
            device_driver.lamp_set_timer(5),
            "[LAMP] auto-off in 5 s",
        )
        timer_expired = device_driver.wait_for("timer expired, lamp off", timeout=8.0)
        status = device_driver.lamp_status()
        visually_off = manual_check(
            "After the 5-second timer expired, did the lamp light turn off and "
            "the LED return to Wi-Fi indication (dim green if connected, "
            "dim red if disconnected)?"
        )
        assert timer_expired, "Timer expiration was not logged within eight seconds."
        assert status["lamp"] == "off"
        assert visually_off

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
    @pytest.mark.negative
    def test_invalid_scene_index(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        if firmware_version != "1.5.0":
            pytest.skip(
                f"Scenes are not implemented in firmware {firmware_version}."
            )
        _assert_response(
            device_driver.lamp_save_scene(7),
            "error: scene must be 1-3",
        )

    @allure.story("FR-L9: Persistent lamp settings")
    @allure.title("Lamp settings persist across reboot and lamp starts off")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_settings_survive_reboot(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
    ) -> None:
        device_driver.lamp_on()
        device_driver.lamp_set_color((17, 34, 51))
        device_driver.lamp_set_brightness(42)
        device_driver.lamp_set_mode("solid")
        device_driver.send_command("reboot", timeout=0.6)

        assert device_driver.wait_for("station_WiFi fw v", timeout=10.0), (
            "Firmware did not report ready after reboot."
        )
        status = device_driver.lamp_status()
        wifi_indicator_visible = manual_check(
            "After reboot, is the lamp light off and has the LED returned to "
            "Wi-Fi indication (dim green if connected, dim red if disconnected)?"
        )
        assert status["lamp"] == "off"
        assert status["color"] == [17, 34, 51]
        assert status["brightness"] == 42
        assert status["mode"] == "solid"
        assert wifi_indicator_visible

    @allure.story("FR-L11: Unknown lamp command")
    @allure.title("Unknown lamp subcommand is rejected")
    @pytest.mark.negative
    def test_unknown_lamp_command(
        self, device_driver: DeviceDriver, firmware_version: str
    ) -> None:
        _assert_response(
            device_driver.send_command("lamp loremipsun"),
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
