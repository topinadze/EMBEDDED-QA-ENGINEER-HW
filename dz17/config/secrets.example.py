# Copy this file to secrets.py and set your local test credentials.
DEFAULT_WIFI_SSID = "Your_WiFi_SSID"
DEFAULT_WIFI_PASSWORD = "Your_WiFi_Password"

DEFAULT_APP_USER = "sentry_op"
DEFAULT_APP_PASSWORD = "Your_Device_Account_Password"

# Four-digit Guard PIN for local hardware tests.
DEFAULT_GUARD_PIN = ""

# Authorized AU-6 sudo password. It is separate from the account password and is
# not given in the PRD; leave empty to skip the sudo elevation test.
DEFAULT_SUDO_PASSWORD = ""

# Telegram bot credentials for optional smartphone-based operator checks.
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
