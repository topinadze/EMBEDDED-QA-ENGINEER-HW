"""Shared DZ14 defaults and environment-based test settings."""

from __future__ import annotations

import os

WIFI_SSID = os.getenv("TEST_WIFI_SSID", "TopA-node")
WIFI_PASSWORD = os.getenv("TEST_WIFI_PASSWORD", "")
INVALID_PASSWORD = os.getenv("TEST_INVALID_PASSWORD", "wrong_password123")
SHORT_PASSWORD = "short"
NON_EXISTENT_SSID = "NON_EXISTENT_SSID_9999"

SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT = 2.0
WIFI_CONNECT_TIMEOUT = 10.0
REBOOT_TIMEOUT = 8.0

BLE_DEVICE_NAME = os.getenv("TEST_BLE_DEVICE_NAME", "SENTRY-BLE")
BLE_LED_CHAR_UUID = os.getenv(
    "TEST_BLE_LED_CHAR_UUID", "00001525-1212-efde-1523-785feabcd123"
)
BLE_RELAY_CHAR_UUID = os.getenv(
    "TEST_BLE_RELAY_CHAR_UUID", "00001526-1212-efde-1523-785feabcd123"
)
