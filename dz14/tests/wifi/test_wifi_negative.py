import re

import allure
import pytest

try:
    from drivers.device_driver import DeviceDriver
except ModuleNotFoundError:
    from dz14.drivers.device_driver import DeviceDriver


@allure.epic("ДЗ-14: Тестування бездротових інтерфейсів")
@allure.feature("Частина A: station_WiFi (Негативні сценарії)")
class TestWiFiNegative:

    @allure.story("FR-W2: Неправильний пароль")
    @allure.title("A3.1: Валідний SSID з неправильним паролем (>= 8 символів) відхиляється")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.wifi
    @pytest.mark.negative
    def test_wrong_password(
        self,
        device_driver: DeviceDriver,
        invalid_wifi_credentials: dict,
        wifi_cleanup: None,
    ):
        valid_ssid = invalid_wifi_credentials["valid_ssid"]
        wrong_password = invalid_wifi_credentials["wrong_password"]

        with allure.step(f"1. Спроба підключення до '{valid_ssid}' з невірним паролем '{wrong_password}'"):
            connected = device_driver.wifi_connect(
                ssid=valid_ssid,
                password=wrong_password,
            )

        with allure.step("2. Перевірка, що з'єднання не встановлено"):
            assert not connected, "FAIL: Пристрій повідомив про успішне підключення з невірним паролем!"

        with allure.step("3. Перевірка UART-повідомлення про невдале підключення"):
            uart_output = "\n".join(device_driver.uart_log)
            assert re.search(r"\b(fail|failed|timeout)\b", uart_output, re.IGNORECASE), (
                "FAIL: Після неправильного пароля у UART немає повідомлення "
                "про помилку або timeout."
            )

        with allure.step("4. Перевірка статусу пристрою"):
            status = device_driver.wifi_status()
            assert not status["connected"], f"FAIL: Статус помилково показує connected після невірного пароля: {status}"

    @allure.story("FR-W3: Захист від занадто короткого пароля (< 8 символів)")
    @allure.title("A3.2: Пароль < 8 символів відхиляється одразу без спроби підключення")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.wifi
    @pytest.mark.negative
    def test_short_password(
        self,
        device_driver: DeviceDriver,
        invalid_wifi_credentials: dict,
        wifi_cleanup: None,
    ):
        valid_ssid = invalid_wifi_credentials["valid_ssid"]
        short_password = invalid_wifi_credentials["short_password"]

        with allure.step(f"1. Спроба вводу короткого пароля ('{short_password}', довжина {len(short_password)})"):
            connected = device_driver.wifi_connect(
                ssid=valid_ssid,
                password=short_password,
                timeout=5.0,
            )

        with allure.step("2. Перевірка, що з'єднання не відбулося"):
            assert not connected, "FAIL: Відбулося підключення з коротким паролем!"

        with allure.step("3. Перевірка повідомлення про короткий пароль і відсутності спроби підключення"):
            uart_output = "\n".join(device_driver.uart_log).lower()
            assert "password too short (min 8 chars)" in uart_output, (
                "FAIL: Не знайдено точне повідомлення про короткий пароль."
            )
            assert not re.search(
                r"connecting to ssid|state:\s*init\s*->\s*auth",
                uart_output,
                re.IGNORECASE,
            ), "FAIL: Після короткого пароля пристрій почав спробу підключення."

        with allure.step("4. Перевірка статусу пристрою"):
            status = device_driver.wifi_status()
            assert not status["connected"], "FAIL: Пристрій перейшов у стан connected при короткому паролі!"

    @allure.story("FR-W2 & Стійкість CLI: Спроба підключення до неіснуючого SSID")
    @allure.title("A3.3: Неіснуючий SSID призводить до помилки, але пристрій залишається працездатним")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.wifi
    @pytest.mark.negative
    def test_nonexistent_ssid(
        self,
        device_driver: DeviceDriver,
        invalid_wifi_credentials: dict,
        wifi_cleanup: None,
    ):
        nonexistent_ssid = invalid_wifi_credentials["nonexistent_ssid"]
        dummy_password = "any_password_123"

        with allure.step(f"1. Спроба підключення до неіснуючого SSID '{nonexistent_ssid}'"):
            connected = device_driver.wifi_connect(
                ssid=nonexistent_ssid,
                password=dummy_password,
            )

        with allure.step("2. Перевірка, що підключення не відбулося"):
            assert not connected, "FAIL: Повідомлено про підключення до неіснуючої точки доступу!"

        with allure.step("3. Перевірка UART-повідомлення про невдале підключення"):
            uart_output = "\n".join(device_driver.uart_log)
            assert re.search(r"\b(fail|failed|timeout)\b", uart_output, re.IGNORECASE), (
                "FAIL: Після підключення до відсутньої мережі у UART немає "
                "повідомлення про помилку або timeout."
            )

        with allure.step("4. Перевірка живучості пристрою через команду help"):
            help_lines = device_driver.send_command("help", timeout=2.0)
            full_help = " ".join(help_lines).lower()
            assert "connect" in full_help or "scan" in full_help or "status" in full_help, (
                f"FAIL: Пристрій завис або не відповідає на 'help' після невдалого підключення! Вивід: {help_lines}"
            )
