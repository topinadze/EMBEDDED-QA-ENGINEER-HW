from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Generator
from unittest.mock import Mock

import allure
import pytest
from config.test_config import resolve_wifi_credentials
from drivers.device_driver import DeviceDriver
from manual_checks import (
    STATUS_INDICATOR_LEGEND,
    SoftChecks,
    prepare_observation,
    status_indicator_description,
)

LOGGER = logging.getLogger(__name__)
STATUS_LED_VISIBILITY_PRECONDITION = (
    "Before pressing Enter, verify the Beacon lamp is off and no higher-priority "
    "LED state is active (emergency, Guard alarm/intrusion/arming, OTA, or sensor "
    "error). If you cannot verify these conditions, do not continue. Do not change "
    "Wi-Fi or login state."
)


@dataclass
class WifiRestoreState:
    initially_connected: bool
    ap_interruption_started: bool = False
    ap_restoration_confirmed: bool = False


def _restore_saved_wifi(
    driver: DeviceDriver,
    ssid: str,
    password: str,
) -> None:
    reconnect_start = driver.buffer_len()
    with allure.step("Restore Wi-Fi using the saved profile"):
        reconnected = driver.wifi_reconnect(timeout=22.0)
    reconnect_response = "\n".join(driver.uart_log[reconnect_start:])
    if reconnected:
        status = _confirmed_wifi_status(driver)
        if DeviceDriver.wifi_connection_is_valid(status):
            return
        reconnect_outcome = (
            "Saved-profile reconnect returned success, but status did not confirm "
            f"a valid connection: {status}"
        )
    else:
        reconnect_outcome = "Saved-profile reconnect did not receive both association and IP events."

    LOGGER.warning(
        "Saved-profile Wi-Fi reconnect failed during cleanup: %s; UART: %s",
        reconnect_outcome,
        reconnect_response or "No reconnect response captured.",
    )
    allure.attach(
        reconnect_response or "No reconnect response captured.",
        name="Saved-profile reconnect response",
        attachment_type=allure.attachment_type.TEXT,
    )

    if not ssid or not password:
        raise AssertionError(
            "Saved-profile Wi-Fi reconnect failed and configured SSID/password are "
            "unavailable for the connect fallback. Configure config/wifi_secrets.py, "
            "HW17_WIFI_SSID/HW17_WIFI_PASSWORD, TEST_WIFI_SSID/TEST_WIFI_PASSWORD, "
            "or --wifi-ssid/--wifi-password."
        )

    connect_start = driver.buffer_len()
    with allure.step(f"Fallback: connect to configured Wi-Fi SSID '{ssid}'"):
        connected = driver.wifi_connect(ssid, password, timeout=25.0)
    connect_response = "\n".join(driver.uart_log[connect_start:])
    allure.attach(
        connect_response or "No connect response captured.",
        name="Configured-credential connect response",
        attachment_type=allure.attachment_type.TEXT,
    )
    if not connected:
        raise AssertionError(
            "Saved-profile reconnect failed, and the configured-credential "
            "connect fallback did not receive both association and IP events. "
            f"Reconnect: {reconnect_outcome}; fallback UART: "
            f"{connect_response or 'No connect response captured.'}"
        )

    status = _confirmed_wifi_status(driver)
    if (
        not DeviceDriver.wifi_connection_is_valid(status)
        or status.get("ssid") != ssid
    ):
        raise AssertionError(
            "Configured-credential connect returned success, but status did not "
            f"confirm a valid connection to SSID '{ssid}': {status}"
        )


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


def _status_led_prompt(status: dict[str, Any], is_logged_in: bool) -> str:
    expected = status_indicator_description(
        is_connected=status["connected"],
        is_logged_in=is_logged_in,
    )
    color = expected.split(" ", maxsplit=1)[0]
    link_state = "connected" if status["connected"] else "disconnected"
    return (
        f"UART status confirms Wi-Fi is {link_state}. The built-in RGB status LED "
        f"should show {expected}. Do you see {color}? If not, enter 'c' first and "
        "record the specific color you see, then answer 'n'."
    )


@pytest.fixture
def wifi_restore_state(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Generator[WifiRestoreState, None, None]:
    state = WifiRestoreState(
        initially_connected=_confirmed_wifi_status(device_driver)["connected"]
    )
    yield state

    try:
        current_status = _confirmed_wifi_status(device_driver)
        if state.initially_connected and not DeviceDriver.wifi_connection_is_valid(
            current_status
        ):
            with allure.step("Teardown: restore the initially connected Wi-Fi link"):
                ssid, password = resolve_wifi_credentials(
                    ssid_override=request.config.getoption("--wifi-ssid"),
                    password_override=request.config.getoption("--wifi-password"),
                )
                _restore_saved_wifi(device_driver, ssid, password)
        elif not state.initially_connected and current_status["connected"]:
            with allure.step("Teardown: restore the initially disconnected Wi-Fi state"):
                lines = device_driver.wifi_disconnect()
                assert any(
                    "[LINK] disconnected" in line or "W115" in line for line in lines
                ), f"Could not restore disconnected Wi-Fi state: {lines}"
    except Exception as exc:
        allure.attach(
            str(exc),
            name="Wi-Fi state cleanup failure",
            attachment_type=allure.attachment_type.TEXT,
        )
        if getattr(getattr(request.node, "rep_call", None), "failed", False):
            LOGGER.error("Wi-Fi cleanup also failed after test failure: %s", exc)
        else:
            pytest.fail(f"Wi-Fi cleanup failed: {exc}", pytrace=False)


@pytest.fixture
def wifi_connected_state(
    device_driver: DeviceDriver,
    wifi_restore_state: WifiRestoreState,
    wifi_ssid: str,
) -> dict[str, Any]:
    status = _confirmed_wifi_status(device_driver)
    if not status["connected"]:
        with allure.step("Fixture: reconnect to the saved Wi-Fi profile"):
            assert device_driver.wifi_reconnect(timeout=20.0), (
                "Could not establish the connected Wi-Fi precondition from the "
                "saved profile."
            )
        status = _confirmed_wifi_status(device_driver)

    assert status["connected"], (
        f"Connected Wi-Fi precondition was not established: {status}"
    )
    assert status["ssid"] == wifi_ssid or (
        status["ssid"] and wifi_ssid in status["ssid"]
    ), (
        f"Connected Wi-Fi precondition requires configured SSID '{wifi_ssid}', "
        f"got: {status['ssid']}"
    )
    return status


@pytest.fixture
def wifi_disconnected_state(
    device_driver: DeviceDriver,
    wifi_restore_state: WifiRestoreState,
) -> dict[str, Any]:
    status = _confirmed_wifi_status(device_driver)
    if status["connected"]:
        with allure.step("Fixture: disconnect Wi-Fi to establish the down-state precondition"):
            lines = device_driver.wifi_disconnect()
            assert any("[LINK] disconnected" in line for line in lines), (
                f"Could not establish disconnected Wi-Fi precondition: {lines}"
            )
        status = _confirmed_wifi_status(device_driver)

    assert not status["connected"], (
        f"Disconnected Wi-Fi precondition was not established: {status}"
    )
    return status


@pytest.fixture
def wifi_link_loss_restore(
    wifi_restore_state: WifiRestoreState,
    wifi_connected_state: dict[str, Any],
    manual_prepare: Any,
) -> Generator[WifiRestoreState, None, None]:
    yield wifi_restore_state

    if (
        wifi_restore_state.ap_interruption_started
        and not wifi_restore_state.ap_restoration_confirmed
    ):
        with allure.step("Teardown: ensure the test access point is restored"):
            manual_prepare(
                "What to do: If the test access point/router is still off, turn it back "
                "on now. Wait until it is available, then press Enter.\n"
                "What to observe: The access point is powered on and available; "
                "the device remains connected to USB/UART.\n"
                "Duration: Allow up to 20 seconds for the AP to become available."
            )


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
    @pytest.mark.interactive
    def test_wifi_connect_success(
        self,
        device_driver: DeviceDriver,
        wifi_credentials: tuple[str, str],
        wifi_disconnected_state: dict[str, Any],
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = device_driver
        ssid, password = wifi_credentials

        with allure.step("Prepare to observe the status LED after Wi-Fi connection"):
            prepare_observation(
                manual_prepare,
                action=(
                    f"{STATUS_LED_VISIBILITY_PRECONDITION} Then watch the built-in "
                    "RGB status LED while this test connects the device to Wi-Fi."
                ),
                expected=(
                    f"{STATUS_INDICATOR_LEGEND} After UART confirms connection, "
                    "the LED should show ORANGE if the device is logged out or "
                    "GREEN if it is logged in."
                ),
                duration="~15 seconds",
            )

        with allure.step(f"Connect to Wi-Fi SSID '{ssid}'"):
            connection_mark = driver.buffer_len()
            connected = driver.wifi_connect(ssid, password, timeout=14.0)
            assert connected, (
                f"Failed to connect to Wi-Fi SSID '{ssid}'; "
                f"UART: {driver.uart_log[connection_mark:]}"
            )
            completion = driver.wait_for_any(
                (
                    "[LINK] network saved",
                    "E101",
                    "E104",
                    "[LINK] connection failed",
                ),
                timeout=20.0,
                since_index=connection_mark,
            )
            assert completion == "[LINK] network saved", (
                "Wi-Fi association and DHCP completed, but the explicit "
                "profile-save success event was not received (or a failure "
                f"event occurred: {completion!r}); "
                f"UART: {driver.uart_log[connection_mark:]}"
            )

        with allure.step("Query status and verify valid network state"):
            status = _confirmed_wifi_status(driver)
            assert status["connected"], "Device reported Wi-Fi link down after connect"
            assert status["ssid"] == ssid or (status["ssid"] and ssid in status["ssid"])
            assert DeviceDriver.wifi_connection_is_valid(status), (
                f"Wi-Fi status does not have a valid IP or RSSI: {status}"
            )
            login_state = _confirmed_login_state(driver)

        with allure.step("Physically verify the connected-state status LED color"):
            soft.check(
                manual_check(_status_led_prompt(status, login_state)),
                "The status LED did not match the UART-confirmed Wi-Fi/login state after connect",
            )
            soft.assert_all()

    @allure.story("WF-3 Wi-Fi disconnect and status")
    @allure.title("Disconnect from Wi-Fi")
    @pytest.mark.positive
    @pytest.mark.interactive
    def test_wifi_disconnect(
        self,
        device_driver: DeviceDriver,
        wifi_connected_state: dict[str, Any],
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = device_driver
        prepare_observation(
            manual_prepare,
            action=(
                f"{STATUS_LED_VISIBILITY_PRECONDITION} Then watch the built-in "
                "RGB status LED as this test disconnects Wi-Fi."
            ),
            expected=(
                "After the test confirms the Wi-Fi link is disconnected, the "
                "built-in RGB status LED should be RED."
            ),
            duration="~5 seconds",
        )

        with allure.step("Issue 'disconnect' command"):
            lines = driver.wifi_disconnect(timeout=1.0)
            assert any("[LINK] disconnected" in line or "W115" in line for line in lines)

        with allure.step("Verify status shows link down"):
            status = _confirmed_wifi_status(driver)
            assert not status["connected"], "Wi-Fi reported connected after disconnect command"
            login_state = _confirmed_login_state(driver)

        soft.check(
            manual_check(_status_led_prompt(status, login_state)),
            "Status LED was not physically observed as red after Wi-Fi disconnect",
        )
        soft.assert_all()

    @allure.story("WF-3 Wi-Fi disconnect and status")
    @allure.title("Return W115 when disconnect is requested while already disconnected")
    @pytest.mark.negative
    def test_wifi_disconnect_when_already_disconnected(
        self,
        device_driver: DeviceDriver,
        wifi_disconnected_state: dict[str, Any],
    ) -> None:
        driver = device_driver
        with allure.step("Request disconnect while Wi-Fi is already down"):
            lines = driver.wifi_disconnect(timeout=1.0)
            assert any("W115" in line for line in lines), (
                f"Expected W115 for disconnect while already down, got: {lines}"
            )
            status = _confirmed_wifi_status(driver)
            assert not status["connected"], (
                "Wi-Fi unexpectedly connected after a repeated disconnect"
            )

    @allure.story("WF-5 Automatic Wi-Fi link-loss handling")
    @allure.title("Emit W110 and make all three automatic reconnect attempts after AP loss")
    @pytest.mark.positive
    @pytest.mark.interactive
    def test_wifi_link_loss_emits_warning_and_three_retries(
        self,
        device_driver: DeviceDriver,
        wifi_link_loss_restore: WifiRestoreState,
        wifi_connected_state: dict[str, Any],
        manual_prepare: Any,
    ) -> None:
        driver = device_driver
        restore_state = wifi_link_loss_restore

        expected_messages = (
            "W110 wifi connection lost",
            "retry 1/3",
            "retry 2/3",
            "retry 3/3",
        )
        with allure.step("Prepare a controlled access-point interruption"):
            manual_prepare(
                "What to do: Use only a dedicated test access point/router that is "
                "safe to interrupt. After pressing Enter, switch that AP off; keep "
                "it off until all three retry messages appear and the next prompt "
                "asks you to restore it. Keep the device connected to USB/UART.\n"
                "What to observe: The console should report W110 followed by "
                "retry 1/3, retry 2/3, and retry 3/3.\n"
                "Duration: Keep the AP unavailable until the retry sequence is "
                "captured (typically ~5-10 seconds after link loss); the test "
                "waits up to 30 seconds.\n"
                "Do not proceed if switching off this AP would affect other users "
                "or devices."
            )
        mark = driver.buffer_len()
        restore_state.ap_interruption_started = True

        with allure.step("Capture W110 and all three automatic retry messages"):
            found = driver.wait_for_all(
                expected_messages,
                timeout=30.0,
                since_index=mark,
            )
            missing = [message for message, seen in found.items() if not seen]
            assert not missing, (
                "WF-5 did not produce all required link-loss messages; "
                f"missing: {missing}"
            )

            captured = driver.uart_log[mark:]
            positions = [
                next(
                    index
                    for index, line in enumerate(captured)
                    if message.casefold() in line.casefold()
                )
                for message in expected_messages
            ]
            assert positions == sorted(positions), (
                "WF-5 messages were not emitted in the required order: "
                f"{expected_messages}"
            )

        with allure.step("Prompt operator to restore the access point"):
            manual_prepare(
                "What to do: Turn the same test access point/router back on now. "
                "Wait until it is available, then press Enter.\n"
                "What to observe: The access point is powered on and available; "
                "the device remains connected to USB/UART.\n"
                "Duration: Allow up to 20 seconds for the AP to become available."
            )
            restore_state.ap_restoration_confirmed = True

        with allure.step("Read back Wi-Fi state after access-point restoration"):
            _confirmed_wifi_status(driver)

    @allure.story("WF-3 Saved profile reconnect")
    @allure.title("Reconnect to saved Wi-Fi profile and already-connected warning")
    @pytest.mark.positive
    @pytest.mark.interactive
    def test_wifi_reconnect(
        self,
        device_driver: DeviceDriver,
        wifi_connected_state: dict[str, Any],
        wifi_ssid: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = device_driver
        login_state_before_disconnect = _confirmed_login_state(driver)
        expected_connected_state = status_indicator_description(
            is_connected=True,
            is_logged_in=login_state_before_disconnect,
        )
        prepare_observation(
            manual_prepare,
            action=(
                f"{STATUS_LED_VISIBILITY_PRECONDITION} Then watch the built-in "
                "RGB status LED through the saved-profile disconnect/reconnect "
                "sequence."
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
                    _status_led_prompt(
                        disconnected_status,
                        _confirmed_login_state(driver),
                    )
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
            manual_check(_status_led_prompt(status, current_login_state)),
            f"Status LED was not physically observed as "
            f"{expected_connected_state} after reconnect",
        )
        soft.assert_all()

    @allure.story("WF-2 Network not found")
    @allure.title("Reject an SSID absent from scan results with error E102")
    @pytest.mark.negative
    def test_wifi_connect_missing_network(
        self,
        device_driver: DeviceDriver,
        wifi_restore_state: WifiRestoreState,
        missing_wifi_ssid: str,
        wrong_wifi_password: str,
    ) -> None:
        driver = device_driver
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

    @allure.story("WF-1 Negative validation - Empty SSID")
    @allure.title("Reject empty SSID with error E111")
    @pytest.mark.negative
    def test_wifi_connect_empty_ssid(
        self,
        device_driver: DeviceDriver,
        wifi_disconnected_state: dict[str, Any],
    ) -> None:
        driver = device_driver

        with allure.step("Send connect command and provide empty SSID"):
            mark = driver.buffer_len()
            driver.send_command("connect", timeout=0.6)
            prompt_seen = driver.wait_for("ssid or number:", timeout=6.0, since_index=mark)
            assert prompt_seen, "Expected 'ssid or number:' prompt"
            mark_result = driver.buffer_len()
            driver._send_line("")
            assert driver.wait_for("E111", timeout=6.0, since_index=mark_result), (
                "Expected explicit E111 for empty SSID; "
                f"UART: {driver.uart_log[mark_result:]}"
            )


    @allure.story("WF-1 Negative validation - Short password")
    @allure.title("Reject password shorter than 8 characters with error E112")
    @pytest.mark.negative
    def test_wifi_connect_short_password(
        self,
        device_driver: DeviceDriver,
        wifi_disconnected_state: dict[str, Any],
        wifi_ssid: str,
    ) -> None:
        driver = device_driver

        with allure.step("Send connect and provide short password (<8 chars)"):
            mark = driver.buffer_len()
            driver.send_command("connect", timeout=0.6)
            prompt_ssid = driver.wait_for("ssid or number:", timeout=6.0, since_index=mark)
            assert prompt_ssid, "Expected 'ssid or number:' prompt"

            mark_pass = driver.buffer_len()
            driver._send_line(wifi_ssid)
            prompt_pass = driver.wait_for("password:", timeout=6.0, since_index=mark_pass)
            assert prompt_pass, "Expected 'password:' prompt"

            mark_result = driver.buffer_len()
            driver._send_line("short1", sensitive=True)
            assert driver.wait_for("E112", timeout=6.0, since_index=mark_result), (
                "Expected explicit E112 for a short password; "
                f"UART: {driver.uart_log[mark_result:]}"
            )

    @allure.story("WF-2 Negative validation - Wrong password")
    @allure.title("Reject incorrect password with error E101")
    @pytest.mark.negative
    def test_wifi_connect_wrong_password(
        self,
        device_driver: DeviceDriver,
        wifi_disconnected_state: dict[str, Any],
        wifi_ssid: str,
        wrong_wifi_password: str,
    ) -> None:
        driver = device_driver

        with allure.step("Send connect and provide incorrect password"):
            mark = driver.buffer_len()
            driver.send_command("connect", timeout=0.6)
            prompt_ssid = driver.wait_for("ssid or number:", timeout=6.0, since_index=mark)
            assert prompt_ssid, "Expected 'ssid or number:' prompt"

            driver._send_line(wifi_ssid)
            mark_pass = driver.buffer_len()
            prompt_pass = driver.wait_for("password:", timeout=6.0, since_index=mark_pass)
            assert prompt_pass, "Expected 'password:' prompt"

            mark_result = driver.buffer_len()
            driver._send_line(wrong_wifi_password, sensitive=True)
            error = driver.wait_for_any(
                ("E101", "wrong password"),
                timeout=12.0,
                since_index=mark_result,
            )
            assert error is not None, (
                "Expected explicit E101 or 'wrong password' response for "
                f"incorrect credentials; UART: {driver.uart_log[mark_result:]}"
            )

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
            connection_mark = driver.buffer_len()
            connected = driver.wifi_connect(ssid, password, timeout=20.0)
            assert connected, (
                "Could not establish Wi-Fi before reboot; "
                f"UART: {driver.uart_log[connection_mark:]}"
            )
            completion = driver.wait_for_any(
                (
                    "[LINK] network saved",
                    "E101",
                    "E104",
                    "[LINK] connection failed",
                ),
                timeout=20.0,
                since_index=connection_mark,
            )
            assert completion == "[LINK] network saved", (
                "Wi-Fi connection did not emit the explicit saved-profile "
                f"confirmation before reboot (completion={completion!r}); "
                f"UART: {driver.uart_log[connection_mark:]}"
            )

        with allure.step("Reboot device"):
            assert driver.reboot(timeout=30.0), "Device failed to reboot and return to ready prompt"

        with allure.step("Verify status indicates known saved profile"):
            status = driver.wifi_status()
            assert not status["connected"], "PRD states device starts disconnected after reboot"
            assert status["ssid"] == ssid or (status["ssid"] and ssid in status["ssid"])

        with allure.step("Restore connection via 'reconnect'"):
            reconnect_mark = driver.buffer_len()
            reconnected = driver.wifi_reconnect(timeout=30.0)
            assert reconnected, (
                "Saved profile did not produce both association and IP UART "
                "events after reboot; "
                f"UART: {driver.uart_log[reconnect_mark:]}"
            )
            status_after = driver.wifi_status()
            assert status_after["connected"]


@pytest.mark.parametrize(
    ("connected", "logged_in", "expected_color"),
    [
        (False, False, "RED"),
        (False, True, "RED"),
        (True, False, "ORANGE"),
        (True, True, "GREEN"),
    ],
)
@pytest.mark.wifi
def test_status_led_prompt_uses_confirmed_link_and_login_state(
    connected: bool,
    logged_in: bool,
    expected_color: str,
) -> None:
    prompt = _status_led_prompt(
        {"connected": connected},
        is_logged_in=logged_in,
    )

    assert f"Wi-Fi is {'connected' if connected else 'disconnected'}" in prompt
    assert f"show {expected_color}" in prompt
    assert f"Do you see {expected_color}?" in prompt


def _connected_wifi_status(ssid: str = "TestAP") -> dict[str, Any]:
    return {
        "connected": True,
        "ssid": ssid,
        "ip": "192.168.1.105",
        "raw": [
            f"I (10) sentry:   link: buoy link '{ssid}', ip 192.168.1.105, rssi -33 dBm"
        ],
    }


@allure.story("Wi-Fi fixture restoration")
@allure.title("Keep a valid saved-profile reconnect without changing credentials")
@pytest.mark.wifi
def test_restore_wifi_skips_connect_fallback_after_valid_reconnect() -> None:
    driver = Mock()
    driver.buffer_len.return_value = 0
    driver.uart_log = ["RX < I (1) sentry: [LINK] connected to 'TestAP'"]
    driver.wifi_reconnect.return_value = True
    driver.wifi_status.return_value = _connected_wifi_status()

    _restore_saved_wifi(driver, "TestAP", "private-test-password")

    driver.wifi_reconnect.assert_called_once_with(timeout=22.0)
    driver.wifi_connect.assert_not_called()


@allure.story("Wi-Fi fixture restoration")
@allure.title("Fall back to configured credentials when saved-profile reconnect fails")
@pytest.mark.wifi
def test_restore_wifi_connects_with_configured_credentials_after_reconnect_failure() -> None:
    driver = Mock()
    driver.buffer_len.return_value = 0
    driver.uart_log = ["RX < E104 no IP address from router (DHCP timeout)"]
    driver.wifi_reconnect.return_value = False
    driver.wifi_connect.return_value = True
    driver.wifi_status.return_value = _connected_wifi_status()

    _restore_saved_wifi(driver, "TestAP", "private-test-password")

    driver.wifi_reconnect.assert_called_once_with(timeout=22.0)
    driver.wifi_connect.assert_called_once_with(
        "TestAP",
        "private-test-password",
        timeout=25.0,
    )


@allure.story("Wi-Fi fixture restoration")
@allure.title("Fall back when reconnect reports success without a valid IP")
@pytest.mark.wifi
def test_restore_wifi_falls_back_when_reconnect_has_no_valid_ip() -> None:
    driver = Mock()
    driver.buffer_len.return_value = 0
    driver.uart_log = ["RX < W114 already connected"]
    driver.wifi_reconnect.return_value = True
    driver.wifi_connect.return_value = True
    driver.wifi_status.side_effect = [
        {
            **_connected_wifi_status(),
            "ip": "0.0.0.0",
        },
        _connected_wifi_status(),
    ]

    _restore_saved_wifi(driver, "TestAP", "private-test-password")

    driver.wifi_connect.assert_called_once_with(
        "TestAP",
        "private-test-password",
        timeout=25.0,
    )


@allure.story("Wi-Fi fixture restoration")
@allure.title("Report both failed Wi-Fi restoration attempts")
@pytest.mark.wifi
def test_restore_wifi_fails_explicitly_when_reconnect_and_connect_fail() -> None:
    driver = Mock()
    driver.buffer_len.return_value = 0
    driver.uart_log = ["RX < E104 no IP address from router (DHCP timeout)"]
    driver.wifi_reconnect.return_value = False
    driver.wifi_connect.return_value = False

    with pytest.raises(
        AssertionError,
        match="Saved-profile reconnect failed.*connect fallback did not receive",
    ):
        _restore_saved_wifi(driver, "TestAP", "private-test-password")

    driver.wifi_connect.assert_called_once_with(
        "TestAP",
        "private-test-password",
        timeout=25.0,
    )
