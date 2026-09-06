import time
import pytest
import serial.tools.list_ports
from drivers.device_driver import DeviceDriver
from config.test_config import DEFAULT_USER, DEFAULT_PASSWORD


def find_esp32_port() -> str:
    """Динамічний пошук COM-порту підключеного ESP32/UART пристрою."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        pytest.fail("No available COM ports found on the system!")

    descriptors = ["CP210", "CH340", "FT232", "ESP32", "USB-to-UART", "Serial"]

    for p in ports:
        for desc in descriptors:
            if desc.lower() in p.description.lower() or (
                p.manufacturer and desc.lower() in p.manufacturer.lower()
            ):
                return p.device

    return ports[0].device


@pytest.fixture(scope="class")
def device_driver():
    """Фікстура рівня класу: відкриває порт один раз на клас і закриває його в кінці."""
    com_port = find_esp32_port()
    driver = DeviceDriver(port=com_port, timeout=2.0)
    driver.open()

    yield driver  # Виконується сам тест

    driver.close()


@pytest.fixture(autouse=True)
def reboot_device_between_tests(device_driver: DeviceDriver):
    """
    Гарантує чистий RAM пристрою після кожного тесту.
    """
    yield  # Виконується сам тест

    # Teardown: переконуємося, що ми авторизовані для виконання reboot
    try:
        # Намагаємося залогінитися або відразу слати reboot
        device_driver.send_command("login qa_admin password123")
        time.sleep(0.2)
        device_driver.send_command("reboot")
    except Exception:
        pass

    # Чекаємо перезавантаження
    time.sleep(3.0)

    # Вичищаємо буфери
    if device_driver.serial and device_driver.serial.is_open:
        device_driver.serial.reset_input_buffer()
        device_driver.serial.reset_output_buffer()


@pytest.fixture
def hard_reset_after_test(device_driver: DeviceDriver):
    """
    Фікстура для тесту test_rate_limit_blocking.
    Після завершення тесту робить АПАРАТНИЙ скид (RTS/DTR),
    ігноруючи блокування профілю та відсутність AUTH.
    """
    yield  # Виконується сам тест
    # Teardown підгледів звісно :)
    if device_driver.serial and device_driver.serial.is_open:
        try:
            device_driver.serial.setDTR(False)
            device_driver.serial.setRTS(True)
            time.sleep(0.15)
            device_driver.serial.setRTS(False)
        except Exception as e:
            print(f"\n[Teardown Warning] Hard reset failed: {e}")

    time.sleep(3.0)
    # Очищаємо буфери
    if device_driver.serial and device_driver.serial.is_open:
        device_driver.serial.reset_input_buffer()
        device_driver.serial.reset_output_buffer()


@pytest.fixture
def user_credentials() -> tuple[str, str]:
    return DEFAULT_USER, DEFAULT_PASSWORD
