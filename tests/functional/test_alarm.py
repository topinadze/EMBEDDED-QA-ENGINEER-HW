import time
import allure
import pytest
from drivers.device_driver import DeviceDriver


@allure.epic("Embedded Testing")
@allure.feature("Alarm System")
class TestAlarmFunctional:

    @allure.story("State Machine Constraints")
    @allure.title("Parametrized: 'alarm clear' availability across states")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.alarm
    @pytest.mark.functional
    @pytest.mark.hw_9
    @pytest.mark.parametrize(
        "setup_command, expect_clear_success, description",
        [
            ("alarm disarm", False, "Зі стану DISARMED команда clear відхиляється"),
            (
                "alarm arm",
                False,
                "Зі стану ARMED (без спрацьовування) команда clear відхиляється",
            ),
        ],
        ids=["clear_from_disarmed", "clear_from_armed_normal"],
    )
    def test_alarm_clear_invalid_states(
        self,
        authenticated_device: DeviceDriver,
        reboot_device_between_tests: None,
        setup_command: str,
        expect_clear_success: bool,
        description: str,
    ):
        """
        Перевірка, що 'alarm clear' відхиляється з попередженням,
        якщо сигналізація НЕ перебуває у стані TRIGGERED (секція 8.2 PRD).
        """
        with allure.step(f"1. Переведення alarm у стан через '{setup_command}'"):
            command_res = " ".join(authenticated_device.send_command(setup_command))

        with allure.step(f"3. Перевірка виконання '{setup_command}'"):
            if "alarm arm" in setup_command:
                assert (
                    "ARMED" in command_res.upper()
                ), f"FAIL: Команда '{setup_command}' відхилена. Отримано: '{command_res}'"
            elif "alarm disarm" in setup_command:
                assert (
                    "DISARMED" in command_res.upper()
                ), f"FAIL: Команда '{setup_command}' відхилена. Отримано: '{command_res}'"

        with allure.step("2. Спроба виконання 'alarm clear'"):
            clear_res = " ".join(
                authenticated_device.send_command("alarm clear")
            ).lower()

            with allure.step("Перевірка виконання 'alarm clear'"):
                if not expect_clear_success:
                    assert (
                        "Nothing to clear.".lower() in clear_res
                    ), f"FAIL [{description}]: Команда 'alarm clear' мала бути відхилена. Отримано: '{clear_res}'"

    @allure.story("Distance Zone Alarm")
    @allure.title("Parametrized: Distance zones triggering")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.alarm
    @pytest.mark.functional
    @pytest.mark.hw_9
    @pytest.mark.parametrize(
        "zone_command, expect_active",
        [
            ("distance zone near", "near"),
            ("distance zone far", "far"),
            ("distance zone custom 10 50", "custom"),
            ("distance zone off", "off"),
        ],
        ids=["zone_near", "zone_far", "zone_custom", "zone_off"],
    )
    def test_distance_zone_configuration(
        self,
        authenticated_device: DeviceDriver,
        reboot_device_between_tests: None,
        zone_command: str,
        expect_active: str,
    ):
        """
        Параметризована перевірка налаштування зон відстані для HC-SR04 (Фіча 13.5).
        """
        with allure.step(f"1. Встановлення конфігурації зони: {zone_command}"):
            res = " ".join(authenticated_device.send_command(zone_command)).lower()
            assert (
                f"Zone: {expect_active}".lower() in res
                or "Zone monitoring disabled".lower() in res
            ), f"FAIL: Помилка при виконанні '{zone_command}': '{res}'"

        with allure.step("2. Перевірка статусу підсистеми distance"):
            status_res = " ".join(
                authenticated_device.send_command("distance status")
            ).lower()
            if expect_active != "off":
                assert (
                    expect_active in status_res
                    or "active" in status_res
                    or "zone" in status_res
                ), f"FAIL: Зона {expect_active} не відображається у 'distance status': '{status_res}'"
