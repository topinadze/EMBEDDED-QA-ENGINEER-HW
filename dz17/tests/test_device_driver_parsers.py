from __future__ import annotations

import pytest
from drivers.device_driver import DeviceDriver


class FakeSerial:
    is_open = True

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.writes: list[bytes] = []

    @property
    def in_waiting(self) -> int:
        return len(self._data)

    def read(self, size: int) -> bytes:
        data, self._data = self._data[:size], self._data[size:]
        return data

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        pass


def test_buffer_len_reports_current_uart_log_size() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.uart_log.extend(["TX > status", "RX < ready"])
    assert driver.buffer_len() == 2


def test_read_for_redacts_sensitive_uart_echo() -> None:
    driver = DeviceDriver(port="DUMMY")
    secret = "not-a-real-password"
    driver._sensitive_uart_values.add(secret)
    driver.serial = FakeSerial(f"echo {secret}\n".encode())  # type: ignore[assignment]

    lines = driver.read_for(timeout=0.02)

    assert lines == ["echo [REDACTED]"]
    assert secret not in "\n".join(lines)
    assert secret not in "\n".join(driver.uart_log)


def test_wait_for_any_matches_uart_phrase_from_buffered_output() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.uart_log.extend(
        [
            "TX > login testUser [REDACTED]",
            "RX < I (1) sentry: [AUTH] operator testUser on watch",
        ]
    )

    result = driver.wait_for_any(
        ("[AUTH] operator testUser on watch", "E209"),
        timeout=0.1,
        since_index=1,
    )

    assert result == "[AUTH] operator testUser on watch"


def test_wait_for_any_reads_uart_until_expected_phrase() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.serial = FakeSerial(
        b"I (1) sentry: wrong login or password (E209)\n"
    )  # type: ignore[assignment]

    result = driver.wait_for_any(
        ("[AUTH] operator testUser on watch", "wrong login or password", "E209"),
        timeout=0.1,
        since_index=0,
    )

    assert result == "wrong login or password"


def test_send_command_nowait_writes_without_waiting_and_redacts_password() -> None:
    driver = DeviceDriver(port="DUMMY")
    serial = FakeSerial(b"")
    driver.serial = serial  # type: ignore[assignment]

    driver.login_nowait("testUser", "secret")

    assert serial.writes == [b"login testUser secret\r\n"]
    assert driver.uart_log == ["TX > [REDACTED]"]


def test_login_nowait_redacts_password_in_prefixed_uart_output() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.serial = FakeSerial(b"I (1) auth accepted secret\n")  # type: ignore[assignment]

    driver.login_nowait("testUser", "secret")
    assert driver.wait_for("auth accepted", timeout=0.1, since_index=1)

    assert "secret" not in "\n".join(driver.uart_log)
    assert "[REDACTED]" in "\n".join(driver.uart_log)


def test_wifi_status_waits_for_link_phrase_and_parses_response() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.serial = FakeSerial(
        b"I (1) sentry:   link: buoy link 'TestAP', "
        b"ip 192.168.1.105, rssi -33 dBm (excellent), ch 1\n"
        b"I (2) sentry:   internet: OK\n"
        b"I (3) sentry:   user: testUser (user)\n"
        b"I (4) sentry:   heap: 251 KB free\n"
    )  # type: ignore[assignment]

    status = driver.wifi_status(timeout=0.2)

    assert status["connected"] is True
    assert status["ssid"] == "TestAP"
    assert status["ip"] == "192.168.1.105"
    assert status["internet"] is True
    assert status["user"] == "testUser"
    assert driver.uart_log[0] == "TX > status"


def test_wifi_reconnect_waits_for_uart_connection_events() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.serial = FakeSerial(
        b"I (1) sentry: [LINK] connected to 'TestAP', rssi -33 dBm\n"
        b"I (2) esp_netif_handlers: sta ip: 192.168.1.105, "
        b"mask 255.255.255.0, gw 192.168.1.1\n"
    )  # type: ignore[assignment]

    assert driver.wifi_reconnect(timeout=0.2) is True
    assert driver.uart_log[0] == "TX > reconnect"


def test_parse_firmware_version() -> None:
    driver = DeviceDriver(port="DUMMY")
    lines = [
        "I (123) sentry: SENTRY SWM-2 sonar watch module, fw v2.1.0 (build Oct  6 2026 02:14:57)",
        "I (124) sentry:   partition: ota_0 @ 0x20000, state: valid",
    ]
    assert driver.get_firmware_version(lines) == "2.1.0"

    lines_status = [
        "I (456) sentry: === SWM-2 status ===",
        "I (456) sentry:   fw:       v2.3.0 (ota_1)",
        "I (456) sentry:   state:    1 NORMAL",
    ]
    assert driver.get_firmware_version(lines_status) == "2.3.0"


def test_parse_state() -> None:
    driver = DeviceDriver(port="DUMMY")
    lines_status = [
        "I (456) sentry: === SWM-2 status ===",
        "I (456) sentry:   fw:       v2.1.0 (ota_0)",
        "I (456) sentry:   state:    2 DEBUG",
    ]
    num, name = driver.parse_state(lines_status)
    assert num == 2
    assert name == "DEBUG"

    lines_transition = [
        "W (8423529) sentry: [STATE] 1 NORMAL -> 3 VERBOSE (by buttons)",
    ]
    num, name = driver.parse_state(lines_transition)
    assert num == 3
    assert name == "VERBOSE"


def test_parse_lamp_status() -> None:
    driver = DeviceDriver(port="DUMMY")
    lines_on = [
        "I (2776723) sentry: [BEACON] ON, color (254,0,0), brightness 100%, mode solid, timer off",
    ]
    status_on = driver.parse_lamp_status(lines_on)
    assert status_on["lamp"] == "on"
    assert status_on["color"] == (254, 0, 0)
    assert status_on["brightness"] == 100
    assert status_on["mode"] == "solid"
    assert status_on["timer_s"] == 0

    lines_countdown = [
        "I (2924963) sentry: [BEACON] ON, color (0,0,255), brightness 50%, mode blink, timer 3 s left",
    ]
    status_timer = driver.parse_lamp_status(lines_countdown)
    assert status_timer["lamp"] == "on"
    assert status_timer["color"] == (0, 0, 255)
    assert status_timer["brightness"] == 50
    assert status_timer["mode"] == "blink"
    assert status_timer["timer_s"] == 3

    lines_off = [
        "I (32) sentry: [BEACON] off, color (255,0,0), brightness 100%, mode solid, timer off",
    ]
    status_off = driver.parse_lamp_status(lines_off)
    assert status_off["lamp"] == "off"
    assert status_off["color"] == (255, 0, 0)


def test_parse_wifi_scan() -> None:
    lines = [
        "I (10) sentry: [LINK] scanning...",
        "I (11) sentry:   [ 1] TestAP - -45 dBm",
        "I (12) sentry:   [ 2] HomeNet - -78 dBm",
        "SSID or number:",
    ]
    aps = DeviceDriver.parse_wifi_scan(lines)
    assert len(aps) == 2
    assert aps[0]["index"] == 1
    assert aps[0]["ssid"] == "TestAP"
    assert aps[0]["rssi"] == -45
    assert aps[1]["index"] == 2
    assert aps[1]["ssid"] == "HomeNet"
    assert aps[1]["rssi"] == -78


def test_parse_wifi_status() -> None:
    lines_connected = [
        "I (10) sentry: === SWM-2 status ===",
        "I (10) sentry:   fw:       v2.1.0 (ota_0)",
        "I (10) sentry:   state:    1 NORMAL",
        "I (10) sentry:   link:     buoy link 'TestAP', ip 192.168.1.105, rssi -33 dBm (excellent), ch 1",
        "I (10) sentry:   internet: OK",
        "I (10) sentry:   user:     operator1 (user)",
    ]
    status = DeviceDriver.parse_wifi_status(lines_connected)
    assert status["connected"] is True
    assert status["ssid"] == "TestAP"
    assert status["ip"] == "192.168.1.105"
    assert status["rssi"] == -33
    assert status["internet"] is True
    assert status["user"] == "operator1"
    assert DeviceDriver.wifi_connection_is_valid(status) is True

    lines_disconnected = [
        "I (20) sentry: === SWM-2 status ===",
        "I (20) sentry:   state: 1 NORMAL",
        "I (20) sentry:   link: buoy link down (known: TestAP)",
        "I (20) sentry:   user: not logged in",
    ]
    status_down = DeviceDriver.parse_wifi_status(lines_disconnected)
    assert status_down["connected"] is False
    assert status_down["ssid"] == "TestAP"
    assert DeviceDriver.wifi_connection_is_valid(status_down) is False


def test_parse_sonar_stats() -> None:
    lines = [
        "I (3307669) sentry: [SONAR] measurements 286, errors 17, min 2.1, max 151.1, avg 21.7 cm",
        "I (3307669) sentry: [SONAR] calibration -2.0 cm, filter median 5, alarm on",
    ]
    driver = DeviceDriver(port="DUMMY")
    # Call driver method with mock send_command
    driver.send_command = lambda cmd, timeout=0.8: lines  # type: ignore[assignment]
    stats = driver.distance_stats()
    assert stats["measurements"] == 286
    assert stats["errors"] == 17
    assert stats["min"] == 2.1
    assert stats["max"] == 151.1
    assert stats["avg"] == 21.7
    assert stats["calibration"] == -2.0
    assert stats["filter"] == 5
    assert stats["alarm"] == "on"

    lines_off = [
        "I (3515309) sentry: [SONAR] measurements 286, errors 17, min 2.1, max 151.1, avg 21.7 cm",
        "I (3515309) sentry: [SONAR] calibration +0.0 cm, filter off, alarm off",
    ]
    driver.send_command = lambda cmd, timeout=0.8: lines_off  # type: ignore[assignment]
    stats_off = driver.distance_stats()
    assert stats_off["filter"] == 0
    assert stats_off["alarm"] == "off"


def test_parse_sonar_stats_without_measurements_keeps_calibration_unknown() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.send_command = lambda cmd, timeout=0.8: [  # type: ignore[assignment]
        "I (1463815) sentry: [SONAR] no measurements yet. Timeouts: 0"
    ]

    stats = driver.distance_stats()

    assert stats["measurements"] == 0
    assert stats["calibration"] is None
    assert stats["filter"] is None
    assert stats["alarm"] is None


def test_driver_redaction() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver._sensitive_uart_values.add("supersecret123")
    assert "supersecret123" not in driver._redact("wifi connect supersecret123")
    assert "[REDACTED]" in driver._redact("wifi connect supersecret123")
    assert "[REDACTED]" in driver._redact("login admin mypass456")
    assert "[REDACTED]" in driver._redact("register user7 secret999")


@pytest.mark.parametrize(
    "command",
    [
        "guard disarm 1234",
        "guard pin 1234 5678",
        "I (1) sentry: guard disarm 1234",
        "I (2) sentry: guard pin 1234 5678",
    ],
)
def test_guard_pin_commands_are_redacted(command: str) -> None:
    redacted = DeviceDriver(port="DUMMY")._redact(command)
    assert "1234" not in redacted
    assert "5678" not in redacted
    assert "[REDACTED]" in redacted


def test_guard_and_alert_helpers_build_commands() -> None:
    driver = DeviceDriver(port="DUMMY")
    commands: list[tuple[str, float]] = []

    def capture(command: str, timeout: float = 0.6) -> list[str]:
        commands.append((command, timeout))
        return [command]

    driver.send_command = capture  # type: ignore[method-assign]

    assert driver.guard_status() == ["guard status"]
    assert driver.guard_set_zone(50) == ["guard zone 50"]
    assert driver.guard_arm(timeout=0.8) == ["guard arm"]
    assert driver.guard_disarm("1234") == ["guard disarm 1234"]
    assert driver.guard_panic(timeout=1.0) == ["guard panic"]
    assert driver.relay_schedule_stop() == ["relay schedule off"]
    assert driver.alert_list() == ["alert list"]
    assert driver.alert_test("critical") == ["alert test critical"]
    assert driver.alert_ack() == ["alert ack"]
    assert driver.alert_ack(42) == ["alert ack 42"]
    assert driver.alert_clear() == ["alert clear"]

    assert commands == [
        ("guard status", 0.6),
        ("guard zone 50", 0.6),
        ("guard arm", 0.8),
        ("guard disarm 1234", 0.6),
        ("guard panic", 1.0),
        ("relay schedule off", 0.6),
        ("alert list", 0.6),
        ("alert test critical", 0.6),
        ("alert ack", 0.6),
        ("alert ack 42", 0.6),
        ("alert clear", 0.6),
    ]


def test_wifi_reconnect_accepts_station_ip_event(monkeypatch) -> None:
    driver = DeviceDriver(port="DUMMY")
    monkeypatch.setattr(
        driver,
        "send_command_nowait",
        lambda command, sensitive=False: None,
    )
    monkeypatch.setattr(
        driver,
        "_read_for",
        lambda timeout: [
            "I (1) sentry: [LINK] connected to 'TestAP'",
            "I (2) esp_netif_handlers: sta ip: 192.0.2.10",
        ],
    )

    assert driver.wifi_reconnect(timeout=0.1)


def test_parse_relay_status() -> None:
    lines = [
        "I (6992779) sentry: [VALVE] OPEN, auto off, cycles 82",
    ]
    driver = DeviceDriver(port="DUMMY")
    driver.send_command = lambda cmd, timeout=0.6: lines  # type: ignore[assignment]
    status = driver.relay_status()
    assert status["state"] == "OPEN"
    assert status["auto"] == "off"
    assert status["cycles"] == 82


def test_relay_status_rejects_unparsed_uart_response() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.send_command = lambda cmd, timeout=0.6: ["unexpected response"]  # type: ignore[assignment]

    with pytest.raises(AssertionError, match="No relay status found"):
        driver.relay_status()


def test_parse_whoami() -> None:
    driver = DeviceDriver(port="DUMMY")
    driver.send_command = lambda cmd, timeout=0.6: ["I (1) sentry: user: operator1, access: user"]  # type: ignore[assignment]
    who = driver.whoami()
    assert who["user"] == "operator1"
    assert who["access"] == "user"
    assert who["logged_in"] is True

    driver.send_command = lambda cmd, timeout=0.6: ["I (2) sentry: user: not logged in"]  # type: ignore[assignment]
    who_logged_out = driver.whoami()
    assert who_logged_out["logged_in"] is False
