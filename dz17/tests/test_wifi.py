from __future__ import annotations

import time
from typing import Any

import allure
import pytest
from drivers.device_driver import DeviceDriver
from manual_checks import (
    STATUS_INDICATOR_LEGEND,
    SoftChecks,
    prepare_observation,
    status_indicator_description,
)


def _restore_saved_wifi(driver: DeviceDriver) -> None:
    if driver.wifi_status()["connected"]:
        return
    reconnected = driver.wifi_reconnect(timeout=14.0)
    assert reconnected, "Failed to restore the saved Wi-Fi connection after the test"


def _confirmed_login_state(driver: DeviceDriver) -> bool:
    identity = driver.whoami()
    identity_lines = [line.casefold() for line in identity["raw"]]
    logged_out = any("not logged in" in line for line in identity_lines)
    logged_in = any(
        "user:" in line and "access:" in line for line in identity_lines
    )
    assert logged_out != logged_in, (
        f"Could not determine login state from whoami response: {identity['raw']}"
    )
    assert identity["logged_in"] is logged_in, (
        f"whoami parser disagrees with its response: {identity}"
    )
    return logged_in


def _confirmed_wifi_status(driver: DeviceDriver) -> dict[str, Any]:
    status = driver.wifi_status()
    link_lines = [
        line.casefold() for line in status["raw"] if "link:" in line.casefold()
    ]
    assert link_lines, f"Could not determine Wi-Fi state: {status['raw']}"
    latest_link = link_lines[-1]
    connected = "buoy link '" in latest_link or "connected (" in latest_link
    disconnected = "buoy link down" in latest_link
    assert connected != disconnected, f"Unrecognized Wi-Fi link response: {link_lines}"
    assert status["connected"] is connected, (
        f"Wi-Fi status parser disagrees with its latest link response: {status}"
    )
    return status


@allure.epic("SENTRY SWM-2")
@allure.feature("Wi-Fi Communication")
@pytest.mark.wifi
class TestWifi:

    @allure.story("WF-4 Network scan")
    @allure.title("Scan nearby Wi-Fi access points")
    @pytest.mark.positive
    @pytest.mark.smoke
    def test_wifi_scan(self, device_driver: DeviceDriver) -> None:
        driver = device_driver
        with allure.step("Issue 'scan' command"):
            ssids = driver.wifi_scan(timeout=10.0)
            assert ssids, "Scan returned no Wi-Fi networks"

        with allure.step("Verify parsed access points"):
            allure.attach(
                "\n".join(ssids),
                name="Discovered SSIDs",
                attachment_type=allure.attachment_type.TEXT,
            )
            assert any(len(s.strip()) > 0 for s in ssids)

    @allure.story("WF-1 Wi-Fi connection")
    @allure.title("Connect to Wi-Fi network using valid credentials")
    @pytest.mark.positive
    @pytest.mark.smoke
    @pytest.mark.persistent
    def test_wifi_connect_success(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
    ) -> None:
        driver = device_driver
        ssid, password = wifi_credentials

        with allure.step(f"Connect to Wi-Fi SSID '{ssid}'"):
            connected = driver.wifi_connect(ssid, password, timeout=14.0)
            assert connected, f"Failed to connect to Wi-Fi SSID '{ssid}'"

        with allure.step("Query status and verify valid network state"):
            status = driver.wifi_status()
            assert status["connected"], "Device reported Wi-Fi link down after connect"
            assert status["ssid"] == ssid or (status["ssid"] and ssid in status["ssid"])
            assert DeviceDriver.wifi_connection_is_valid(status), (
                f"Wi-Fi status does not have a valid IP or RSSI: {status}"
            )

    @allure.story("WF-3 Wi-Fi disconnect and status")
    @allure.title("Disconnect from Wi-Fi")
    @pytest.mark.positive
    @pytest.mark.interactive
    def test_wifi_disconnect(
        self,
        device_driver: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = device_driver
        initially_connected = False
        try:
            initial_status = _confirmed_wifi_status(driver)
            initially_connected = initial_status["connected"]
            assert initial_status["connected"], (
                "Disconnect test requires an initially connected Wi-Fi link."
            )
            lamp_status = driver.lamp_status()
            assert lamp_status["lamp"] == "off", (
                "Turn the main Beacon lamp OFF before this status-LED check; "
                f"got: {lamp_status}"
            )
            prepare_observation(
                manual_prepare,
                action="Watch the built-in RGB status LED as this test disconnects Wi-Fi.",
                expected=(
                    f"{STATUS_INDICATOR_LEGEND} After disconnecting, the built-in "
                    "RGB status LED should show RED (Wi-Fi disconnected)."
                ),
                duration="~5 seconds",
            )

            with allure.step("Issue 'disconnect' command"):
                lines = driver.wifi_disconnect(timeout=1.0)
                assert any("[LINK] disconnected" in line or "W115" in line for line in lines)

            with allure.step("Verify status shows link down"):
                status = _confirmed_wifi_status(driver)
                assert not status["connected"], "Wi-Fi reported connected after disconnect command"

            soft.check(
                manual_check(
                    f"The main Beacon lamp is OFF. {STATUS_INDICATOR_LEGEND} "
                    "With Wi-Fi disconnected, does the built-in RGB status LED "
                    "show RED (Wi-Fi disconnected)?"
                ),
                "Status LED was not physically observed as red after Wi-Fi disconnect",
            )
            soft.assert_all()
        finally:
            if initially_connected:
                with allure.step("Restore Wi-Fi connection"):
                    _restore_saved_wifi(driver)

    @allure.story("WF-3 Saved profile reconnect")
    @allure.title("Reconnect to saved Wi-Fi profile and already-connected warning")
    @pytest.mark.positive
    @pytest.mark.interactive
    def test_wifi_reconnect(
        self,
        device_driver: DeviceDriver,
        wifi_ssid: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = device_driver
        initially_connected = False
        try:
            login_state_before_disconnect = _confirmed_login_state(driver)
            initial_wifi_status = _confirmed_wifi_status(driver)
            initially_connected = initial_wifi_status["connected"]
            assert initial_wifi_status["connected"], (
                "Saved-profile reconnect test requires Wi-Fi to be connected initially."
            )
            expected_connected_state = status_indicator_description(
                is_connected=True,
                is_logged_in=login_state_before_disconnect,
            )
            lamp_status = driver.lamp_status()
            assert lamp_status["lamp"] == "off", (
                "Turn the main Beacon lamp OFF before this status-LED check; "
                f"got: {lamp_status}"
            )
            prepare_observation(
                manual_prepare,
                action=(
                    "Watch the built-in RGB status LED through the saved-profile "
                    "disconnect/reconnect sequence."
                ),
                expected=(
                    f"{STATUS_INDICATOR_LEGEND} The LED should show RED "
                    "(Wi-Fi disconnected) while disconnected, then "
                    f"{expected_connected_state} after reconnect; login state "
                    "should remain unchanged."
                ),
                duration="~20 seconds",
            )

            with allure.step("Disconnect before testing reconnect"):
                driver.wifi_disconnect()
                disconnected_status = _confirmed_wifi_status(driver)
                assert not disconnected_status["connected"], (
                    "Wi-Fi must be disconnected before testing saved-profile reconnect"
                )
                soft.check(
                    manual_check(
                        f"The main Beacon lamp is OFF. {STATUS_INDICATOR_LEGEND} "
                        "With Wi-Fi disconnected, does the built-in RGB status LED "
                        "show RED (Wi-Fi disconnected)?"
                    ),
                    "Status LED was not physically observed as red after disconnect",
                )

            with allure.step("Issue 'reconnect' to connect to saved profile"):
                reconnected = driver.wifi_reconnect(timeout=14.0)
                assert reconnected, "Failed to reconnect using saved Wi-Fi profile"

            with allure.step("Verify status reports the saved network"):
                status = _confirmed_wifi_status(driver)
                assert status["connected"]
                assert status["ssid"] == wifi_ssid or (
                    status["ssid"] and wifi_ssid in status["ssid"]
                ), (
                    f"Expected saved SSID '{wifi_ssid}', got: {status['ssid']}"
                )
                current_login_state = _confirmed_login_state(driver)
                assert current_login_state is login_state_before_disconnect, (
                    "Login state changed during saved-profile reconnect: "
                    f"before={login_state_before_disconnect}, "
                    f"after={current_login_state}"
                )

            with allure.step("Verify duplicate reconnect returns warning W114"):
                dup_lines = driver.send_command("reconnect")
                assert any("W114" in line or "already connected" in line.casefold() for line in dup_lines)

            soft.check(
                manual_check(
                    f"The main Beacon lamp is OFF. {STATUS_INDICATOR_LEGEND} "
                    f"With Wi-Fi reconnected, does the built-in RGB status LED "
                    f"show {expected_connected_state}?"
                ),
                f"Status LED was not physically observed as "
                f"{expected_connected_state} after reconnect",
            )
            soft.assert_all()
        finally:
            if initially_connected:
                with allure.step("Restore saved Wi-Fi connection if disconnected"):
                    _restore_saved_wifi(driver)

    @allure.story("WF-2 Network not found")
    @allure.title("Reject an SSID absent from scan results with error E102")
    @pytest.mark.negative
    def test_wifi_connect_missing_network(
        self,
        device_driver: DeviceDriver,
        missing_wifi_ssid: str,
        wrong_wifi_password: str,
    ) -> None:
        driver = device_driver
        try:
            with allure.step("Confirm the configured missing SSID is not in scan results"):
                scanned_ssids = driver.wifi_scan(timeout=10.0)
                assert scanned_ssids, "Wi-Fi scan returned no access points to compare"
                assert missing_wifi_ssid.casefold() not in {
                    ssid.casefold() for ssid in scanned_ssids
                }, (
                    "The missing-network test SSID is present in scan results; "
                    "configure a confirmed absent SSID."
                )
                driver.wifi_disconnect()
                assert not driver.wifi_status()["connected"]

            with allure.step("Enter an SSID absent from scan results"):
                mark = driver.buffer_len()
                driver.send_command("connect", timeout=0.6)
                prompt_ssid = driver.wait_for(
                    "ssid or number:", timeout=6.0, since_index=mark
                )
                assert prompt_ssid, "Expected 'ssid or number:' prompt"

                mark_password = driver.buffer_len()
                driver._send_line(missing_wifi_ssid)
                prompt_password = driver.wait_for(
                    "password:", timeout=6.0, since_index=mark_password
                )
                assert prompt_password, "Expected 'password:' prompt"

            with allure.step("Submit a known-invalid test password and verify E102"):
                mark_result = driver.buffer_len()
                driver._send_line(wrong_wifi_password, sensitive=True)
                assert driver.wait_for("E102", timeout=20.0, since_index=mark_result), (
                    "Expected E102 when connecting to an SSID absent from scan results"
                )
                output = "\n".join(driver.uart_log[mark_result:]).casefold()
                assert "got ip" not in output and "connected to '" not in output, (
                    f"Connection unexpectedly succeeded before E102: {output}"
                )
        finally:
            with allure.step("Restore Wi-Fi connection after missing-network test"):
                _restore_saved_wifi(driver)

    @allure.story("WF-1 Negative validation - Empty SSID")
    @allure.title("Reject empty SSID with error E111")
    @pytest.mark.negative
    def test_wifi_connect_empty_ssid(self, device_driver: DeviceDriver) -> None:
        driver = device_driver
        try:
            driver.wifi_disconnect()

            with allure.step("Send connect command and provide empty SSID"):
                mark = driver.buffer_len()
                driver.send_command("connect", timeout=0.6)
                prompt_seen = driver.wait_for("ssid or number:", timeout=6.0, since_index=mark)
                assert prompt_seen, "Expected 'ssid or number:' prompt"
                # Send empty line (Enter)
                driver._send_line("")
                lines = driver.read_for(timeout=1.0)
                combined = "\n".join(lines)
                assert "E111" in combined, f"Expected E111 for empty SSID, got: {combined}"
        finally:
            with allure.step("Restore Wi-Fi connection after negative test"):
                _restore_saved_wifi(driver)

    @allure.story("WF-1 Negative validation - Short password")
    @allure.title("Reject password shorter than 8 characters with error E112")
    @pytest.mark.negative
    def test_wifi_connect_short_password(
        self,
        device_driver: DeviceDriver,
        wifi_ssid: str,
    ) -> None:
        driver = device_driver
        try:
            driver.wifi_disconnect()

            with allure.step("Send connect and provide short password (<8 chars)"):
                mark = driver.buffer_len()
                driver.send_command("connect", timeout=0.6)
                prompt_ssid = driver.wait_for("ssid or number:", timeout=6.0, since_index=mark)
                assert prompt_ssid, "Expected 'ssid or number:' prompt"

                mark_pass = driver.buffer_len()
                driver._send_line(wifi_ssid)
                prompt_pass = driver.wait_for("password:", timeout=6.0, since_index=mark_pass)
                assert prompt_pass, "Expected 'password:' prompt"

                driver._send_line("short1", sensitive=True)
                lines = driver.read_for(timeout=1.0)
                combined = "\n".join(lines)
                assert "E112" in combined, f"Expected E112 for short password, got: {combined}"
        finally:
            with allure.step("Restore Wi-Fi connection after negative test"):
                _restore_saved_wifi(driver)

    @allure.story("WF-2 Negative validation - Wrong password")
    @allure.title("Reject incorrect password with error E101")
    @pytest.mark.negative
    def test_wifi_connect_wrong_password(
        self,
        device_driver: DeviceDriver,
        wifi_ssid: str,
        wrong_wifi_password: str,
    ) -> None:
        driver = device_driver
        try:
            driver.wifi_disconnect()

            with allure.step("Send connect and provide incorrect password"):
                mark = driver.buffer_len()
                driver.send_command("connect", timeout=0.6)
                prompt_ssid = driver.wait_for("ssid or number:", timeout=6.0, since_index=mark)
                assert prompt_ssid, "Expected 'ssid or number:' prompt"

                mark_pass = driver.buffer_len()
                driver._send_line(wifi_ssid)
                prompt_pass = driver.wait_for("password:", timeout=6.0, since_index=mark_pass)
                assert prompt_pass, "Expected 'password:' prompt"

                driver._send_line(wrong_wifi_password, sensitive=True)
                # Connection attempt will run for a few seconds then fail
                lines = driver.read_for(timeout=8.0)
                combined = "\n".join(lines)
                assert "E101" in combined or "connection failed" in combined.casefold(), (
                    f"Expected E101 for wrong password, got: {combined}"
                )
        finally:
            with allure.step("Restore Wi-Fi connection after negative test"):
                _restore_saved_wifi(driver)

    @allure.story("WF-3 Profile persistence across reboot")
    @allure.title("Saved Wi-Fi credentials persist in NVS across reboot")
    @pytest.mark.persistent
    def test_wifi_persistence_after_reboot(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
    ) -> None:
        driver = device_driver
        ssid, password = wifi_credentials

        with allure.step("Ensure device is connected and network is saved"):
            driver.wifi_connect(ssid, password, timeout=12.0)

        with allure.step("Reboot device"):
            assert driver.reboot(timeout=30.0), "Device failed to reboot and return to ready prompt"

        with allure.step("Verify status indicates known saved profile"):
            status = driver.wifi_status()
            assert not status["connected"], "PRD states device starts disconnected after reboot"
            assert status["ssid"] == ssid or (status["ssid"] and ssid in status["ssid"])

        with allure.step("Restore connection via 'reconnect'"):
            reconnected = driver.wifi_reconnect(timeout=14.0)
            assert reconnected, "Saved credentials failed to reconnect after reboot"
            status_after = driver.wifi_status()
            assert status_after["connected"]
