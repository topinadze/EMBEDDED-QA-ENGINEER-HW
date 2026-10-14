"""Backward-compatible imports; primary settings live in dz14/settings.py."""

try:
    from settings import (
        BLE_DEVICE_NAME,
        BLE_LED_CHAR_UUID,
        BLE_RELAY_CHAR_UUID,
        INVALID_PASSWORD,
        NON_EXISTENT_SSID,
        REBOOT_TIMEOUT,
        SERIAL_BAUDRATE,
        SERIAL_TIMEOUT,
        SHORT_PASSWORD,
        WIFI_CONNECT_TIMEOUT,
        WIFI_PASSWORD,
        WIFI_SSID,
    )
except ModuleNotFoundError:
    from dz14.settings import (
        BLE_DEVICE_NAME,
        BLE_LED_CHAR_UUID,
        BLE_RELAY_CHAR_UUID,
        INVALID_PASSWORD,
        NON_EXISTENT_SSID,
        REBOOT_TIMEOUT,
        SERIAL_BAUDRATE,
        SERIAL_TIMEOUT,
        SHORT_PASSWORD,
        WIFI_CONNECT_TIMEOUT,
        WIFI_PASSWORD,
        WIFI_SSID,
    )
