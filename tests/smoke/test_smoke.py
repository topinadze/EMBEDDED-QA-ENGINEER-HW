import allure
import pytest
from drivers.device_driver import DeviceDriver


@allure.epic("Embedded Testing")
@allure.feature("Smoke Test Suite")
class TestSentrySmoke:

    @allure.story("Authentication & Access Levels")
    @allure.title("Smoke 01: Verify unauthenticated commands limit & user login")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.smoke
    @pytest.mark.hw_9
    def test_smoke_auth_flow(
        self,
        device_driver: DeviceDriver,
        user_credentials: tuple[str, str],
    ):
        user, password = user_credentials

        with allure.step("1. Перевірка команди help без авторизації (AUTH_NONE)"):
            help_res = " ".join(device_driver.send_command("help")).lower()
            assert "register" in help_res and "login" in help_res, (
                f"FAIL: Справка help недоступна або некоректна у станi AUTH_NONE. Отримано: '{help_res}'"
            )

        with allure.step("2. Реєстрація єдиного профілю"):
            reg_res = " ".join(device_driver.send_command(f"register {user} {password}")).lower()
            assert "ok" in reg_res or "created" in reg_res or user in reg_res, (
                f"FAIL: Не вдалося зареєструвати користувача '{user}'. Отримано: '{reg_res}'"
            )

        with allure.step("3. Вхід у сесію (AUTH_USER)"):
            login_res = " ".join(device_driver.send_command(f"login {user} {password}")).lower()
            assert "welcome" in login_res or "started" in login_res or "ok" in login_res, (
                f"FAIL: Вхід не виконано. Отримано: '{login_res}'"
            )

        with allure.step("4. Перевірка виконання команди status для AUTH_USER"):
            status_res = " ".join(device_driver.send_command("status")).lower()
            assert "heap" in status_res or "led" in status_res, (
                f"FAIL: Команда status недоступна після входу. Отримано: '{status_res}'"
            )

    @allure.story("Hardware Control")
    @allure.title("Smoke 02: LED blink within allowed range (1..20)")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.smoke
    @pytest.mark.hw_9
    def test_smoke_led_blink(
        self,
        authenticated_device: DeviceDriver,
        reboot_device_between_tests: None,
    ):
        with allure.step("1. Виконання led blink 3"):
            response = " ".join(authenticated_device.send_command("led blink 3")).lower()
            assert "blinking" in response or "done" in response or "ok" in response, (
                f"FAIL: Некоректний відгук на 'led blink 3'. Отримано: '{response}'"
            )

    @allure.story("Distance Sensor (HC-SR04)")
    @allure.title("Smoke 03: Single distance measurement")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.smoke
    @pytest.mark.hw_9
    def test_smoke_distance_read(
        self,
        authenticated_device: DeviceDriver,
        reboot_device_between_tests: None,
    ):
        with allure.step("1. Виконання команди distance"):
            response = " ".join(authenticated_device.send_command("distance")).lower()
            
            has_valid_resp = "cm" in response or "timeout" in response or "raw" in response
            assert has_valid_resp, (
                f"FAIL: Команда 'distance' повернула некоректну відповідь: '{response}'"
            )

    @allure.story("Relay Control")
    @allure.title("Smoke 04: Toggle Relay status")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.smoke
    @pytest.mark.hw_9
    def test_smoke_relay_control(
        self,
        authenticated_device: DeviceDriver,
        reboot_device_between_tests: None,
    ):
        with allure.step("1. Увімкнення реле"):
            on_res = " ".join(authenticated_device.send_command("relay on")).lower()
            assert "on" in on_res or "ok" in on_res, f"FAIL: Не вдалося увімкнути реле: '{on_res}'"

        with allure.step("2. Вимкнення реле"):
            off_res = " ".join(authenticated_device.send_command("relay off")).lower()
            assert "off" in off_res or "ok" in off_res, f"FAIL: Не вдалося вимкнути реле: '{off_res}'"

    @allure.story("Telemetry & Alarm")
    @allure.title("Smoke 05: Sensor history buffer check")
    @allure.severity(allure.severity_level.NORMAL)
    @pytest.mark.smoke
    @pytest.mark.hw_9
    def test_smoke_sensor_history(
        self,
        authenticated_device: DeviceDriver,
        reboot_device_between_tests: None,
    ):
        with allure.step("1. Запит історії без попереднього запуску"):
            response = " ".join(authenticated_device.send_command("sensor history")).lower()
            
            # Повинно повернути або порожній буфер, або список зафіксованих показань
            assert "empty" in response or "temp:" in response or "[" in response, (
                f"FAIL: Некоректний відгук на 'sensor history': '{response}'"
            )