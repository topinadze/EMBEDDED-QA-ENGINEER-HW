"""
Wi-Fi and UART configuration compatibility facade for DZ17.
Reads from test_config and environment variables.
"""

from __future__ import annotations

from config.test_config import (
    DEFAULT_WIFI_MISSING_SSID,
    DEFAULT_WIFI_PASSWORD,
    DEFAULT_WIFI_SSID,
    DEFAULT_WIFI_WRONG_PASSWORD,
    WIFI_MISSING_SSID,
    WIFI_PASSWORD,
    WIFI_SSID,
    WIFI_WRONG_PASSWORD,
    resolve_wifi_credentials,
)

SERIAL_PORT = None  # Auto-detected if None
BAUDRATE = 115200
SERIAL_TIMEOUT = 0.5
WIFI_CONNECT_TIMEOUT = 12.0
OTA_TIMEOUT = 120.0

__all__ = [
    "BAUDRATE",
    "DEFAULT_WIFI_MISSING_SSID",
    "DEFAULT_WIFI_PASSWORD",
    "DEFAULT_WIFI_SSID",
    "DEFAULT_WIFI_WRONG_PASSWORD",
    "OTA_TIMEOUT",
    "SERIAL_PORT",
    "SERIAL_TIMEOUT",
    "WIFI_CONNECT_TIMEOUT",
    "WIFI_MISSING_SSID",
    "WIFI_PASSWORD",
    "WIFI_SSID",
    "WIFI_WRONG_PASSWORD",
    "resolve_wifi_credentials",
]
