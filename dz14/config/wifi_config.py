import os

# Wi-Fi Credentials for testing Part A (station_WiFi)
# Can be overridden via environment variables:
# e.g., $env:TEST_WIFI_SSID="MyHotspot"; $env:TEST_WIFI_PASSWORD="mypassword123"
WIFI_SSID = os.getenv("TEST_WIFI_SSID", "TopA-node")  # Default SSID for testing
WIFI_PASSWORD = os.getenv("TEST_WIFI_PASSWORD", "3423434234")

# Invalid test credentials for negative testing
INVALID_PASSWORD = os.getenv("TEST_INVALID_PASSWORD", "wrong_password123")
SHORT_PASSWORD = "short"  # < 8 characters to trigger FR-W3
NON_EXISTENT_SSID = "NON_EXISTENT_SSID_9999"

# UART / Timing Configurations
SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT = 2.0
WIFI_CONNECT_TIMEOUT = 10.0  # FR-W2 specifies 10s connection timeout
REBOOT_TIMEOUT = 8.0

# BLE Configuration (Part B)
BLE_DEVICE_NAME = "SENTRY-BLE"
BLE_LED_CHAR_UUID = "00001525-1212-efde-1523-785feabcd123"
BLE_RELAY_CHAR_UUID = "00001526-1212-efde-1523-785feabcd123"
