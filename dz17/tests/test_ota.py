from __future__ import annotations

import ipaddress
import re
import sys
import time
from collections.abc import Callable, Iterator
from typing import Any

import allure
import pytest

from detect_firmware import parse_firmware_version
from config.test_config import resolve_wifi_credentials
from drivers.device_driver import OTA_BOOT_READY_MARKER, DeviceDriver
from manual_checks import prepare_observation


OTA_UPDATE_CASES = (
    pytest.param("2.1.0", "ota update beta", "2.3.0", id="beta-2.1-to-2.3"),
)
OTA_DOWNGRADE_CASES = (
    pytest.param("2.3.0", "ota install 2.1.0 force", "2.1.0", id="force-downgrade-2.3-to-2.1"),
)
OTA_CURRENT_CHANNELS = (
    pytest.param("2.1.0", "ota update", "stable", id="stable-already-current"),
    pytest.param("2.3.0", "ota update beta", "beta", id="beta-already-current"),
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
    ip_val = status.get("ip")
    if not ip_val:
        return False
    try:
        address = ipaddress.ip_address(str(ip_val))
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


def _ensure_saved_wifi_connected(
    driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> None:
    ssid, _ = resolve_wifi_credentials(
        ssid_override=request.config.getoption("--wifi-ssid"),
        password_override=request.config.getoption("--wifi-password"),
    )
    if not ssid:
        pytest.fail(
            "This test requires a configured target Wi-Fi SSID to verify "
            "saved-profile restoration without replacing persistent settings."
        )

    def is_target_connection(status: dict[str, Any]) -> bool:
        return DeviceDriver.wifi_connection_is_valid(status) and (
            status.get("ssid") == ssid
        )

    status = driver.wifi_status()
    if not is_target_connection(status):
        driver.wifi_reconnect(timeout=20.0)
        status = driver.wifi_status()
    assert is_target_connection(status), (
        "Could not restore the configured Wi-Fi connection through the saved "
        f"profile without modifying persistent credentials: {status!r}"
    )


def _ota_server_setting(lines: list[str]) -> str:
    match = re.search(
        r"\[OTA\]\s*server:\s*(\S+)(?:\s+\((default)\))?",
        _response(lines),
        re.IGNORECASE,
    )
    assert match is not None, f"Could not parse OTA server setting: {lines!r}"
    return "default" if match.group(2) else match.group(1)


# ---------------------------------------------------------------------------
# Offline Helper / Parser Unit Tests (Run without hardware)
# ---------------------------------------------------------------------------


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
            [
                "I (1234) sentry: SENTRY SWM-2 sonar watch module, fw v2.1.0 (build Oct 6 2026)",
                "I (1234) sentry:   partition: ota_0 @ 0x20000, state: valid",
            ],
            "2.1.0",
            id="sentry-swm2-2.1.0",
        ),
        pytest.param(
            [
                "I (1234) sentry: SENTRY SWM-2 sonar watch module, fw v2.3.0 (build Oct 6 2026)",
                "I (1234) sentry:   partition: ota_1 @ 0x1a0000, state: valid",
            ],
            "2.3.0",
            id="sentry-swm2-2.3.0",
        ),
        pytest.param(
            ["I (100) sentry: fw: v2.1.0 (ota_0)"],
            "2.1.0",
            id="status-fw-2.1.0",
        ),
        pytest.param(
            ["I (100) sentry: fw: v2.3.0 (ota_1)"],
            "2.3.0",
            id="status-fw-2.3.0",
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
    with pytest.raises(ValueError, match="Unsupported firmware version 3.0.0"):
        parse_firmware_version(["FW: v3.0.0"])


@pytest.mark.ota
def test_ota_success_stages_must_be_observed_in_order() -> None:
    output = "\n".join(
        (
            "[OTA] 100%",
            "[OTA] success: v2.1.0 -> v2.3.0 in 18 s. Rebooting...",
            "[OTA] new firmware, PENDING_VERIFY - self-check...",
            "[OTA] self-check passed, firmware marked VALID",
            "ready. state 1 NORMAL (patrol). Type 'help'",
        )
    )

    _assert_ota_success_stages_in_order(output, "2.1.0", "2.3.0")

    out_of_order_output = output.replace(
        "[OTA] success: v2.1.0 -> v2.3.0 in 18 s. Rebooting...\n",
        "",
    ).replace(
        "[OTA] 100%\n",
        "[OTA] success: v2.1.0 -> v2.3.0 in 18 s. Rebooting...\n[OTA] 100%\n",
    )
    with pytest.raises(AssertionError, match="installation success"):
        _assert_ota_success_stages_in_order(
            out_of_order_output,
            "2.1.0",
            "2.3.0",
        )


@pytest.mark.ota
def test_run_ota_returns_on_check_failure_without_waiting_for_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    failure = [
        "E esp-tls: getaddrinfo() returns 202",
        "E sentry: [OTA] check failed: cannot read stable.txt",
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
def test_run_ota_waits_for_device_ready_after_same_version_reinstall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    reads = iter(
        (
            ["I sentry: [OTA] success: v2.1.0 -> v2.1.0. Rebooting..."],
            ["I sentry: [OTA] self-check passed, firmware marked VALID"],
            ["I sentry: ready. state 1 NORMAL (patrol). Type 'help'"],
        )
    )
    monkeypatch.setattr(
        driver,
        "send_command",
        lambda command, timeout: ["W sentry: W409 same version v2.1.0 - reinstalling"],
    )
    monkeypatch.setattr(driver, "_read_for", lambda timeout: next(reads))

    result = driver.run_ota("ota update", timeout=180.0)

    assert any("W409 same version" in line for line in result)
    assert any("success: v2.1.0 -> v2.1.0" in line for line in result)
    assert any("self-check passed" in line for line in result)
    assert any(
        "ready. state 1 NORMAL (patrol). Type 'help'" in line for line in result
    )


@pytest.mark.ota
def test_ota_connectivity_retry_recovers_after_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    responses = iter(
        (
            [
                "E esp-tls: couldn't get hostname for :raw.githubusercontent.com",
                "E sentry: [OTA] check failed: cannot read stable.txt",
            ],
            ["I sentry: [OTA] self-check passed"],
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
        "ota update beta", attempts=2, retry_delay=0
    )

    assert result == ["I sentry: [OTA] self-check passed"]
    assert calls == ["ota update beta", "ota update beta"]


@pytest.mark.ota
def test_ota_connectivity_retry_restores_wifi_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = DeviceDriver("unused")
    responses = iter(
        (
            [
                "E esp-tls: getaddrinfo() returns 202",
                "E sentry: [OTA] check failed: cannot read stable.txt",
            ],
            ["I sentry: [OTA] self-check passed"],
        )
    )
    reconnect_calls = 0

    monkeypatch.setattr(driver, "run_ota", lambda command, timeout: next(responses))
    monkeypatch.setattr(driver, "wifi_status", lambda: {"connected": False})

    def reconnect() -> bool:
        nonlocal reconnect_calls
        reconnect_calls += 1
        return True

    monkeypatch.setattr(driver, "wifi_reconnect", reconnect)

    result = driver.run_ota_with_connectivity_retry(
        "ota update beta", attempts=2, retry_delay=0
    )

    assert result == ["I sentry: [OTA] self-check passed"]
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
            "E sentry: [OTA] check failed: cannot read stable.txt",
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
            "ota update beta", attempts=2, retry_delay=0
        )

    assert calls == 2


# ---------------------------------------------------------------------------
# Device-Facing OTA Test Suite
# ---------------------------------------------------------------------------


def _assert_ota_success_stages_in_order(
    output: str,
    old_version: str,
    new_version: str,
) -> None:
    stages = (
        ("download completion", r"\[OTA\]\s*100%"),
        (
            "installation success",
            rf"\[OTA\]\s*success:\s*v?{re.escape(old_version)}\s*->\s*"
            rf"v?{re.escape(new_version)}",
        ),
        (
            "self-check start",
            r"\[OTA\]\s*new firmware,\s*PENDING_VERIFY\s*-\s*self-check\.\.\.",
        ),
        (
            "self-check success",
            r"\[OTA\]\s*self-check passed,\s*firmware marked VALID",
        ),
        ("device ready", re.escape(OTA_BOOT_READY_MARKER)),
    )
    search_from = 0
    for stage, pattern in stages:
        match = re.search(pattern, output[search_from:], re.IGNORECASE)
        assert match is not None, (
            f"OTA output did not report {stage} after the preceding stage:\n{output}"
        )
        search_from += match.end()


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
        rf"\[OTA\]\s*.*target partition\s*{target_partition}\b",
        output,
        re.IGNORECASE,
    ), f"OTA did not target the inactive partition {target_partition}:\n{output}"
    assert re.search(
        r"\[OTA\]\s*downloading\s*https?://\S+",
        output,
        re.IGNORECASE,
    ), f"OTA did not report its download URL:\n{output}"
    assert re.search(
        rf"\[OTA\]\s*image:\s*sentry_fw7\s*v?{re.escape(new_version)}\b",
        output,
        re.IGNORECASE,
    ), f"OTA did not report target version {new_version}:\n{output}"
    assert re.search(
        rf"\[OTA\]\s*success:\s*v?{re.escape(old_version)}\s*->\s*v?{re.escape(new_version)}",
        output,
        re.IGNORECASE,
    ), f"OTA output did not confirm the expected version transition:\n{output}"
    for percentage in range(10, 101, 10):
        assert re.search(rf"\[OTA\]\s*{percentage}%", output), (
            f"OTA output omitted the {percentage}% progress event."
        )
    assert "self-check passed" in output.casefold(), (
        "The new firmware did not report a successful self-check."
    )
    assert OTA_BOOT_READY_MARKER.casefold() in output.casefold(), (
        "The new firmware did not report its complete ready state."
    )
    _assert_ota_success_stages_in_order(output, old_version, new_version)

    with allure.step("Verify the reported firmware and active partition after OTA"):
        version_lines = driver.send_command("version")
        assert driver.get_firmware_version(version_lines) == new_version
        part, _, state = _partition_state(version_lines)
        assert part == target_partition, f"Expected active partition {target_partition}, got {part}"
        assert state == "valid", f"New firmware partition is not valid: {version_lines!r}"


pytestmark = [
    allure.parent_suite("DZ17"),
    allure.suite("Over-the-Air Firmware Updates"),
    allure.epic("SENTRY SWM-2"),
    allure.feature("OTA Updates (OTA-1 - OTA-12)"),
]


@pytest.fixture
def restore_authenticated_session_after_test(
    device_driver: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
    request: pytest.FixtureRequest,
) -> Iterator[DeviceDriver]:
    """Establish and restore the configured user session around access checks."""
    _ensure_saved_wifi_connected(device_driver, request)
    ensure_authenticated_device(device_driver)
    identity = device_driver.whoami()
    if identity["access"] == "debug":
        device_driver.logout()
        ensure_authenticated_device(device_driver)
        identity = device_driver.whoami()
    assert identity["logged_in"] and identity["access"] == "user", (
        f"Expected user-level access before OTA access checks: {identity!r}"
    )
    yield device_driver
    with allure.step("Restore authenticated session after the OTA check"):
        _ensure_saved_wifi_connected(device_driver, request)
        identity = device_driver.whoami()
        if identity["logged_in"] and identity["access"] == "debug":
            device_driver.logout()
        ensure_authenticated_device(device_driver)
        identity = device_driver.whoami()
        assert identity["logged_in"] and identity["access"] == "user", (
            f"Could not restore user-level access after OTA check: {identity!r}"
        )


@pytest.fixture
def restore_wifi_connection_after_test(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Iterator[DeviceDriver]:
    """Establish and restore Wi-Fi through the existing saved profile."""
    _ensure_saved_wifi_connected(device_driver, request)
    yield device_driver
    with allure.step("Restore Wi-Fi connection after the OTA check"):
        _ensure_saved_wifi_connected(device_driver, request)


@pytest.fixture
def restore_ota_server_after_test(
    restore_authenticated_session_after_test: DeviceDriver,
) -> Iterator[tuple[DeviceDriver, str]]:
    """Restore the captured OTA server setting after the case."""
    driver = restore_authenticated_session_after_test
    original_server = _ota_server_setting(driver.ota_server(timeout=3.0))
    yield driver, original_server

    with allure.step(f"Restore OTA server setting to {original_server!r}"):
        driver.ota_server(original_server, timeout=3.0)
        restored_server = _ota_server_setting(driver.ota_server(timeout=3.0))
        assert restored_server == original_server, (
            f"OTA server cleanup expected {original_server!r}, "
            f"but read back {restored_server!r}."
        )


@pytest.fixture
def restore_wifi_after_interrupted_ota(
    device_driver: DeviceDriver,
    manual_prepare: Any,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Callable[[], None], Callable[[], None]]]:
    """Restore connectivity and authentication after the AP is disabled."""
    _ensure_saved_wifi_connected(device_driver, request)
    ensure_authenticated_device(device_driver)
    ap_was_disabled = False
    ap_restored = False

    def mark_ap_disabled() -> None:
        nonlocal ap_was_disabled
        ap_was_disabled = True

    def mark_ap_restored() -> None:
        nonlocal ap_restored
        ap_restored = True

    yield mark_ap_disabled, mark_ap_restored

    if ap_was_disabled:
        with allure.step("Restore Wi-Fi access and authenticated session during teardown"):
            if not ap_restored:
                prepare_observation(
                    manual_prepare,
                    action=(
                        "turn the test Wi-Fi access point back on; "
                        "keep the board powered"
                    ),
                    expected="device reconnects and reports valid Wi-Fi connection",
                    duration="allow up to 20 seconds",
                )
            _ensure_saved_wifi_connected(device_driver, request)
            ensure_authenticated_device(device_driver)


@allure.sub_suite("OTA Verification")
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

    @allure.story("OTA-2: Partition status inspection")
    @allure.title("OTA status reports running partition and previous partition")
    def test_ota_status_reports_partitions(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = authenticated_device
        status = driver.ota_status()
        assert status["running_version"] == firmware_version, (
            f"Expected running version {firmware_version}, got {status['running_version']}"
        )
        assert status["running_partition"] in {"ota_0", "ota_1"}, (
            f"Invalid running partition: {status['running_partition']}"
        )
        if status["running_state"] is not None:
            assert status["running_state"].casefold() == "valid"

    @allure.story("OTA-3: Stable and beta channels")
    @allure.title("OTA check reports running version, stable 2.1.0, and beta 2.3.0")
    def test_ota_check_reports_channel_versions(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = authenticated_device
        with allure.step("Read the current version and OTA channels"):
            check_data = driver.ota_check()

        assert check_data["current"] == firmware_version, (
            f"Expected current {firmware_version}, got {check_data['current']}"
        )
        assert check_data["stable"] == "2.1.0", (
            f"Expected stable channel 2.1.0, got {check_data['stable']}"
        )
        assert check_data["beta"] == "2.3.0", (
            f"Expected beta channel 2.3.0, got {check_data['beta']}"
        )
        assert check_data["status"] is not None, "OTA check did not report channel status line"

    @allure.story("OTA-4: Current channel requires no download")
    @allure.title("Beta update on 2.3.0 is already up to date without downloading")
    def test_beta_update_on_current_beta_is_noop(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        if firmware_version != "2.3.0":
            pytest.skip("Beta up-to-date no-op scenario requires firmware 2.3.0.")

        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        lines = driver.run_ota("ota update beta", timeout=8.0)
        output = _response(lines).casefold()

        assert "[ota] already up to date" in output or "up to date (beta)" in output, (
            f"OTA did not report beta channel as up to date:\n{output}"
        )
        assert "[ota] progress:" not in output and "[ota]  10%" not in output, (
            "An up-to-date channel unexpectedly started an OTA download."
        )
        assert _partition_state(driver.send_command("version")) == before

    @allure.story("OTA-4: Current channel requires no download")
    @allure.title("Stable update on 2.1.0 is already up to date without downloading")
    @pytest.mark.xfail(
        reason="BUG-015: ota update on 2.1.0 reinstalls current version instead of no-op",
        strict=True,
    )
    @pytest.mark.persistent
    def test_stable_update_on_current_stable_is_noop(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        if firmware_version != "2.1.0":
            pytest.skip("Stable up-to-date no-op scenario requires firmware 2.1.0.")

        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        lines = driver.run_ota("ota update", timeout=180.0)
        output = _response(lines).casefold()

        assert "[ota] already up to date" in output or "up to date (stable)" in output, (
            f"OTA did not report stable channel as up to date:\n{output}"
        )
        assert "[ota] progress:" not in output and "[ota]  10%" not in output, (
            "An up-to-date channel unexpectedly started an OTA download."
        )
        assert _partition_state(driver.send_command("version")) == before

    @allure.story("OTA-5: Version string validation")
    @allure.title("Installing malformed version '{version_str}' is rejected with E414")
    @pytest.mark.parametrize("version_str", ["2.1", "2.1.0.0", "abc"])
    def test_ota_install_invalid_version_format(
        self,
        authenticated_device: DeviceDriver,
        version_str: str,
    ) -> None:
        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        lines = driver.run_ota(f"ota install {version_str}", timeout=6.0)
        output = _response(lines)

        assert "E414" in output, (
            f"Malformed version {version_str!r} did not return E414:\n{output}"
        )
        assert "Format: X.Y.Z" in output or "bad version" in output.casefold(), (
            f"Output did not explain expected format:\n{output}"
        )
        assert _partition_state(driver.send_command("version")) == before

    @allure.story("OTA-5: Unavailable version on server")
    @allure.title("Installing nonexistent version 999.999.999 returns E415")
    def test_ota_install_nonexistent_version(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        lines = driver.run_ota("ota install 999.999.999", timeout=12.0)
        output = _response(lines)

        assert "E415" in output, (
            f"Nonexistent version did not return E415:\n{output}"
        )
        assert "not found on server" in output.casefold(), (
            f"Output did not confirm version not found on server:\n{output}"
        )
        assert _partition_state(driver.send_command("version")) == before

    @allure.story("OTA-5: Downgrades require force")
    @allure.title("Installing older version 2.1.0 without force is blocked with E408")
    def test_downgrade_without_force_is_blocked(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        if firmware_version != "2.3.0":
            pytest.skip("Downgrade check requires active firmware 2.3.0.")

        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        lines = driver.run_ota("ota install 2.1.0", timeout=8.0)
        output = _response(lines)

        assert "E408" in output or "downgrade blocked" in output.casefold(), (
            f"OTA did not block the downgrade with E408:\n{output}"
        )
        assert "ota install 2.1.0 force" in output or "force" in output.casefold(), (
            f"Output did not advise using force for downgrade:\n{output}"
        )
        assert _partition_state(driver.send_command("version")) == before

    @allure.story("OTA-11: Custom URL scheme validation")
    @allure.title("Installing from non-HTTP URL is rejected with E418")
    def test_ota_url_rejects_non_http(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        lines = driver.run_ota("ota url ftp://invalid.local/fw7.bin", timeout=5.0)
        output = _response(lines)

        assert "E418" in output, (
            f"Non-HTTP URL was not rejected with E418:\n{output}"
        )
        assert "http://" in output or "https://" in output, (
            f"Output did not specify required URL schemes:\n{output}"
        )
        assert _partition_state(driver.send_command("version")) == before

    @allure.story("OTA-12: Configurable update server")
    @allure.title("Setting OTA server to default returns GitHub default URL")
    def test_ota_server_default(
        self,
        restore_ota_server_after_test: tuple[DeviceDriver, str],
    ) -> None:
        driver, _ = restore_ota_server_after_test
        lines = driver.ota_server("default", timeout=3.0)
        output = _response(lines)

        assert "raw.githubusercontent.com/BohdanHorbanych/esp32-ota-files/main/fw7/" in output, (
            f"OTA server default did not report expected GitHub URL:\n{output}"
        )
        assert "(default)" in output.casefold(), (
            f"OTA server output did not confirm '(default)':\n{output}"
        )

    @allure.story("AC-1: Access control for OTA")
    @allure.title("OTA commands while logged out return E003 login required")
    def test_ota_logged_out_blocked(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure logged out"):
            driver.logout()
            who = driver.whoami()
            assert not who["logged_in"], f"Device still logged in: {who}"

        for cmd in ("ota", "ota status", "ota check"):
            with allure.step(f"Verify unauthenticated '{cmd}' returns E003"):
                lines = driver.send_command(cmd, timeout=2.0)
                out = _response(lines)
                assert "E003" in out, f"Command '{cmd}' while logged out did not return E003: {out}"

    @allure.story("AC-1: Access control for OTA")
    @allure.title("OTA commands without Wi-Fi return E002 Wi-Fi required")
    def test_ota_without_wifi_blocked(
        self,
        restore_wifi_connection_after_test: DeviceDriver,
    ) -> None:
        driver = restore_wifi_connection_after_test
        with allure.step("Disconnect Wi-Fi"):
            driver.wifi_disconnect()
            status = driver.wifi_status()
            if _has_usable_ipv4(status):
                driver.reboot()
                status = driver.wifi_status()
            assert not _has_usable_ipv4(status), f"Wi-Fi still active: {status}"

        with allure.step("Verify OTA command without Wi-Fi returns E002"):
            lines = driver.send_command("ota status", timeout=2.0)
            out = _response(lines)
            assert "E002" in out, f"OTA command without Wi-Fi did not return E002: {out}"

    # -----------------------------------------------------------------------
    # Persistent Flashing Tests (Opt-in only via -m persistent)
    # -----------------------------------------------------------------------

    @allure.story("OTA-6/OTA-7/OTA-10: Beta channel upgrade")
    @allure.title("OTA update from 2.1.0 to 2.3.0 completes and validates")
    @pytest.mark.persistent
    def test_available_update_completes_self_check(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        if firmware_version != "2.1.0":
            pytest.skip("Beta update scenario requires firmware 2.1.0.")

        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        with allure.step("Run OTA update to beta channel (2.3.0)"):
            lines = driver.run_ota_with_connectivity_retry(
                "ota update beta", timeout=180.0
            )
        _assert_successful_update(
            driver, lines, "2.1.0", "2.3.0", before[0]
        )

    @allure.story("OTA-5/OTA-7/OTA-10: Forced downgrade")
    @allure.title("Forced OTA downgrade from 2.3.0 to 2.1.0 completes and validates")
    @pytest.mark.persistent
    def test_forced_downgrade_completes_self_check(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        if firmware_version != "2.3.0":
            pytest.skip("Downgrade scenario requires firmware 2.3.0.")

        driver = authenticated_device
        before = _partition_state(driver.send_command("version"))
        with allure.step("Force-install firmware 2.1.0 over 2.3.0"):
            lines = driver.run_ota_with_connectivity_retry(
                "ota install 2.1.0 force", timeout=180.0
            )
        _assert_successful_update(
            driver, lines, "2.3.0", "2.1.0", before[0]
        )

    # -----------------------------------------------------------------------
    # Interactive OTA Interruption and Recovery Tests
    # -----------------------------------------------------------------------

    @allure.story("OTA-9: Retry after OTA download failure")
    @allure.title(
        "Interrupted OTA download can be retried after network recovery"
    )
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_interrupted_download_can_be_retried(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        restore_wifi_after_interrupted_ota: tuple[
            Callable[[], None], Callable[[], None]
        ],
        ensure_authenticated_device: Callable[[DeviceDriver], None],
        request: pytest.FixtureRequest,
    ) -> None:
        driver = device_driver
        mark_ap_disabled, mark_ap_restored = restore_wifi_after_interrupted_ota
        initial_partition = _partition_state(driver.send_command("version"))[0]

        prepare_observation(
            manual_prepare,
            action=(
                "keep the test Wi-Fi access point reachable and the board powered; "
                "do not switch off the AP until the next prompt"
            ),
            expected=(
                "the OTA command reaches 10% progress, then the next prompt "
                "instructs when to switch off the AP"
            ),
            duration="allow up to 30 seconds for the first progress event",
        )

        with allure.step("Start forced same-version OTA install"):
            progress_mark = len(driver.uart_log)
            driver.send_command(f"ota install {firmware_version} force", timeout=0.2)
            assert driver.wait_for_any(
                ("[OTA]  10%", "[OTA] 10%"),
                timeout=30.0,
                since_index=progress_mark,
            ), (
                "OTA did not reach its first progress event."
            )

        with allure.step("Disconnect Wi-Fi while OTA download is active"):
            interruption_mark = len(driver.uart_log)
            interruption_deadline = time.monotonic() + 45.0
            mark_ap_disabled()
            prepare_observation(
                manual_prepare,
                action="turn off the test Wi-Fi access point now; keep the board powered",
                expected="UART logs W110 and E410 download interrupted",
                duration="allow up to 45 seconds",
            )
            wifi_lost = driver.wait_for_any(
                ("W110",),
                timeout=max(0.0, interruption_deadline - time.monotonic()),
                since_index=interruption_mark,
            )
            assert wifi_lost, "OTA did not report the expected Wi-Fi-loss event (W110)."
            remaining_time = interruption_deadline - time.monotonic()
            download_interrupted = remaining_time > 0 and driver.wait_for_any(
                ("E410",), timeout=remaining_time, since_index=interruption_mark
            )
            assert download_interrupted, (
                "OTA did not report the expected interrupted-download error (E410)."
            )

        with allure.step("Restore Wi-Fi access point and reconnect"):
            prepare_observation(
                manual_prepare,
                action="turn the test Wi-Fi access point back on; keep the board powered",
                expected="the test access point is available to clients",
                duration="allow up to 20 seconds",
            )
            prepare_observation(
                manual_prepare,
                action=(
                    "if needed, restore the upstream internet connection for "
                    "the test access point"
                ),
                expected=(
                    "a separate client using this access point (not cellular "
                    "data) can reach the internet"
                ),
                duration=(
                    "allow up to 60 seconds; if unavailable, report FAIL and "
                    "stop before the OTA retry"
                ),
            )
            if not manual_check(
                "Is a separate client connected to the restored test access "
                "point (not cellular data) able to reach the internet?"
            ):
                pytest.skip(
                    "The operator did not confirm upstream internet on the "
                    "restored test access point; OTA recovery is inconclusive."
                )
            mark_ap_restored()

            if firmware_version == "2.3.0":
                with allure.step(
                    "Force saved-profile reconnect and verify internet on 2.3.0"
                ):
                    disconnect_lines = driver.wifi_disconnect(timeout=10.0)
                    assert any(
                        marker in line.casefold()
                        for line in disconnect_lines
                        for marker in ("[link] disconnected", "w115")
                    ), (
                        "Wi-Fi disconnect did not return the expected UART "
                        f"confirmation: {disconnect_lines!r}"
                    )

                    assert driver.wifi_reconnect(timeout=20.0), (
                        "Saved-profile reconnect did not restore Wi-Fi "
                        "association and IP."
                    )
                    _ensure_saved_wifi_connected(driver, request)
                    internet_status = driver.wifi_status()
                    assert internet_status.get("internet") is True, (
                        "Wi-Fi association/IP returned after reconnect, but "
                        "internet readiness did not. The AP's upstream "
                        "internet was confirmed by the operator. Candidate "
                        "finding: BUG-018. "
                        f"Status: {internet_status!r}"
                    )
            else:
                _ensure_saved_wifi_connected(driver, request)

            ensure_authenticated_device(driver)

        with allure.step("Verify firmware version and partition remained unchanged after error"):
            ver_lines = driver.send_command("version")
            assert driver.get_firmware_version(ver_lines) == firmware_version
            assert _partition_state(ver_lines)[0] == initial_partition

        with allure.step("Retry OTA install after interruption"):
            retry_lines = driver.run_ota_with_connectivity_retry(
                f"ota install {firmware_version} force", timeout=180.0
            )
            _assert_successful_update(
                driver,
                retry_lines,
                firmware_version,
                firmware_version,
                initial_partition,
            )
