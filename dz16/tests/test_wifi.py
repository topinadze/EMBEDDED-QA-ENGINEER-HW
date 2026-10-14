from __future__ import annotations

from collections.abc import Callable, Generator
import re

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import prepare_observation, wifi_indicator_color


def _assert_valid_connection(status: dict[str, object]) -> None:
    assert DeviceDriver.wifi_connection_is_valid(status), (
        f"Wi-Fi status must contain connected, SSID, usable IPv4, and RSSI: {status!r}"
    )


def _assert_response(lines: list[str], expected: str) -> None:
    output = "\n".join(lines)
    assert expected.casefold() in output.casefold(), (
        f"Expected {expected!r} in UART response:\n{output}"
    )


def _wifi_status_is_connected(lines: list[str]) -> bool:
    return DeviceDriver.wifi_connection_is_valid(
        DeviceDriver.parse_wifi_status(lines)
    )


def _needs_recovery(report: pytest.TestReport | None) -> bool:
    if report is None:
        return False
    return report.failed or (report.skipped and hasattr(report, "wasxfail"))


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("Wi-Fi")
@pytest.mark.wifi
class TestWifiButtons:
    @pytest.fixture(autouse=True)
    def reboot_after_failure(
        self,
        request: pytest.FixtureRequest,
        device_driver: DeviceDriver,
    ) -> Generator[None, None, None]:
        yield

        reports = (
            getattr(request.node, "rep_setup", None),
            getattr(request.node, "rep_call", None),
        )
        if any(_needs_recovery(report) for report in reports):
            setattr(request.node, "wifi_failure_reboot_attempted", True)
            with allure.step("Reboot ESP32 after Wi-Fi test failure"):
                device_driver.reboot(timeout=30.0)

    @allure.story("FR-W5: K3 reconnects with saved credentials")
    @allure.title("K3 toggles Wi-Fi off and reconnects with saved credentials")
    @pytest.mark.interactive
    @pytest.mark.xfail(
        reason="Known BUG-02; see dz16/REPORT.md, section 5 (BUG-02)."
    )
    def test_k3_reconnects_saved_wifi(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
    ) -> None:
        with allure.step("Verify Wi-Fi is connected before the K3 toggle scenario"):
            initial_status = device_driver.send_command("status")
            if not _wifi_status_is_connected(initial_status):
                pytest.fail(
                    "This K3 toggle check requires an active Wi-Fi connection with a "
                    "valid SSID and IP. Connect the device before starting the run."
                )

        with allure.step("Turn the lamp off before checking Wi-Fi status indication"):
            _assert_response(device_driver.lamp_off(), "[LAMP] off")
            assert device_driver.lamp_status()["lamp"] == "off"

        prepare_observation(
            manual_prepare,
            action="press physical K3 once to disconnect Wi-Fi, then again to reconnect",
            expected="UART reports disconnect, reconnect, and an IP address",
            duration="allow up to 30 seconds for reconnection",
        )
        with allure.step("Press K3 once and verify Wi-Fi disconnect action"):
            assert manual_check(
                "Press physical K3 once to disconnect Wi-Fi, then confirm to continue."
            )
            k3_disconnected = device_driver.wait_for(
                "[K3] wifi disconnect", timeout=5.0
            )
            assert k3_disconnected, (
                "UART did not report the first K3 disconnect action."
            )

        with allure.step("Press K3 again and wait for reconnect using saved credentials"):
            assert manual_check(
                "Press physical K3 a second time to reconnect using saved credentials, "
                "then confirm to continue."
            )
            reconnect_event = device_driver.wait_for(
                "[K3] wifi reconnect (saved credentials)", timeout=5.0
            )
            got_ip = device_driver.wait_for("got ip:", timeout=30.0)
            status_after_reconnect = device_driver.send_command("status")

            assert reconnect_event, (
                "UART did not report K3 reconnect with saved credentials."
            )
            assert got_ip, "Device did not report an IP address after K3 reconnect."
            assert _wifi_status_is_connected(
                status_after_reconnect
            ), f"Wi-Fi status lacks a valid connection: {status_after_reconnect!r}"

        wifi_status = device_driver.wifi_status()
        indicator_color = wifi_indicator_color(
            DeviceDriver.wifi_connection_is_valid(wifi_status)
        )
        prepare_observation(
            manual_prepare,
            action="the reconnect attempt is complete and the lamp is off",
            expected=f"the status LED shows {indicator_color} for the current Wi-Fi status",
            duration="about 5 seconds",
        )
        with allure.step(f"Verify the Wi-Fi LED indication is {indicator_color}"):
            connected_indicator_visible = manual_check(
                f"After reconnect, with the lamp off, does the LED show the expected "
                f"{indicator_color} Wi-Fi status indication?"
            )
            assert connected_indicator_visible

    @allure.story("FR-W4/FR-W6: K3 disconnect status and indication")
    @allure.title("K3 disconnect reports Wi-Fi disconnected and shows red status LED")
    @pytest.mark.interactive
    @pytest.mark.xfail(
        reason="Known BUG-01; see dz16/REPORT.md, section 5 (BUG-01)."
    )
    def test_k3_disconnect_status_and_led(
        self,
        device_driver: DeviceDriver,
        firmware_version: str,
        manual_check: Callable[[str], bool],
        manual_prepare: Callable[[str], None],
    ) -> None:
        with allure.step("Verify Wi-Fi is connected before the K3 disconnect check"):
            initial_status = device_driver.send_command("status")
            if not _wifi_status_is_connected(initial_status):
                pytest.fail(
                    "This check requires an active Wi-Fi connection with a valid SSID "
                    "and IP. Connect the device before starting the interactive run."
                )

        with allure.step("Turn the lamp off before checking Wi-Fi status indication"):
            _assert_response(device_driver.lamp_off(), "[LAMP] off")
            assert device_driver.lamp_status()["lamp"] == "off"

        prepare_observation(
            manual_prepare,
            action="press physical K3 once to disconnect Wi-Fi",
            expected="UART reports disconnect; the lamp stays off and the Wi-Fi LED matches reported state",
            duration="about 5 seconds",
        )
        with allure.step("Press K3 and verify the Wi-Fi disconnect action"):
            assert manual_check(
                "Press physical K3 once to disconnect Wi-Fi. After pressing it, "
                "confirm to continue."
            )
            k3_disconnected = device_driver.wait_for(
                "[K3] wifi disconnect", timeout=5.0
            )
            assert k3_disconnected, "UART did not report the K3 disconnect action."

        with allure.step("Observe the reported Wi-Fi status and the LED indication"):
            status_after_disconnect = device_driver.send_command("status")
            wifi_status = DeviceDriver.parse_wifi_status(status_after_disconnect)
            indicator_color = wifi_indicator_color(
                DeviceDriver.wifi_connection_is_valid(wifi_status)
            )
            prepare_observation(
                manual_prepare,
                action="the device has reported its Wi-Fi status after K3",
                expected=f"the lamp is off and the LED shows {indicator_color}",
                duration="about 5 seconds",
            )
            wifi_indicator_visible = manual_check(
                f"With the lamp off, does the LED show the expected "
                f"{indicator_color} Wi-Fi status indication?"
            )

        # Both observations are collected first so one failure cannot hide the other.
        with allure.step(
            f"Verify status reports disconnected and the LED is {indicator_color}"
        ):
            failures = []
            if not any(
                "wifi: disconnected" in line.casefold()
                for line in status_after_disconnect
            ):
                failures.append(
                    f"Wi-Fi status did not report disconnected: {status_after_disconnect!r}"
                )
            if not wifi_indicator_visible:
                failures.append(
                    f"Operator did not see the expected {indicator_color} Wi-Fi LED."
                )
            assert not failures, " | ".join(failures)


@allure.epic("HW-16: Smart Lamp and OTA verification")
@allure.feature("Wi-Fi station")
@pytest.mark.wifi
class TestWifiStation:
    @allure.story("FR-W4: Scan lists SSID, RSSI, and channel")
    @allure.title("Wi-Fi scan reports RSSI and channel for the configured network")
    @pytest.mark.positive
    def test_scan_reports_ssid_rssi_and_channel(
        self,
        wifi_ssid: str,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        with allure.step("Scan for nearby access points"):
            ssids = device_driver.wifi_scan(timeout=12.0)
            access_points = device_driver.parse_wifi_scan(device_driver.uart_log)

        assert ssids, "Wi-Fi scan returned no access points."
        target = [
            point
            for point in access_points
            if str(point["ssid"]).casefold() == wifi_ssid.casefold()
        ]
        assert target, f"Configured SSID {wifi_ssid!r} was absent from scan output."
        assert any(
            point["rssi"] is not None and point["channel"] is not None
            for point in target
        ), f"Target scan row did not report both RSSI and channel: {target!r}"

    @allure.story("FR-W1: Connect and acquire an IP address")
    @allure.title("Valid Wi-Fi credentials connect within 10 seconds and report status")
    @pytest.mark.positive
    @pytest.mark.persistent
    def test_connect_reports_ip_and_rssi(
        self,
        wifi_credentials: tuple[str, str],
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        ssid, password = wifi_credentials
        with allure.step("Connect using the configured Wi-Fi credentials"):
            connected = device_driver.wifi_connect(
                ssid=ssid, password=password, timeout=10.0
            )
        assert connected, f"Connection to configured SSID {ssid!r} did not succeed."
        assert device_driver.last_wifi_connect_duration is not None
        assert device_driver.last_wifi_connect_duration <= 10.0, (
            "Wi-Fi connection exceeded the FR-W1 limit: "
            f"{device_driver.last_wifi_connect_duration:.2f} seconds."
        )

        with allure.step("Verify connected status has SSID, non-zero IPv4, and RSSI"):
            _assert_valid_connection(device_driver.wifi_status())

    @allure.story("FR-W1: Reject a short Wi-Fi password")
    @allure.title("Wi-Fi rejects a password shorter than eight characters")
    @pytest.mark.negative
    def test_short_password_is_rejected_before_connecting(
        self,
        wifi_ssid: str,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        device_driver.wifi_disconnect()
        with allure.step("Attempt connection with a deliberately short test value"):
            connected = device_driver.wifi_connect(
                ssid=wifi_ssid, password="short", timeout=3.0
            )

        output = "\n".join(device_driver.uart_log).casefold()
        assert not connected, "Firmware accepted a password shorter than eight characters."
        assert re.search(
            r"password too (?:short|\[redacted\]) \(min 8 chars\)", output
        ), "UART did not report the documented short-password rejection."
        assert "connecting to ssid" not in output, (
            "Firmware started a Wi-Fi connection attempt after rejecting the short password."
        )

    @allure.story("FR-W1: Reject invalid credentials")
    @allure.title("A wrong password is rejected and the device remains responsive")
    @pytest.mark.negative
    def test_wrong_password_is_rejected(
        self,
        wifi_ssid: str,
        wrong_wifi_password: str,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        ssid = wifi_ssid
        device_driver.wifi_disconnect()

        with allure.step("Attempt a connection using the configured wrong password"):
            connected = device_driver.wifi_connect(
                ssid=ssid, password=wrong_wifi_password, timeout=18.0
            )
        output = "\n".join(device_driver.uart_log).casefold()

        assert not connected, "Firmware accepted the configured wrong password."
        assert re.search(
            r"failed to connect to ssid|connection timeout|connect to the ap fail",
            output,
        ), "UART did not report a connection failure or timeout."
        with allure.step("Verify the CLI still responds after the failed connection"):
            help_output = "\n".join(device_driver.send_command("help", timeout=2.0))
        assert "connect" in help_output.casefold(), (
            "The CLI did not list Wi-Fi connect after the failed attempt."
        )

    @allure.story("FR-W1: Reject a missing access point")
    @allure.title("A missing SSID times out without making the CLI unresponsive")
    @pytest.mark.negative
    def test_missing_ssid_is_rejected(
        self,
        missing_wifi_ssid: str,
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        device_driver.wifi_disconnect()

        with allure.step("Attempt to connect to the configured absent SSID"):
            connected = device_driver.wifi_connect(
                ssid=missing_wifi_ssid,
                password="not-a-valid-password",
                timeout=18.0,
            )
        output = "\n".join(device_driver.uart_log).casefold()

        assert not connected, (
            f"Firmware connected to absent SSID {missing_wifi_ssid!r}."
        )
        assert re.search(
            r"failed to connect to ssid|connection timeout|connect to the ap fail",
            output,
        ), (
            "UART did not report a connection failure or timeout for the absent SSID."
        )
        assert "connect" in "\n".join(
            device_driver.send_command("help", timeout=2.0)
        ).casefold(), "The CLI did not respond after the missing-SSID attempt."

    @allure.story("FR-W4: Disconnect status")
    @allure.title("Disconnect reports Wi-Fi disconnected")
    @allure.issue(
        "BUG-01",
        name="Status may report connected with an empty SSID or zero IP after disconnect.",
    )
    @pytest.mark.positive
    @pytest.mark.persistent
    def test_disconnect_updates_status(
        self,
        wifi_credentials: tuple[str, str],
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        ssid, password = wifi_credentials
        assert device_driver.wifi_connect(ssid=ssid, password=password), (
            "Precondition failed: could not connect before disconnect verification."
        )

        with allure.step("Disconnect and read the resulting Wi-Fi status"):
            device_driver.wifi_disconnect()
            status = device_driver.wifi_status()

        if (
            firmware_version in {"1.3.0", "1.4.0"}
            and status["connected"]
            and (not status["ssid"] or status["ip"] in {None, "0.0.0.0"})
        ):
            pytest.xfail(
                "BUG-01: status reports connected with an empty SSID or zero IP "
                "after disconnect; see dz16/REPORT.md section 5."
            )
        assert not status["connected"], (
            f"Wi-Fi status should report disconnected after the command: {status!r}"
        )

    @allure.story("FR-W2: Credentials persist and manual connect uses saved values")
    @allure.title("Saved Wi-Fi credentials survive reboot and reconnect after Enter")
    @pytest.mark.persistent
    @pytest.mark.positive
    def test_credentials_survive_reboot_and_reconnect_with_enter(
        self,
        wifi_credentials: tuple[str, str],
        device_driver: DeviceDriver,
        firmware_version: str,
    ) -> None:
        ssid, password = wifi_credentials
        assert device_driver.wifi_connect(ssid=ssid, password=password), (
            "Precondition failed: could not save Wi-Fi credentials through a connection."
        )

        with allure.step("Reboot and confirm credentials are saved without auto-connect"):
            log_start_idx = len(device_driver.uart_log)
            assert device_driver.reboot(), "Device did not report ready after reboot."
            boot_output = "\n".join(device_driver.uart_log[log_start_idx:]).casefold()
            assert "saved credentials found but auto-connect disabled" in boot_output, (
                "Boot output did not confirm saved credentials with auto-connect disabled."
            )

        with allure.step("Use an empty SSID entry to reconnect from saved credentials"):
            assert device_driver.wifi_connect_saved(), (
                "Connect with Enter did not use the saved Wi-Fi credentials."
            )
            _assert_valid_connection(device_driver.wifi_status())
