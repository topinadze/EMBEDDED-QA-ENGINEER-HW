from __future__ import annotations

from collections.abc import Callable, Generator
import ipaddress

import allure
import pytest

from drivers.device_driver import DeviceDriver


def _assert_response(lines: list[str], expected: str) -> None:
    output = "\n".join(lines)
    assert expected.casefold() in output.casefold(), (
        f"Expected {expected!r} in UART response:\n{output}"
    )


def _wifi_status_is_connected(lines: list[str]) -> bool:
    if "wifi: connected" not in "\n".join(lines).casefold():
        return False

    fields = {
        key: line.casefold().split(f"{key}:", 1)[1].strip()
        for line in lines
        for key in ("ssid", "ip")
        if f"{key}:" in line.casefold()
    }
    if not fields.get("ssid"):
        return False

    try:
        address = ipaddress.ip_address(fields["ip"])
    except (KeyError, ValueError):
        return False
    return not address.is_unspecified


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
        if any(report is not None and report.failed for report in reports):
            setattr(request.node, "wifi_failure_reboot_attempted", True)
            with allure.step("Reboot ESP32 after Wi-Fi test failure"):
                device_driver.send_command("reboot", timeout=0.6)

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

        with allure.step("Verify the connected Wi-Fi LED indication is dim green"):
            connected_indicator_visible = manual_check(
                "After reconnect, with the lamp off, does the LED show the dim green "
                "Wi-Fi status indication?"
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

        with allure.step("Press K3 and verify the Wi-Fi disconnect action"):
            assert manual_check(
                "Press physical K3 once to disconnect Wi-Fi. After pressing it, "
                "confirm to continue."
            )
            k3_disconnected = device_driver.wait_for(
                "[K3] wifi disconnect", timeout=5.0
            )
            assert k3_disconnected, "UART did not report the K3 disconnect action."

        with allure.step("Verify disconnected status and the dim-red LED indication"):
            status_after_disconnect = device_driver.send_command("status")
            assert any(
                "wifi: disconnected" in line.casefold()
                for line in status_after_disconnect
            ), (
                "Wi-Fi status did not report disconnected: "
                f"{status_after_disconnect!r}"
            )
            red_indicator_visible = manual_check(
                "With the lamp off and Wi-Fi disconnected, does the LED show "
                "the dim red Wi-Fi status indication?"
            )
            assert red_indicator_visible
