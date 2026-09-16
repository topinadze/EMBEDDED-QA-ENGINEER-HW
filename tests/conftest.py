import time
import allure
import pytest
import serial.tools.list_ports
from drivers.device_driver import DeviceDriver
from config.test_config import DEFAULT_USER, DEFAULT_PASSWORD

# Стандартні Vendor IDs для USB-to-UART конвертерів та ESP32
ESP32_VIDS = [
    0x10C4,  # Silicon Labs CP210x
    0x1A86,  # QinHeng Electronics CH340/CH341
    0x0403,  # FTDI FT232
    0x303A,  # Espressif Systems (ESP32-S2/S3/C3 Native USB)
]

descriptors = ["CP210", "CH340", "FT232", "ESP32", "USB-to-UART", "Serial"]


def find_esp32_port() -> str:
    """Динамічний пошук COM-порту підключеного ESP32/UART пристрою."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        pytest.fail("No available COM ports found on the system!")

    # 1. Пошук за Vendor ID
    for p in ports:
        if p.vid in ESP32_VIDS:
            return p.device

    # 2. Фолбек за текстовим описом, якщо VID не збігся
    descriptors = ["cp210", "ch340", "ft232", "esp32", "usb-to-uart"]
    for p in ports:
        desc = (p.description or "") + (p.manufacturer or "")
        if any(d in desc.lower() for d in descriptors):
            return p.device

    # 3. Якщо нічого не знайдено — повертаємо перший доступний
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
    device_driver.wait_for("App started", timeout=3)

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

    device_driver.wait_for("App started", timeout=3)
    # Очищаємо буфери
    if device_driver.serial and device_driver.serial.is_open:
        device_driver.serial.reset_input_buffer()
        device_driver.serial.reset_output_buffer()


@pytest.fixture
def user_credentials() -> tuple[str, str]:
    return DEFAULT_USER, DEFAULT_PASSWORD


@pytest.fixture
def authenticated_device(
    device_driver: DeviceDriver, user_credentials: tuple[str, str]
) -> DeviceDriver:
    with allure.step("1. Авторизація"):
        user, password = user_credentials
        device_driver.send_command(f"register {user} {password}")

        is_logged_in = device_driver.login(user, password)

    assert (
        is_logged_in
    ), f"SETUP FAIL: Не вдалося авторизуватися під користувачем '{user}'."

    return device_driver
