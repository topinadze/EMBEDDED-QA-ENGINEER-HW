import asyncio
import allure
import pytest
from bleak import BleakScanner, BleakClient

try:
    from drivers.device_driver import DeviceDriver
    from config.wifi_config import BLE_DEVICE_NAME, BLE_LED_CHAR_UUID
except ModuleNotFoundError:
    from dz14.drivers.device_driver import DeviceDriver
    from dz14.config.wifi_config import BLE_DEVICE_NAME, BLE_LED_CHAR_UUID


@allure.epic("ДЗ-14: Тестування бездротових інтерфейсів")
@allure.feature("Частина B: Bluedroid_GATT_Server (SENTRY-BLE Dual-Channel Smoke)")
class TestBLESmoke:

    @allure.story("FR-G4: Керування LED через BLE та верифікація по UART (Dual-Channel)")
    @allure.title("B2: Dual-Channel smoke: BLE Write (0x01 / 0x00) -> UART log verification ('LED ON!' / 'LED OFF!')")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.ble
    @pytest.mark.smoke
    @pytest.mark.asyncio
    async def test_ble_led_dual_channel(
        self,
        device_driver: DeviceDriver,
    ):
        """
        Перевірка наскрізної взаємодії BLE та UART:
        1. Сканування радіоефіру та знаходження пристрою 'SENTRY-BLE'.
        2. Підключення через BLE GATT Client (bleak).
        3. Запис 0x01 у LED-характеристику та перевірка логу 'LED ON!' по UART.
        4. Запис 0x00 у LED-характеристику та перевірка логу 'LED OFF!' по UART.
        5. Відключення BLE клієнта та перевірка логу відключення.
        """
        with allure.step(f"1. Пошук BLE-пристрою з ім'ям '{BLE_DEVICE_NAME}' через BleakScanner"):
            device = await BleakScanner.find_device_by_name(BLE_DEVICE_NAME, timeout=10.0)
            assert device is not None, (
                f"FAIL: BLE-пристрій '{BLE_DEVICE_NAME}' не знайдено під час сканування! "
                f"Переконайтеся, що прошито Bluedroid_GATT_Server і Bluetooth увімкнено на ПК."
            )

        with allure.step(f"2. Підключення до GATT-сервера {device.address}"):
            async with BleakClient(device) as client:
                assert client.is_connected, f"FAIL: Не вдалося встановити BLE з'єднання з {device.address}"

                # Очищаємо залишки буфера UART перед тестом
                device_driver.read_lines(timeout=0.3)

                with allure.step("3. Запис 0x01 у LED-характеристику (Turn ON)"):
                    await client.write_gatt_char(BLE_LED_CHAR_UUID, bytearray([0x01]), response=True)

                    # Перевіряємо другий канал спостереження (UART)
                    found_on = device_driver.wait_for("LED ON!", timeout=3.0)
                    assert found_on, "FAIL: UART не зафіксував подію 'LED ON!' після BLE write 0x01!"

                with allure.step("4. Запис 0x00 у LED-характеристику (Turn OFF)"):
                    await client.write_gatt_char(BLE_LED_CHAR_UUID, bytearray([0x00]), response=True)

                    # Перевіряємо другий канал спостереження (UART)
                    found_off = device_driver.wait_for("LED OFF!", timeout=3.0)
                    assert found_off, "FAIL: UART не зафіксував подію 'LED OFF!' після BLE write 0x00!"

        with allure.step("5. BLE-клієнт відключено"):
            # Підтвердження відключення по UART логу (FR-A3)
            disconnected_log = device_driver.wait_for("Disconnected", timeout=3.0)
            allure.attach(
                f"UART Disconnect detected: {disconnected_log}",
                name="BLE Disconnect Status",
                attachment_type=allure.attachment_type.TEXT,
            )
