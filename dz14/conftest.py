import os
import sys
import time
import pytest
import serial.tools.list_ports

# Ensure both dz14 directory and parent directory are in sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR in sys.path:
    sys.path.remove(CURRENT_DIR)
sys.path.insert(0, CURRENT_DIR)

try:
    from drivers.device_driver import DeviceDriver
    from settings import (
        INVALID_PASSWORD,
        NON_EXISTENT_SSID,
        SHORT_PASSWORD,
        SERIAL_TIMEOUT,
        WIFI_PASSWORD,
        WIFI_SSID,
    )
except ModuleNotFoundError:
    from dz14.drivers.device_driver import DeviceDriver
    from dz14.settings import (
        INVALID_PASSWORD,
        NON_EXISTENT_SSID,
        SHORT_PASSWORD,
        SERIAL_TIMEOUT,
        WIFI_PASSWORD,
        WIFI_SSID,
    )

# Standard Vendor IDs for USB-to-UART converters and ESP32 chips
ESP32_VIDS = [
    0x10C4,  # Silicon Labs CP210x
    0x1A86,  # QinHeng Electronics CH340/CH341
    0x0403,  # FTDI FT232
    0x303A,  # Espressif Systems (ESP32-S2/S3/C3 Native USB)
]


def find_esp32_port() -> str:
    """Динамічний пошук COM-порту підключеного ESP32/UART пристрою за VID/описом."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        pytest.fail("Жодного COM-порту не знайдено на системі! Підключіть ESP32-S3 DevKit.")

    descriptors = ["cp210", "ch340", "ft232", "esp32", "usb-to-uart", "usb serial"]
    candidates = [
        p
        for p in ports
        if p.vid in ESP32_VIDS
        or any(
            d in f"{p.description or ''} {p.manufacturer or ''}".lower()
            for d in descriptors
        )
    ]
    if len(candidates) == 1:
        return candidates[0].device
    if not candidates:
        pytest.fail(
            "Не знайдено жодного порту ESP32 (перевірено VID та описи). Вкажіть порт явно через конфігурацію або CLI."
        )
    pytest.fail(
        "Знайдено декілька потенційних портів ESP32: "
        + ", ".join(p.device for p in candidates)
        + ". Вкажіть потрібний порт явно."
    )


@pytest.fixture(scope="session")
def esp32_port() -> str:
    """COM-порт пристрою."""
    return find_esp32_port()


@pytest.fixture(scope="class")
def device_driver(esp32_port: str):
    """
    Фікстура рівня класу: відкриває serial з'єднання один раз на тестовий клас
    і коректно закриває порт наприкінці.
    """
    driver = DeviceDriver(port=esp32_port, timeout=SERIAL_TIMEOUT)
    driver.open()

    yield driver

    driver.close()


@pytest.fixture(autouse=True)
def attach_test_uart_log(request: pytest.FixtureRequest):
    """Attach UART output to any test that uses the shared device driver."""
    if "device_driver" not in request.fixturenames:
        yield
        return

    driver: DeviceDriver = request.getfixturevalue("device_driver")
    driver.reset_uart_log()
    yield
    driver.attach_uart_log()


@pytest.fixture
def wifi_credentials() -> tuple[str, str]:
    """Валідні креденшили Wi-Fi тестової мережі."""
    if not WIFI_PASSWORD:
        pytest.skip("Set TEST_WIFI_PASSWORD to run credential-based Wi-Fi tests.")
    return WIFI_SSID, WIFI_PASSWORD


@pytest.fixture
def invalid_wifi_credentials() -> dict:
    """Набір невалідних креденшилів для негативного тестування."""
    if not WIFI_PASSWORD:
        pytest.skip("Set TEST_WIFI_PASSWORD to run credential-based Wi-Fi tests.")
    return {
        "valid_ssid": WIFI_SSID,
        "wrong_password": INVALID_PASSWORD,
        "short_password": SHORT_PASSWORD,
        "nonexistent_ssid": NON_EXISTENT_SSID,
    }


@pytest.fixture
def wifi_cleanup(device_driver: DeviceDriver):
    """
    Ensures Wi-Fi connection tests start and finish in a disconnected state.
    """
    device_driver.wifi_disconnect()
    yield
    try:
        device_driver.wifi_disconnect()
    except Exception:
        pass
