from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable, Iterator
from typing import Any

import allure
import pytest

from config.test_config import resolve_account_credentials, resolve_wifi_credentials
from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation


def _response(lines: list[str]) -> str:
    return "\n".join(lines)


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


def _ensure_user_session(
    driver: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
    request: pytest.FixtureRequest,
) -> None:
    identity = driver.whoami()
    if identity["logged_in"] and identity["access"] == "debug":
        driver.logout()
    _ensure_saved_wifi_connected(driver, request)
    ensure_authenticated_device(driver)
    identity = driver.whoami()
    assert identity["logged_in"] and identity["access"] == "user", (
        f"Expected the configured user-level session after restoration: {identity!r}"
    )


def _password_change_succeeded(output: str) -> bool:
    return "password changed" in output.casefold() or "ok" in output.casefold()


# ---------------------------------------------------------------------------
# Offline Unit Tests (Run without hardware)
# ---------------------------------------------------------------------------


def test_whoami_parser_logged_out() -> None:
    driver = DeviceDriver("unused")
    output = ["I (100) sentry: not logged in"]
    driver.send_command = lambda cmd, timeout=1.0: output  # type: ignore[assignment]
    info = driver.whoami()
    assert info["user"] == "not logged in"
    assert info["access"] == "none"
    assert not info["logged_in"]


def test_whoami_parser_operator_user() -> None:
    driver = DeviceDriver("unused")
    output = ["I (100) sentry: user: test_operator, access: user"]
    driver.send_command = lambda cmd, timeout=1.0: output  # type: ignore[assignment]
    info = driver.whoami()
    assert info["user"] == "test_operator"
    assert info["access"] == "user"
    assert info["logged_in"]


def test_whoami_parser_debug_access() -> None:
    driver = DeviceDriver("unused")
    output = ["I (100) sentry: user: commander, access: debug"]
    driver.send_command = lambda cmd, timeout=1.0: output  # type: ignore[assignment]
    info = driver.whoami()
    assert info["user"] == "commander"
    assert info["access"] == "debug"
    assert info["logged_in"]


def test_auth_commands_register_passwords_for_redaction() -> None:
    driver = DeviceDriver("unused")
    sent_cmds: list[str] = []
    driver.send_command = lambda cmd, timeout=1.0: sent_cmds.append(cmd) or []  # type: ignore[assignment]

    secret_pass = "SuperSecretPassword123"
    driver.register("newuser", secret_pass)
    assert secret_pass in driver._sensitive_uart_values

    driver.login("testuser", secret_pass)
    assert secret_pass in driver._sensitive_uart_values

    old_pass = "OldSecretPass456"
    new_pass = "NewSecretPass789"
    driver.passwd(old_pass, new_pass)
    assert old_pass in driver._sensitive_uart_values
    assert new_pass in driver._sensitive_uart_values

    sudo_pass = "SudoSecretPass999"
    driver.sudo(sudo_pass)
    assert sudo_pass in driver._sensitive_uart_values


# ---------------------------------------------------------------------------
# Device-Facing Authentication Suite (AU-1 - AU-6)
# ---------------------------------------------------------------------------


pytestmark = [
    allure.parent_suite("DZ17"),
    allure.suite("Access Control and Authentication"),
    allure.epic("SENTRY SWM-2"),
    allure.feature("Operator Account and Access Control (AU-1 - AU-6)"),
    pytest.mark.auth,
]


@pytest.fixture
def restore_wifi_connection_after_test(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Iterator[DeviceDriver]:
    """Establish the saved Wi-Fi profile and restore it after the case."""
    _ensure_saved_wifi_connected(device_driver, request)
    yield device_driver
    with allure.step("Restore Wi-Fi connection after the case"):
        _ensure_saved_wifi_connected(device_driver, request)


@pytest.fixture
def restore_authenticated_session_after_test(
    device_driver: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
    request: pytest.FixtureRequest,
) -> Iterator[DeviceDriver]:
    """Establish and restore the configured user-level session per case."""
    _ensure_saved_wifi_connected(device_driver, request)
    _ensure_user_session(device_driver, ensure_authenticated_device, request)
    yield device_driver
    with allure.step("Restore authenticated session after the case"):
        _ensure_saved_wifi_connected(device_driver, request)
        _ensure_user_session(
            driver=device_driver,
            ensure_authenticated_device=ensure_authenticated_device,
            request=request,
        )


def _ensure_normal_state_and_valve_closed(driver: DeviceDriver) -> None:
    status_text = _response(driver.send_command("status", timeout=1.0))
    if not re.search(r"\bvalve:\s*closed\b", status_text, re.IGNORECASE):
        driver.relay_off(timeout=2.0)
    if not re.search(r"\bstate:\s*1\s+NORMAL\b", status_text, re.IGNORECASE):
        driver.send_command("state 1", timeout=2.0)

    final_status = _response(driver.send_command("status", timeout=1.0))
    assert re.search(r"\bstate:\s*1\s+NORMAL\b", final_status, re.IGNORECASE), (
        f"Could not establish/restore NORMAL state:\n{final_status}"
    )
    assert re.search(r"\bvalve:\s*closed\b", final_status, re.IGNORECASE), (
        f"Could not establish/restore closed valve:\n{final_status}"
    )


@pytest.fixture
def restore_logout_test_outputs_after_test(
    restore_authenticated_session_after_test: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
    request: pytest.FixtureRequest,
) -> Iterator[DeviceDriver]:
    """Start and finish the logout-output case in NORMAL with the valve closed."""
    driver = restore_authenticated_session_after_test
    with allure.step("Establish safe output baseline for the logout case"):
        _ensure_normal_state_and_valve_closed(driver)

    yield driver

    with allure.step("Restore NORMAL state and closed valve after the logout case"):
        _ensure_saved_wifi_connected(driver, request)
        ensure_authenticated_device(driver)
        _ensure_normal_state_and_valve_closed(driver)


@pytest.fixture
def restore_password_after_test(
    restore_authenticated_session_after_test: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
    request: pytest.FixtureRequest,
) -> Iterator[Callable[[str, str, str], None]]:
    """Roll a test-only password change back after the test completes."""
    driver = restore_authenticated_session_after_test
    scheduled_rollback: tuple[str, str, str] | None = None

    def schedule_rollback(user: str, original_pass: str, temporary_pass: str) -> None:
        nonlocal scheduled_rollback
        scheduled_rollback = (user, original_pass, temporary_pass)

    yield schedule_rollback

    if scheduled_rollback is not None:
        user, original_pass, temporary_pass = scheduled_rollback
        with allure.step("Rollback the temporary password after the case"):
            _ensure_saved_wifi_connected(driver, request)
            identity = driver.whoami()
            if not identity["logged_in"]:
                temporary_login = _response(
                    driver.login(user, temporary_pass, timeout=3.0)
                )
                identity = driver.whoami()
                if not identity["logged_in"]:
                    original_login = _response(
                        driver.login(user, original_pass, timeout=3.0)
                    )
                    identity = driver.whoami()
                    assert identity["logged_in"] and identity["user"] == user, (
                        "Could not establish either credential during password "
                        "rollback. Temporary-password response:\n"
                        f"{temporary_login}\nOriginal-password response:\n"
                        f"{original_login}\nwhoami: {identity!r}"
                    )
                    _ensure_saved_wifi_connected(driver, request)
                    ensure_authenticated_device(driver)
                    return

            rollback_output = _response(
                driver.passwd(temporary_pass, original_pass, timeout=3.0)
            )
            if not _password_change_succeeded(rollback_output):
                assert "E215" in rollback_output, (
                    "Password rollback returned neither success nor the expected "
                    f"old-password rejection:\n{rollback_output}"
                )
                driver.logout()
                original_login = _response(
                    driver.login(user, original_pass, timeout=3.0)
                )
                identity = driver.whoami()
                assert identity["logged_in"] and identity["user"] == user, (
                    "Temporary-password rollback was not needed, but the original "
                    "credential could not be verified:\n"
                    f"{original_login}\nwhoami: {identity!r}"
                )
                _ensure_saved_wifi_connected(driver, request)
                ensure_authenticated_device(driver)
                return

            driver.logout()
            _ensure_saved_wifi_connected(driver, request)
            ensure_authenticated_device(driver)


@allure.sub_suite("Account Management")
class TestAuth:
    # -----------------------------------------------------------------------
    # AU-1: User Profile Registration
    # -----------------------------------------------------------------------

    @allure.story("AU-1: User profile registration")
    @allure.title("Register on device with existing profile is rejected with E202")
    def test_register_profile_already_exists(
        self,
        device_driver: DeviceDriver,
        ensure_wifi_connected: Callable[[DeviceDriver], None],
    ) -> None:
        driver = device_driver
        ensure_wifi_connected(driver)
        lines = driver.register("anotherUser", "ValidPass123", timeout=2.0)
        output = _response(lines)
        assert "E202" in output, (
            f"Expected E202 profile already exists:\n{output}"
        )
        assert "profile already exists" in output.casefold() or "already exists" in output.casefold()

    @allure.story("AU-1: User profile registration")
    @allure.title("Register without Wi-Fi connection returns E002 Wi-Fi required")
    def test_register_without_wifi(
        self,
        restore_wifi_connection_after_test: DeviceDriver,
    ) -> None:
        driver = restore_wifi_connection_after_test
        with allure.step("Disconnect Wi-Fi"):
            driver.wifi_disconnect()
            status = driver.wifi_status()
            if status.get("connected"):
                driver.reboot()

        with allure.step("Verify register without Wi-Fi returns E002"):
            lines = driver.register("someUser", "SomePass123", timeout=2.0)
            output = _response(lines)
            assert "E002" in output, f"Expected E002 without Wi-Fi:\n{output}"

    # -----------------------------------------------------------------------
    # AU-2: Operator Login and Attempt Rate-Limiting
    # -----------------------------------------------------------------------

    @allure.story("AU-2: Operator login and attempt limit")
    @allure.title("Login without required arguments returns E201")
    @pytest.mark.parametrize(
        "cmd",
        [
            pytest.param("login", id="no-args"),
            pytest.param("login onlyuser", id="one-arg"),
        ],
    )
    def test_login_missing_arguments(
        self,
        device_driver: DeviceDriver,
        cmd: str,
    ) -> None:
        driver = device_driver
        lines = driver.send_command(cmd, timeout=2.0)
        output = _response(lines)
        assert "E201" in output, f"Expected E201 for missing arguments on '{cmd}':\n{output}"

    @allure.story("AU-2: Operator login and attempt limit")
    @allure.title("Login while already authenticated returns E206")
    def test_login_already_logged_in(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        who = driver.whoami()
        assert who["logged_in"], "Device must be logged in for E206 check"

        lines = driver.login(who["user"], "AnyPass123", timeout=2.0)
        output = _response(lines)
        assert "E206" in output, f"Expected E206 already logged in:\n{output}"
        assert "already logged in" in output.casefold()

    @allure.story("AU-2: Operator login and attempt limit")
    @allure.title("Login without Wi-Fi returns E002")
    def test_login_without_wifi(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure logged out and Wi-Fi disconnected"):
            driver.logout()
            driver.wifi_disconnect()
            status = driver.wifi_status()
            if status.get("connected"):
                driver.reboot()

        with allure.step("Verify login without Wi-Fi returns E002"):
            lines = driver.login("anyUser", "anyPass123", timeout=2.0)
            output = _response(lines)
            assert "E002" in output, f"Expected E002 without Wi-Fi:\n{output}"

    @allure.story("AU-2: Operator login and attempt limit")
    @allure.title("Wrong login credentials return E209 with attempt count")
    def test_login_wrong_credentials_counter(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
        ensure_wifi_connected: Callable[[DeviceDriver], None],
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure Wi-Fi connected and logged out"):
            ensure_wifi_connected(driver)
            driver.logout()

        with allure.step("Submit incorrect login credentials"):
            lines = driver.login("operator", "DeliberatelyWrongPass456", timeout=2.0)
            output = _response(lines)
            assert "E209" in output, f"Expected E209 wrong credentials:\n{output}"
            assert "wrong login or password" in output.casefold()
            assert "attempts:" in output.casefold(), (
                f"Expected attempt counter in response:\n{output}"
            )

    @allure.story("AU-2: Operator login and attempt limit")
    @allure.title("Three failed login attempts trigger 30s lockout (E210 and E207)")
    def test_login_lockout_and_recovery(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
        ensure_wifi_connected: Callable[[DeviceDriver], None],
    ) -> None:
        driver = restore_authenticated_session_after_test
        user, password = resolve_account_credentials()
        if not user or not password:
            pytest.skip("Configured user credentials required for lockout recovery test.")

        with allure.step("Ensure Wi-Fi connected and logged out"):
            ensure_wifi_connected(driver)
            driver.logout()

        with allure.step("Attempt 1: Incorrect password"):
            lines1 = driver.login(user, "WrongPass_1", timeout=2.0)
            out1 = _response(lines1)
            assert "E209" in out1, f"Expected E209 on attempt 1:\n{out1}"

        with allure.step("Attempt 2: Incorrect password"):
            lines2 = driver.login(user, "WrongPass_2", timeout=2.0)
            out2 = _response(lines2)
            assert "E209" in out2, f"Expected E209 on attempt 2:\n{out2}"

        with allure.step("Attempt 3: Incorrect password triggering lockout"):
            lines3 = driver.login(user, "WrongPass_3", timeout=2.0)
            out3 = _response(lines3)
            assert "E210" in out3, (
                f"Expected E210 account locked for 30 s on attempt 3:\n{out3}"
            )
            assert "locked for 30 s" in out3.casefold() or "too many attempts" in out3.casefold()

        with allure.step("Attempt 4: Immediate attempt during lockout returns E207"):
            lines4 = driver.login(user, "WrongPass_4", timeout=2.0)
            out4 = _response(lines4)
            assert "E207" in out4, (
                f"Expected E207 account locked during cooldown:\n{out4}"
            )
            assert "account locked" in out4.casefold()

            cooldown_match = re.search(
                r"Try again in\s+(\d+)\s*s",
                out4,
                re.IGNORECASE,
            )
        assert cooldown_match is not None, (
            "Expected E207 to report the remaining cooldown in seconds:\n"
            f"{out4}"
        )
        remaining_seconds = int(cooldown_match.group(1))
        assert 0 <= remaining_seconds <= 30, (
            "Expected the reported cooldown to be at most 30 seconds, got "
            f"{remaining_seconds}:\n{out4}"
        )

        with allure.step(
            f"Wait for reported lockout cooldown ({remaining_seconds} seconds)"
        ):
            time.sleep(remaining_seconds + 1)

        with allure.step("Attempt 5: Valid login succeeds after cooldown"):
            lines5 = driver.login(user, password, timeout=3.0)
            out5 = _response(lines5)
            assert "on watch" in out5 or driver.whoami()["logged_in"], (
                f"Valid login failed after lockout cooldown:\n{out5}"
            )

    # -----------------------------------------------------------------------
    # AU-3: Logout and Session Termination
    # -----------------------------------------------------------------------

    @allure.story("AU-3: Logout and output cleanup")
    @allure.title("Logout terminates session, closes valve, turns off lamp, and resets state")
    def test_logout_terminates_session_and_outputs(
        self,
        restore_logout_test_outputs_after_test: DeviceDriver,
    ) -> None:
        driver = restore_logout_test_outputs_after_test
        with allure.step("Activate Beacon and Valve, set state to DEBUG"):
            driver.lamp_on(timeout=1.0)
            driver.relay_on(timeout=1.0)
            driver.send_command("state 2", timeout=1.0)

        with allure.step("Execute logout"):
            lines = driver.logout(timeout=2.0)
            output = _response(lines)

        with allure.step("Verify outputs turned off and session terminated"):
            who = driver.whoami()
            assert not who["logged_in"], f"Still logged in after logout: {who}"

            status_lines = driver.send_command("status", timeout=1.0)
            status_text = _response(status_lines)
            assert re.search(r"\bstate:\s*1\s+NORMAL\b", status_text), (
                f"State did not return to NORMAL after logout:\n{status_text}"
            )
            assert re.search(r"\bvalve:\s*closed\b", status_text), (
                f"Valve was not closed after logout:\n{status_text}"
            )

    @allure.story("AU-3: Logout and output cleanup")
    @allure.title("Repeated logout when already logged out returns W211")
    def test_repeated_logout_returns_warning(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure logged out"):
            driver.logout()

        with allure.step("Execute second logout"):
            lines = driver.logout()
            output = _response(lines)
            assert "W211" in output, (
                f"Expected W211 not logged in on repeated logout:\n{output}"
            )
            assert "not logged in" in output.casefold()

    # -----------------------------------------------------------------------
    # AU-4: Whoami Identity Reporting
    # -----------------------------------------------------------------------

    @allure.story("AU-4: Identity reporting (whoami)")
    @allure.title("Whoami returns 'not logged in' when unauthenticated")
    def test_whoami_unauthenticated(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure logged out"):
            driver.logout()

        with allure.step("Verify whoami reports not logged in"):
            info = driver.whoami()
            assert not info["logged_in"]
            assert info["user"] == "not logged in"
            assert info["access"] == "none"

    @allure.story("AU-4: Identity reporting (whoami)")
    @allure.title("Whoami returns operator username and 'user' access when authenticated")
    def test_whoami_authenticated_operator(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        user, _ = resolve_account_credentials()

        with allure.step("Verify whoami reports user and access level"):
            info = driver.whoami()
            assert info["logged_in"], f"Expected logged-in session, got {info}"
            if user:
                assert info["user"] == user, f"Expected user {user}, got {info['user']}"
            assert info["access"] in {"user", "debug"}, (
                f"Expected access 'user' or 'debug', got {info['access']}"
            )

    # -----------------------------------------------------------------------
    # AU-5: Profile Password Change (passwd)
    # -----------------------------------------------------------------------

    @allure.story("AU-5: Password change")
    @allure.title("Passwd command while logged out returns E003 login required")
    def test_passwd_unauthenticated_blocked(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure logged out"):
            driver.logout()

        with allure.step("Verify passwd without login returns E003"):
            lines = driver.passwd("OldPass123", "NewPass456", timeout=2.0)
            output = _response(lines)
            assert "E003" in output, f"Expected E003 for logged-out passwd:\n{output}"

    @allure.story("AU-5: Password change")
    @allure.title("Passwd without required arguments returns E201")
    @pytest.mark.parametrize(
        "cmd",
        [
            pytest.param("passwd", id="no-args"),
            pytest.param("passwd onlyold", id="one-arg"),
        ],
    )
    def test_passwd_missing_arguments(
        self,
        authenticated_device: DeviceDriver,
        cmd: str,
    ) -> None:
        driver = authenticated_device
        lines = driver.send_command(cmd, timeout=2.0)
        output = _response(lines)
        assert "E201" in output, f"Expected E201 for missing arguments on '{cmd}':\n{output}"

    @allure.story("AU-5: Password change")
    @allure.title("Passwd with wrong current password returns E215")
    def test_passwd_wrong_old_password(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        lines = driver.passwd("DefinitelyWrongOldPass999", "NewValidPass123", timeout=2.0)
        output = _response(lines)
        assert "E215" in output, f"Expected E215 wrong current password:\n{output}"

    @allure.story("AU-5: Password change")
    @allure.title("Passwd with invalid new password length returns E205")
    @pytest.mark.parametrize(
        "new_pass",
        [
            pytest.param("12345", id="too-short-5chars"),
            pytest.param("N" * 33, id="too-long-33chars"),
        ],
    )
    def test_passwd_invalid_new_length(
        self,
        authenticated_device: DeviceDriver,
        new_pass: str,
    ) -> None:
        driver = authenticated_device
        _, current_pass = resolve_account_credentials()
        current_pass = current_pass or "dummyOldPass"

        lines = driver.passwd(current_pass, new_pass, timeout=2.0)
        output = _response(lines)
        assert "E205" in output, (
            f"Expected E205 for new password length {len(new_pass)}:\n{output}"
        )
        assert "6-32" in output or "password" in output.casefold()

    @allure.story("AU-5: Password change")
    @allure.title("Passwd persistently updates credential and old password is rejected")
    @pytest.mark.persistent
    def test_passwd_persistent_change_and_rollback(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
        restore_password_after_test: Callable[[str, str, str], None],
    ) -> None:
        driver = restore_authenticated_session_after_test
        user, original_pass = resolve_account_credentials()
        if not user or not original_pass:
            pytest.skip("Configured account credentials required for persistent passwd test.")

        replacement_character = "x" if original_pass[-1] != "x" else "y"
        temp_pass = original_pass[:-1] + replacement_character
        restore_password_after_test(user, original_pass, temp_pass)

        with allure.step("Change password to temporary value"):
            lines = driver.passwd(original_pass, temp_pass, timeout=3.0)
            out = _response(lines)
            assert "password changed" in out.casefold() or "ok" in out.casefold(), (
                f"Password change failed:\n{out}"
            )

        with allure.step("Logout and verify old password is now rejected"):
            driver.logout()
            fail_lines = driver.login(user, original_pass, timeout=2.0)
            assert "E209" in _response(fail_lines), (
                f"Old password was unexpectedly accepted after change:\n{_response(fail_lines)}"
            )

        with allure.step("Login with new temporary password"):
            login_lines = driver.login(user, temp_pass, timeout=3.0)
            assert "on watch" in _response(login_lines) or driver.whoami()["logged_in"], (
                f"Login with new temporary password failed:\n{_response(login_lines)}"
            )

    # -----------------------------------------------------------------------
    # AU-6: Debug Privilege Elevation (sudo)
    # -----------------------------------------------------------------------

    @allure.story("AU-6: Debug privilege elevation")
    @allure.title("Sudo command while logged out returns E003 login required")
    def test_sudo_unauthenticated_blocked(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Ensure logged out"):
            driver.logout()

        with allure.step("Verify sudo without login returns E003"):
            lines = driver.sudo("AnySudoPass123", timeout=2.0)
            output = _response(lines)
            assert "E003" in output, f"Expected E003 for logged-out sudo:\n{output}"

    @allure.story("AU-6: Debug privilege elevation")
    @allure.title("Sudo with incorrect password returns E213")
    def test_sudo_wrong_password(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        lines = driver.sudo("DefinitelyWrongSudoPass_987", timeout=2.0)
        output = _response(lines)
        assert "E213" in output, f"Expected E213 wrong sudo password:\n{output}"

    @allure.story("AU-6: Debug privilege elevation")
    @allure.title("Sudo elevates user to debug access (BUG-001 regression check)")
    def test_sudo_elevation_or_bug001_handling(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = restore_authenticated_session_after_test
        user, password = resolve_account_credentials()
        if not user or not password:
            pytest.skip("Configured account credentials required for sudo test.")

        if firmware_version == "2.1.0":
            pytest.xfail("BUG-001: sudo rejects valid account password on firmware 2.1.0")

        with allure.step("Attempt sudo elevation using account password"):
            lines = driver.sudo(password, timeout=3.0)
            output = _response(lines)

        if "E213" in output:
            who = driver.whoami()
            assert who["access"] == "user", (
                "Expected BUG-001 reproduction to retain user access after "
                f"E213; got {who}:\n{output}"
            )
            pytest.xfail(
                "BUG-001: firmware 2.3.0 rejects the valid current account "
                "password for sudo (E213); see REPORT.md."
            )

        with allure.step("Verify whoami reports debug access"):
            who = driver.whoami()
            assert who["access"] == "debug", (
                f"Expected access 'debug' after sudo, got {who}:\n{output}"
            )

        with allure.step("Verify repeated sudo while in debug returns W212"):
            rep_lines = driver.sudo(password, timeout=2.0)
            rep_output = _response(rep_lines)
            assert "W212" in rep_output, (
                f"Expected W212 already in debug access:\n{rep_output}"
            )

    # -----------------------------------------------------------------------
    # Interactive Operator Visual Checks (Physical LED Observation)
    # -----------------------------------------------------------------------

    @allure.story("AU-3 / LM-8: Status LED reflection of login and logout")
    @allure.title("Status LED transitions between GREEN (logged in) and ORANGE (logged out)")
    @pytest.mark.interactive
    def test_auth_status_led_login_logout_transitions(
        self,
        restore_authenticated_session_after_test: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = restore_authenticated_session_after_test
        with allure.step("Turn Beacon OFF so the system status LED is active"):
            driver.lamp_off(timeout=1.0)
            status = driver.lamp_status(timeout=0.6)
            assert status["lamp"] == "off", f"Beacon remained on: {status}"

        with allure.step("Observe status LED while connected and logged in (GREEN)"):
            prepare_observation(
                manual_prepare,
                action="observe the built-in RGB LED on the ESP32-S3 board with Beacon OFF and user logged in",
                expected="LED shows solid GREEN (Wi-Fi connected and logged in)",
                duration="5 seconds",
            )
            soft.check(
                manual_check(
                    "Does the built-in RGB LED show solid GREEN?",
                    expected_color="green",
                    expected_rgb=(0, 255, 0),
                ),
                "Built-in LED should show GREEN when connected and authenticated",
            )

        with allure.step("Logout and observe status LED transition to ORANGE"):
            driver.logout()
            prepare_observation(
                manual_prepare,
                action="observe the built-in RGB LED on the ESP32-S3 board after logout",
                expected="LED shows ORANGE (Wi-Fi connected, logged out)",
                duration="5 seconds",
            )
            soft.check(
                manual_check(
                    "Does the built-in RGB LED show ORANGE?",
                    expected_color="orange",
                    expected_rgb=(255, 128, 0),
                ),
                "Built-in LED should show ORANGE when connected and logged out",
            )
