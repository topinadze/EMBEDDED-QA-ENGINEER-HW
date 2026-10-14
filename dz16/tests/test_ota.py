from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from typing import Any

import allure
import pytest

from detect_firmware import parse_firmware_version
from drivers.device_driver import DeviceDriver
from manual_checks import prepare_observation


OTA_UPDATE_CASES = (
    pytest.param("1.3.0", "ota update", "1.4.0", id="stable-1.3-to-1.4"),
    pytest.param("1.4.0", "ota update beta", "1.5.0", id="beta-1.4-to-1.5"),
)
OTA_CURRENT_CHANNELS = (
    pytest.param("1.4.0", "ota update", "stable", id="stable-already-current"),
    pytest.param("1.5.0", "ota update beta", "beta", id="beta-already-current"),
)
def _response(lines: list[str]) -> str:
    return "\n".join(lines)


def _partition_state(lines: list[str]) -> tuple[str, str, str]:
    match = re.search(
        r"\bpartition:\s*(ota_\d+)\s*@\s*(0x[0-9a-f]+),\s*state:\s*([a-z ]+)",
        _response(lines),
        re.IGNORECASE,
    )
    assert match is not None, f"Could not parse active OTA partition: {lines!r}"
    return (
        match.group(1).casefold(),
        match.group(2).casefold(),
        match.group(3).casefold(),
    )


def _has_usable_ipv4(status: dict[str, object]) -> bool:
    try:
        address = ipaddress.ip_address(str(status["ip"]))
    except ValueError:
        return False
    return (
        isinstance(address, ipaddress.IPv4Address)
        and address.packed[0] != 0
        and not (
            address.is_unspecified
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        )
    )


@pytest.mark.parametrize(
    "ip,expected",
    (
        pytest.param("10.123.30.49", True, id="private-lan"),
        pytest.param("127.0.0.1", False, id="loopback"),
        pytest.param("169.254.1.2", False, id="link-local"),
        pytest.param("224.0.0.1", False, id="multicast"),
        pytest.param("0.0.0.1", False, id="zero-network"),
        pytest.param("240.0.0.1", False, id="reserved"),
        pytest.param("::1", False, id="ipv6"),
        pytest.param(None, False, id="missing"),
    ),
)
@pytest.mark.ota
def test_usable_ipv4_guard(ip: str | None, expected: bool) -> None:
    assert _has_usable_ipv4({"ip": ip}) is expected


@pytest.mark.parametrize(
    "lines,expected",
    (
        pytest.param(
            ["I (16111) wifi station: FW: v1.3.0 (build Sep 29 2026 14:15:56)"],
            "1.3.0",
            id="firmware-1.3.0",
        ),
        pytest.param(
            ["I (16111) wifi station: FW: v1.4.0 (build Sep 29 2026 14:16:47)"],
            "1.4.0",
            id="firmware-1.4.0",
        ),
        pytest.param(
            ["I (16111) wifi station: FW: v1.5.0 (build Sep 29 2026 15:23:09)"],
            "1.5.0",
            id="firmware-1.5.0",
        ),
    ),
)
@pytest.mark.ota
def test_detect_firmware_parser(lines: list[str], expected: str) -> None:
    assert parse_firmware_version(lines) == expected


@pytest.mark.ota
def test_detect_firmware_parser_rejects_missing_or_unsupported_version() -> None:
    with pytest.raises(ValueError, match="Could not parse"):
        parse_firmware_version(["version", "FW output missing"])
    with pytest.raises(ValueError, match="Unsupported firmware version 2.0.0"):
        parse_firmware_version(["FW: v2.0.0"])


@pytest.mark.ota
def test_run_ota_returns_on_check_failure_without_waiting_for_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    failure = [
        "E esp-tls: getaddrinfo() returns 202",
        "E wifi station: [OTA] check failed: cannot read stable.txt",
    ]
    monkeypatch.setattr(driver, "send_command", lambda command, timeout: failure)
    monkeypatch.setattr(
        driver,
        "_read_for",
        lambda timeout: pytest.fail("run_ota should not wait after check failure"),
    )

    result = driver.run_ota("ota update", timeout=180.0)

    assert result == failure


@pytest.mark.ota
def test_ota_connectivity_retry_recovers_after_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    responses = iter(
        (
            [
                "E esp-tls: couldn't get hostname for :raw.githubusercontent.com",
                "E wifi station: [OTA] check failed: cannot read stable.txt",
            ],
            ["I wifi station: [OTA] self-check passed"],
        )
    )
    calls: list[str] = []

    def run_ota(command: str, timeout: float) -> list[str]:
        calls.append(command)
        return next(responses)

    monkeypatch.setattr(driver, "run_ota", run_ota)
    monkeypatch.setattr(
        driver,
        "wifi_status",
        lambda: {
            "connected": True,
            "ssid": "test-network",
            "ip": "192.168.1.2",
            "rssi": -40,
        },
    )

    result = driver.run_ota_with_connectivity_retry(
        "ota update", attempts=2, retry_delay=0
    )

    assert result == ["I wifi station: [OTA] self-check passed"]
    assert calls == ["ota update", "ota update"]


@pytest.mark.ota
def test_ota_connectivity_retry_restores_wifi_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    responses = iter(
        (
            [
                "E esp-tls: getaddrinfo() returns 202",
                "E wifi station: [OTA] check failed: cannot read stable.txt",
            ],
            ["I wifi station: [OTA] self-check passed"],
        )
    )
    reconnect_calls = 0

    monkeypatch.setattr(
        driver, "run_ota", lambda command, timeout: next(responses)
    )
    monkeypatch.setattr(driver, "wifi_status", lambda: {"connected": False})

    def reconnect() -> bool:
        nonlocal reconnect_calls
        reconnect_calls += 1
        return True

    monkeypatch.setattr(driver, "wifi_connect_saved", reconnect)

    result = driver.run_ota_with_connectivity_retry(
        "ota update", attempts=2, retry_delay=0
    )

    assert result == ["I wifi station: [OTA] self-check passed"]
    assert reconnect_calls == 1


@pytest.mark.ota
def test_ota_connectivity_retry_fails_fast_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    calls = 0

    def run_ota(command: str, timeout: float) -> list[str]:
        nonlocal calls
        calls += 1
        return [
            "E esp-tls: getaddrinfo() returns 202",
            "E wifi station: [OTA] check failed: cannot read stable.txt",
        ]

    monkeypatch.setattr(driver, "run_ota", run_ota)
    monkeypatch.setattr(
        driver,
        "wifi_status",
        lambda: {
            "connected": True,
            "ssid": "test-network",
            "ip": "192.168.1.2",
            "rssi": -40,
        },
    )

    with pytest.raises(ConnectionError, match="after 2 attempts"):
        driver.run_ota_with_connectivity_retry(
            "ota update", attempts=2, retry_delay=0
        )

    assert calls == 2


def _assert_successful_update(
    driver: DeviceDriver,
    lines: list[str],
    old_version: str,
    new_version: str,
    active_partition: str,
) -> None:
    output = _response(lines)
    target_partition = "ota_1" if active_partition == "ota_0" else "ota_0"
    assert re.search(
        rf"\[OTA\]\s*target partition:\s*{target_partition}\b",
        output,
        re.IGNORECASE,
    ), f"OTA did not target the inactive partition {target_partition}:\n{output}"
    assert re.search(
        r"\[OTA\]\s*downloading:\s*https?://\S+",
        output,
        re.IGNORECASE,
    ), f"OTA did not report its download URL:\n{output}"
    assert re.search(
        rf"\[OTA\]\s*new version:\s*{re.escape(new_version)}\b",
        output,
        re.IGNORECASE,
    ), f"OTA did not report target version {new_version}:\n{output}"
    assert f"[OTA] success: {old_version} -> {new_version}" in output, (
        f"OTA output did not confirm the expected version transition:\n{output}"
    )
    for percentage in range(10, 101, 10):
        assert re.search(rf"\[OTA\] progress:\s*{percentage}%", output), (
            f"OTA output omitted the {percentage}% progress event."
        )
    assert "[OTA] self-check passed" in output, (
        "The new firmware did not report a successful self-check."
    )

    with allure.step("Verify the reported firmware and active partition after OTA"):
        version_lines = driver.send_command("version")
        assert driver.get_firmware_version(version_lines) == new_version
        _, _, state = _partition_state(version_lines)
        assert state == "valid", f"New firmware partition is not valid: {version_lines!r}"


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("Over-the-air updates")
@pytest.mark.ota
class TestOta:
    @allure.story("OTA-1: Running firmware and active partition")
    @allure.title("Version reports the running firmware and a valid OTA partition")
    def test_version_reports_active_partition(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        lines = device_driver.send_command("version")
        assert device_driver.get_firmware_version(lines) == firmware_version
        partition, address, state = _partition_state(lines)
        assert partition in {"ota_0", "ota_1"}
        assert address.startswith("0x")
        assert state == "valid", f"Active firmware is not valid: {lines!r}"

    @allure.story("OTA-2: Stable and beta channels")
    @allure.title("OTA check reports the running version and both update channels")
    def test_ota_check_reports_channel_versions(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        wifi_connected: None,
    ) -> None:
        with allure.step("Read the current version and OTA channels"):
            output = _response(device_driver.send_command("ota check", timeout=8.0))
        assert re.search(
            rf"\[OTA\]\s*current version:\s*{re.escape(firmware_version)}\b",
            output,
            re.IGNORECASE,
        ), f"OTA check did not report current firmware {firmware_version}:\n{output}"
        assert re.search(
            r"\[OTA\]\s*stable channel:\s*1\.4\.0\b", output, re.IGNORECASE
        ), f"OTA check did not report stable 1.4.0:\n{output}"
        assert re.search(
            r"\[OTA\]\s*beta channel:\s*1\.5\.0\b", output, re.IGNORECASE
        ), f"OTA check did not report beta 1.5.0:\n{output}"

    @allure.story("OTA-3: Current channel requires no download")
    @allure.title("{channel} update on {source_version} is already up to date")
    @pytest.mark.parametrize(
        "source_version,command,channel", OTA_CURRENT_CHANNELS
    )
    def test_current_channel_is_not_reinstalled(
        self,
        source_version: str,
        command: str,
        channel: str,
        device_driver: DeviceDriver,
        firmware_version: str,
        wifi_connected: None,
    ) -> None:
        if firmware_version != source_version:
            pytest.skip(f"This no-op scenario requires firmware {source_version}.")

        before = _partition_state(device_driver.send_command("version"))
        lines = device_driver.run_ota(command, timeout=8.0)
        output = _response(lines).casefold()
        assert "[ota] already up to date" in output or (
            f"up to date ({channel})" in output
        ), f"OTA did not report the current {channel} channel as up to date:\n{output}"
        assert "[ota] progress:" not in output, (
            "An up-to-date channel unexpectedly started an OTA download."
        )
        assert _partition_state(device_driver.send_command("version")) == before

    @allure.story("OTA-4: Downgrades require force")
    @allure.title("Installing an older version without force is blocked")
    @pytest.mark.parametrize(
        "source_version", ("1.4.0", "1.5.0"), ids=("from-1.4", "from-1.5")
    )
    def test_downgrade_without_force_is_blocked(
        self,
        source_version: str,
        device_driver: DeviceDriver,
        firmware_version: str,
        wifi_connected: None,
    ) -> None:
        if firmware_version != source_version:
            pytest.skip(f"This downgrade scenario requires firmware {source_version}.")

        before = _partition_state(device_driver.send_command("version"))
        lines = device_driver.run_ota("ota install 1.3.0", timeout=8.0)
        output = _response(lines)
        assert (
            f"[OTA] downgrade blocked: {firmware_version} -> 1.3.0. "
            "Use 'ota install <ver> force'"
        ) in output, f"OTA did not block the downgrade:\n{output}"
        assert _partition_state(device_driver.send_command("version")) == before

    @allure.story("OTA-7: OTA requires Wi-Fi")
    @allure.title("OTA update without Wi-Fi is rejected without changing firmware")
    def test_ota_update_without_wifi_is_rejected(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        before = _partition_state(device_driver.send_command("version"))
        device_driver.wifi_disconnect()
        disconnected_status = device_driver.wifi_status()
        if disconnected_status.get("connected"):
            # Due to BUG-01, disconnect leaves internal state dirty; reboot to ensure clean offline state
            assert device_driver.reboot(), "Device did not reboot cleanly."
            disconnected_status = device_driver.wifi_status()
        if _has_usable_ipv4(disconnected_status):
            pytest.fail(
                "Wi-Fi disconnect precondition failed; refusing to issue OTA "
                f"while the board still reports an active IP: {disconnected_status!r}"
            )

        for command in ("ota check", "ota update beta"):
            lines = device_driver.run_ota(command, timeout=8.0)
            output = _response(lines)
            assert (
                "[OTA] failed: WiFi not connected. Use 'connect' first." in output
            ), f"{command!r} did not reject the disconnected state:\n{output}"
        assert _partition_state(device_driver.send_command("version")) == before

    @allure.story("OTA-5/OTA-9: Download, self-check, and activation")
    @allure.title("OTA update {source_version} to {target_version} completes and validates")
    @pytest.mark.parametrize(
        "source_version,command,target_version", OTA_UPDATE_CASES
    )
    @pytest.mark.persistent
    def test_available_update_completes_self_check(
        self,
        source_version: str,
        command: str,
        target_version: str,
        device_driver: DeviceDriver,
        firmware_version: str,
        wifi_connected: None,
    ) -> None:
        if firmware_version != source_version:
            pytest.skip(f"This update scenario requires firmware {source_version}.")
        before = _partition_state(device_driver.send_command("version"))
        lines = device_driver.run_ota_with_connectivity_retry(
            command, timeout=180.0
        )
        _assert_successful_update(
            device_driver, lines, source_version, target_version, before[0]
        )

    @allure.story("OTA-4: Forced downgrade and firmware validation")
    @allure.title("Forced OTA downgrade from {source_version} to {target_version} completes")
    @pytest.mark.parametrize(
        "source_version,target_version",
        (
            pytest.param("1.5.0", "1.4.0", id="from-1.5-to-1.4"),
            pytest.param("1.4.0", "1.3.0", id="from-1.4-to-1.3"),
        ),
    )
    @pytest.mark.persistent
    def test_forced_downgrade_completes_self_check(
        self,
        source_version: str,
        target_version: str,
        device_driver: DeviceDriver,
        firmware_version: str,
        wifi_connected: None,
    ) -> None:
        assert firmware_version == source_version, (
            f"Expected source firmware {source_version}, got {firmware_version}."
        )
        before = _partition_state(device_driver.send_command("version"))
        with allure.step(
            f"Force-install firmware {target_version} over {source_version}"
        ):
            lines = device_driver.run_ota_with_connectivity_retry(
                f"ota install {target_version} force", timeout=180.0
            )
        _assert_successful_update(
            device_driver, lines, source_version, target_version, before[0]
        )

    @allure.story("OTA-6: Retry after Wi-Fi interruption")
    @allure.title("OTA succeeds on retry after an interrupted download without reboot")
    @allure.issue(
        "BUG-06",
        name="An interrupted OTA may leave the update operation locked.",
    )
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_interrupted_download_can_be_retried(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Callable[[str], None],
        wifi_connected: None,
        reboot_after_ota_lock: None,
    ) -> None:
        if firmware_version != "1.5.0":
            pytest.skip("This interactive retry scenario is scoped to firmware 1.5.0.")
        initial_partition = _partition_state(device_driver.send_command("version"))[0]

        prepare_observation(
            manual_prepare,
            action=(
                "keep the board's Wi-Fi access point reachable; when OTA reaches "
                "10%, switch it off, then restore it when prompted"
            ),
            expected=(
                "'[OTA] failed: download interrupted'; a successful retry will "
                "reflash firmware 1.5.0 and reboot the board"
            ),
            duration="up to 30 seconds for 10% progress and 45 seconds for interruption",
        )
        with allure.step("Start a forced same-version OTA install"):
            device_driver.send_command("ota install 1.5.0 force", timeout=0.2)
            assert device_driver.wait_for("[OTA] progress: 10%", timeout=30.0), (
                "OTA did not reach its first progress event."
            )

        with allure.step("Disconnect Wi-Fi while the OTA download is active"):
            prepare_observation(
                manual_prepare,
                action="turn off the access point used by the board; leave the board powered",
                expected="'[OTA] failed: download interrupted'",
                duration="allow up to 45 seconds; restore the access point at the next prompt",
            )
            interrupted = device_driver.wait_for(
                "[OTA] failed: download interrupted", timeout=45.0
            )

        with allure.step("Restore the Wi-Fi access point before checking the result"):
            prepare_observation(
                manual_prepare,
                action="turn the same Wi-Fi access point back on; do not reboot the board",
                expected="the device reconnects using saved credentials",
                duration="restore within about 30 seconds, then allow up to 10 seconds for reconnect",
            )
            assert interrupted, (
                "OTA did not report the required interrupted-download failure."
            )
            assert device_driver.get_firmware_version(
                device_driver.send_command("version")
            ) == firmware_version, (
                "Firmware version changed after the interrupted download."
            )

        with allure.step("Reconnect using credentials saved on-device"):
            if not device_driver.wifi_connect_saved(timeout=10.0):
                pytest.fail("The saved Wi-Fi connection could not be restored.")
            status = device_driver.wifi_status()
            assert device_driver.wifi_connection_is_valid(status), (
                f"Wi-Fi must be connected before OTA: {status!r}"
            )

        with allure.step("Retry the same OTA install without rebooting the device"):
            retry_lines = device_driver.run_ota(
                "ota install 1.5.0 force", timeout=180.0
            )
            retry_output = _response(retry_lines)
            if "[OTA] error: update already in progress" in retry_output:
                pytest.xfail(
                    "BUG-06: interrupted OTA leaves the update operation locked; "
                    "see dz16/REPORT.md section 5."
                )
            _assert_successful_update(
                device_driver,
                retry_lines,
                "1.5.0",
                "1.5.0",
                initial_partition,
            )

    @allure.story("OTA-12: Demo OTA server")
    @allure.title("OTA test server demonstrates an update and reboots without flashing")
    def test_ota_test_server_does_not_change_firmware(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        wifi_connected: None,
    ) -> None:
        before = _partition_state(device_driver.send_command("version"))
        lines = device_driver.run_ota("ota-test-server", timeout=20.0)
        assert "=== OTA Update Complete. Restarting" in _response(lines)
        assert device_driver.wait_for("ready", timeout=40.0), (
            "Device did not return to the ready prompt after the demo server reboot."
        )
        after_lines = device_driver.send_command("version")
        assert device_driver.get_firmware_version(after_lines) == firmware_version
        assert _partition_state(after_lines) == before

    @allure.story("FR-W1: Wi-Fi station connection")
    @allure.title("Wi-Fi connection is valid before the next OTA transition")
    def test_wifi_connection_can_be_established(
        self,
        device_driver: DeviceDriver,
        wifi_connected: None,
    ) -> None:
        status = device_driver.wifi_status()
        assert device_driver.wifi_connection_is_valid(status), (
            f"Wi-Fi must have a usable IPv4 connection before an OTA transition: "
            f"{status!r}"
        )
