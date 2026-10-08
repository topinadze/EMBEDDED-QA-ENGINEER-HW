import re
import allure
import pytest

try:
    from drivers.device_driver import DeviceDriver
except ModuleNotFoundError:
    from dz14.drivers.device_driver import DeviceDriver


@allure.epic("ДЗ-14: Тестування бездротових інтерфейсів")
@allure.feature("Частина A: station_WiFi (Позитивні сценарії)")
class TestWiFiPositive:

    @allure.story("FR-W1: Сканування Wi-Fi мереж")
    @allure.title(
        "A2.1: Сканування повертає непорожній список та знаходить цільову мережу"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.wifi
    @pytest.mark.positive
    def test_scan_finds_networks(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
    ):
        target_ssid, _ = wifi_credentials

        with allure.step("1. Виконання сканування мереж через wifi_scan()"):
            scanned_ssids = device_driver.wifi_scan(timeout=10.0)

        with allure.step("2. Перевірка, що знайдено хоча б одну мережу"):
            assert (
                len(scanned_ssids) > 0
            ), "FAIL: Сканування повернуло порожній список мереж!"

        with allure.step(f"3. Перевірка наявності цільової мережі '{target_ssid}'"):
            assert any(
                target_ssid.lower() == ssid.lower() for ssid in scanned_ssids
            ), f"FAIL: Цільову мережу '{target_ssid}' не знайдено у списку: {scanned_ssids}"

        with allure.step("4. Перевірка номера мережі, SSID та RSSI у UART-виводі"):
            scan_output = "\n".join(device_driver.uart_log)
            legacy_target_row = re.search(
                rf"\[\s*\d+\s*\]\s*{re.escape(target_ssid)}\s+-?\d+\s*dBm",
                scan_output,
                re.IGNORECASE,
            )
            labeled_target_row = re.search(
                rf"\[\s*\d+\s*\]\s*SSID:\s*{re.escape(target_ssid)}\s+"
                r"RSSI:\s*-?\d+\s*dBm",
                scan_output,
                re.IGNORECASE,
            )
            assert legacy_target_row or labeled_target_row, (
                "FAIL: У результаті сканування немає рядка цільової мережі "
                "з номером та RSSI у dBm."
            )

    @allure.story("FR-W2 & FR-W5: Підключення до Wi-Fi та перевірка IP")
    @allure.title("A2.2: Успішне підключення з валідними креденшилами та отримання IP")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.wifi
    @pytest.mark.positive
    def test_connect_success(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
        wifi_cleanup: None,
    ):
        target_ssid, password = wifi_credentials

        with allure.step(f"1. Підключення до мережі '{target_ssid}'"):
            connected = device_driver.wifi_connect(ssid=target_ssid, password=password)
            assert connected, f"FAIL: Не вдалося підключитися до Wi-Fi '{target_ssid}'."
            assert device_driver.last_wifi_connect_duration is not None, (
                "FAIL: Час підключення не зафіксовано після успішного з'єднання."
            )
            assert device_driver.last_wifi_connect_duration <= 10.0, (
                "FAIL: Підключення перевищило FR-W2 timeout 10 s: "
                f"{device_driver.last_wifi_connect_duration:.2f} s"
            )

        with allure.step("2. Запит статусу підключення та валідація IP-адреси"):
            status = device_driver.wifi_status()
            assert status[
                "connected"
            ], f"FAIL: wifi_status() показує статус 'не підключено': {status}"
            assert (
                status["ip"] is not None
            ), f"FAIL: Пристрій не отримав IP-адресу! Статус: {status}"
            assert re.match(
                r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", status["ip"]
            ), f"FAIL: Отримана IP-адреса не відповідає формату IPv4: '{status['ip']}'"

    @allure.story("FR-W6: Відключення від мережі")
    @allure.title(
        "A2.3: Відключення розриває з'єднання, status фіксує відключений стан"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.wifi
    @pytest.mark.positive
    @allure.issue(
        "BUG-01",
        name="status reports WiFi connected with an empty SSID and IP 0.0.0.0 after disconnect.",
    )
    @pytest.mark.xfail(
        reason="BUG-01: status reports WiFi connected with an empty SSID and IP 0.0.0.0 after disconnect.",
        strict=True,
    )
    def test_disconnect(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
        wifi_cleanup: None,
    ):
        target_ssid, password = wifi_credentials

        with allure.step("1. Попереднє підключення до мережі"):
            connected = device_driver.wifi_connect(ssid=target_ssid, password=password)
            assert (
                connected
            ), f"SETUP FAIL: Не вдалося підключитися до '{target_ssid}' перед перевіркою disconnect."

        with allure.step("2. Виконання команди disconnect"):
            disconnect_response = device_driver.wifi_disconnect()
            allure.attach(
                "\n".join(disconnect_response),
                name="Disconnect Output",
                attachment_type=allure.attachment_type.TEXT,
            )

        with allure.step("3. Перевірка статусу після disconnect"):
            status = device_driver.wifi_status()
            assert not status[
                "connected"
            ], f"FAIL: Після disconnect пристрій все ще перебуває у стані connected! Статус: {status}"

    @allure.story("FR-W4: Збереження креденшилів у NVS після reboot")
    @allure.title(
        "A2.4: Збережені креденшили переживають reboot та дозволяють швидке підключення (Enter)"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.wifi
    @pytest.mark.positive
    def test_credentials_survive_reboot(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
        wifi_cleanup: None,
    ):
        target_ssid, password = wifi_credentials

        with allure.step("1. Початкове підключення для збереження креденшилів у NVS"):
            connected = device_driver.wifi_connect(ssid=target_ssid, password=password)
            assert connected, "SETUP FAIL: Початкове підключення не відбулося."

        with allure.step("2. Перезавантаження пристрою"):
            rebooted = device_driver.reboot()
            assert rebooted, "FAIL: Пристрій не вийшов на готовність після reboot."

        with allure.step(
            "3. Виклик connect з порожнім вводом (Enter для збережених даних)"
        ):
            connected_saved = device_driver.wifi_connect(ssid="", password="")
            assert (
                connected_saved
            ), "FAIL: Не вдалося підключитися за збереженими креденшилами після перезавантаження!"

        with allure.step("4. Перевірка, що статус показує підключення та валідну IP"):
            status = device_driver.wifi_status()
            assert status[
                "connected"
            ], f"FAIL: Статус не підтвердив підключення: {status}"
            assert (
                status["ip"] is not None
            ), f"FAIL: IP адреса відсутня після підключення: {status}"
