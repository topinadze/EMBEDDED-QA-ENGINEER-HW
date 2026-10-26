from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import allure
import pytest

from config.test_config import resolve_account_credentials
from drivers.device_driver import DeviceDriver
from manual_checks import (
    confirm_destructive_action,
    prepare_manually,
    prepare_observation,
)
from utils.nvs_erase import erase_nvs

pytestmark = [
    allure.parent_suite("DZ17"),
    allure.suite("Authentication Registration Preparation"),
    allure.epic("SENTRY SWM-2"),
    allure.feature("Operator Account and Access Control (AU-1)"),
    pytest.mark.auth,
    pytest.mark.auth_registration,
    pytest.mark.interactive,
    pytest.mark.persistent,
]


@pytest.fixture(scope="module", autouse=True)
def auth_registration_nvs_prepared(
    request: pytest.FixtureRequest,
) -> None:
    """Erase NVS exactly once before this module's registration cases."""
    username, password = resolve_account_credentials(
        user_override=request.config.getoption("--app-user"),
        password_override=request.config.getoption("--app-password"),
    )
    if not username or not password:
        pytest.skip(
            "Configure HW17_USER/HW17_PASSWORD or TEST_USER/TEST_PASSWORD, "
            "or pass --app-user and --app-password before running AU-1 registration."
        )
    if (
        not re.fullmatch(r"[a-zA-Z0-9_]{3,16}", username)
        or username.casefold() == "debug"
    ):
        pytest.fail(
            "The configured registration username must be 3-16 ASCII letters, "
            "digits, or underscores, and must not be 'debug'."
        )
    if not 6 <= len(password) <= 32:
        pytest.fail("The configured registration password must be 6-32 characters.")

    port = request.config.getoption("--port")
    if not port:
        pytest.fail(
            "The NVS-erasing registration pack requires an explicit --port "
            "so the operator can authorize the exact target."
        )
    baudrate = int(request.config.getoption("--baudrate") or 115200)
    expected_version = request.config.getoption("--expected-fw-version")
    if not expected_version:
        pytest.fail(
            "The NVS-erasing registration pack requires --expected-fw-version "
            "for a firmware preflight before erasing."
        )

    preflight_command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "detect_firmware.py"),
        "--port",
        port,
        "--baudrate",
        str(baudrate),
    ]
    with allure.step(f"Verify supported firmware on {port} before NVS erase"):
        try:
            preflight = subprocess.run(
                preflight_command,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                check=False,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired as error:
            output = "\n".join(
                _decode_process_output(value)
                for value in (error.stdout, error.stderr)
                if value
            )
            allure.attach(
                output or "Firmware preflight produced no output.",
                name="Firmware preflight timeout",
                attachment_type=allure.attachment_type.TEXT,
            )
            pytest.fail(
                f"Firmware preflight timed out on {port}; NVS was not erased. "
                f"{output}"
            )

        preflight_output = "\n".join(
            _decode_process_output(part)
            for part in (preflight.stdout, preflight.stderr)
            if part
        )
        allure.attach(
            f"Command: {subprocess.list2cmdline(preflight_command)}\n"
            f"Exit code: {preflight.returncode}\n{preflight_output}",
            name="Firmware preflight",
            attachment_type=allure.attachment_type.TEXT,
        )
        if preflight.returncode != 0:
            pytest.fail(
                f"Firmware preflight failed on {port}; NVS was not erased. "
                f"Output:\n{preflight_output or '<no output>'}"
            )

        detected_versions = re.findall(
            r"^DETECTED_FIRMWARE=(\S+)$",
            preflight.stdout,
            flags=re.MULTILINE,
        )
        if detected_versions != [expected_version]:
            pytest.fail(
                f"Firmware preflight on {port} detected {detected_versions!r}; "
                f"expected exactly {expected_version!r}. NVS was not erased. "
                f"Output:\n{preflight_output or '<no output>'}"
            )

    erase_command = [
        sys.executable,
        "-m",
        "esptool",
        "--port",
        port,
        "--baud",
        str(baudrate),
        "erase-region",
        "0x9000",
        "0x6000",
    ]
    command_text = subprocess.list2cmdline(erase_command)
    consent_phrase = f"ERASE NVS ON {port}"
    with allure.step("Prepare and authorize the one NVS erase for this pack run"):
        prepare_observation(
            prepare_manually,
            action=(
                f"This pack will run `{command_text}` once before its first test on "
                f"{port}. Keep the board powered. It erases all NVS data, including "
                "the saved account, Wi-Fi profile, and settings, and may reset the "
                "board. It does not erase or flash firmware. Negative registration "
                "cases run before the final test creates the configured account."
            ),
            expected=(
                "The operator sees the target and erase scope once. After the "
                "command, esptool reports completion and every test's UART setup "
                "confirms the expected firmware remains installed."
            ),
            duration=(
                "Firmware preflight is complete; keep the board powered during the "
                "single erase (up to 90 seconds) and subsequent reboot."
            ),
        )

        if not confirm_destructive_action(
            f"Authorize this NVS erase on {port}: {command_text}",
            consent_phrase,
        ):
            pytest.skip("Operator declined NVS erase; no erase was performed.")

    with allure.step(f"Erase NVS region on {port}"):
        try:
            result = erase_nvs(port, baudrate)
        except subprocess.TimeoutExpired as error:
            output = "\n".join(
                _decode_process_output(value)
                for value in (error.stdout, error.stderr)
                if value
            )
            allure.attach(
                output or "esptool produced no captured output before timeout.",
                name="NVS erase timeout",
                attachment_type=allure.attachment_type.TEXT,
            )
            pytest.fail(
                f"NVS erase timed out on {port}; erase completion is unknown. "
                "Do not retry until the device state is checked manually."
            )

        erase_output = "\n".join(
            _decode_process_output(part)
            for part in (result.stdout, result.stderr)
            if part
        )
        allure.attach(
            f"Command: {command_text}\nExit code: {result.returncode}\n"
            f"{erase_output or '<no output>'}",
            name="NVS erase result",
            attachment_type=allure.attachment_type.TEXT,
        )
        if result.returncode != 0:
            pytest.fail(
                f"esptool failed to erase NVS on {port}; the region may be "
                "partially erased. Do not retry until the device state is checked. "
                f"Output:\n{erase_output or '<no output>'}"
            )


def _decode_process_output(output: str | bytes) -> str:
    if isinstance(output, bytes):
        output = output.decode(errors="replace")
    return re.sub(
        r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b",
        "[REDACTED MAC]",
        output,
        flags=re.IGNORECASE,
    )


def _reports_explicitly_logged_out(identity: dict[str, object]) -> bool:
    raw_lines = identity["raw"]
    return isinstance(raw_lines, list) and any(
        isinstance(line, str) and "not logged in" in line.casefold()
        for line in raw_lines
    )


def _assert_explicitly_logged_out(
    identity: dict[str, object],
    *,
    context: str,
) -> None:
    raw_lines = identity["raw"]
    assert _reports_explicitly_logged_out(identity), (
        f"{context}: whoami did not explicitly confirm the logged-out state; "
        f"response was {raw_lines!r}."
    )


@pytest.fixture
def _registration_device_with_logged_out_preconditions(
    auth_registration_nvs_prepared: None,
    device_driver: DeviceDriver,
    ensure_wifi_connected: Callable[[DeviceDriver], None],
) -> Iterator[DeviceDriver]:
    """Establish the shared Wi-Fi and logged-out registration preconditions."""
    _ = auth_registration_nvs_prepared
    driver = device_driver
    with allure.step("Establish and verify Wi-Fi and logged-out preconditions"):
        ensure_wifi_connected(driver)
        identity = driver.whoami()
        if (
            identity["logged_in"]
            or not _reports_explicitly_logged_out(identity)
        ):
            driver.logout()
            identity = driver.whoami()
        _assert_explicitly_logged_out(identity, context="Registration setup")
        assert not identity["logged_in"], (
            "Registration checks must start logged out; "
            f"UART whoami reported {identity!r}."
        )
    yield driver


@pytest.fixture
def registration_ready_device(
    _registration_device_with_logged_out_preconditions: DeviceDriver,
) -> Iterator[DeviceDriver]:
    """Keep negative registration cases isolated from session changes."""
    driver = _registration_device_with_logged_out_preconditions
    yield driver

    with allure.step("Restore and verify logged-out state after the case"):
        identity = driver.whoami()
        if (
            identity["logged_in"]
            or not _reports_explicitly_logged_out(identity)
        ):
            driver.logout()
            identity = driver.whoami()
        _assert_explicitly_logged_out(identity, context="Registration teardown")
        assert not identity["logged_in"], (
            "Registration case teardown must leave the device logged out; "
            f"UART whoami reported {identity!r}."
        )


@pytest.fixture
def registered_profile_device(
    _registration_device_with_logged_out_preconditions: DeviceDriver,
    app_credentials: tuple[str, str],
) -> Iterator[DeviceDriver]:
    """Keep the newly registered profile logged in after the final case."""
    driver = _registration_device_with_logged_out_preconditions
    username, _ = app_credentials
    yield driver

    with allure.step("Verify the newly registered profile remains logged in"):
        identity = driver.whoami()
        assert (
            identity["logged_in"]
            and identity["user"] == username
            and identity["access"] == "user"
        ), (
            "The final registration case must leave the configured profile "
            f"logged in at user access; UART whoami reported {identity!r}."
        )


def _assert_registration_rejected(
    output: str,
    *,
    expected_code: str,
    scenario: str,
) -> None:
    assert expected_code in output, (
        f"{scenario}: expected {expected_code}; UART returned:\n"
        f"{output or '<no response>'}"
    )
    assert "[AUTH] profile '" not in output, (
        f"{scenario}: invalid registration unexpectedly created a profile:\n{output}"
    )


@allure.sub_suite("First-Time Profile Registration")
@allure.story("AU-1: Required registration arguments")
@allure.title("Reject registration command with missing arguments ({case}) using E201")
@pytest.mark.negative
@pytest.mark.parametrize(
    ("command", "case"),
    [
        pytest.param("register", "no-arguments", id="no-arguments"),
        pytest.param("register onlyuser", "login-only", id="login-only"),
    ],
)
def test_registration_rejects_missing_arguments(
    registration_ready_device: DeviceDriver,
    command: str,
    case: str,
) -> None:
    with allure.step(f"Send malformed registration command: {case}"):
        output = "\n".join(
            registration_ready_device.send_command(command, timeout=2.0)
        )
        _assert_registration_rejected(
            output,
            expected_code="E201",
            scenario=f"Malformed command {command!r}",
        )


@allure.sub_suite("First-Time Profile Registration")
@allure.story("AU-1: Reserved registration login")
@allure.title("Reject reserved registration login 'debug' with E203")
@pytest.mark.negative
def test_registration_rejects_reserved_debug_login(
    registration_ready_device: DeviceDriver,
) -> None:
    with allure.step("Reject the reserved 'debug' login"):
        output = "\n".join(
            registration_ready_device.register("debug", "ValidPass123", timeout=2.0)
        )
        _assert_registration_rejected(
            output,
            expected_code="E203",
            scenario="Reserved login 'debug'",
        )


@allure.sub_suite("First-Time Profile Registration")
@allure.story("AU-1: Registration login constraints")
@allure.title("Reject invalid registration login ({case}) with E204")
@pytest.mark.negative
@pytest.mark.parametrize(
    ("username", "case"),
    [
        pytest.param("ab", "below-minimum-length", id="below-minimum-length"),
        pytest.param(
            "a" * 17,
            "above-maximum-length",
            id="above-maximum-length",
        ),
        pytest.param("bad@user", "unsupported-character", id="unsupported-character"),
    ],
)
def test_registration_rejects_invalid_login(
    registration_ready_device: DeviceDriver,
    username: str,
    case: str,
) -> None:
    with allure.step(f"Reject invalid login: {case}"):
        output = "\n".join(
            registration_ready_device.register(
                username, "ValidPass123", timeout=2.0
            )
        )
        _assert_registration_rejected(
            output,
            expected_code="E204",
            scenario=f"Invalid login case {case}",
        )


@allure.sub_suite("First-Time Profile Registration")
@allure.story("AU-1: Registration password constraints")
@allure.title("Reject registration password ({case}) with E205")
@pytest.mark.negative
@pytest.mark.parametrize(
    ("password", "case"),
    [
        pytest.param("12345", "below-minimum-length", id="below-minimum-length"),
        pytest.param(
            "P" * 33,
            "above-maximum-length",
            id="above-maximum-length",
        ),
    ],
)
def test_registration_rejects_invalid_password_length(
    registration_ready_device: DeviceDriver,
    password: str,
    case: str,
) -> None:
    with allure.step(f"Reject invalid password length: {case}"):
        output = "\n".join(
            registration_ready_device.register(
                "validUser", password, timeout=2.0
            )
        )
        _assert_registration_rejected(
            output,
            expected_code="E205",
            scenario=f"Invalid password length {case}",
        )


@allure.sub_suite("First-Time Profile Registration")
@allure.story("AU-1: Valid profile registration")
@allure.title("Register the configured profile and verify login with whoami")
@pytest.mark.positive
def test_registration_creates_configured_profile_and_allows_login(
    registered_profile_device: DeviceDriver,
    app_credentials: tuple[str, str],
) -> None:
    username, password = app_credentials
    with allure.step(f"Register configured profile {username!r}"):
        output = "\n".join(
            registered_profile_device.register(username, password, timeout=2.0)
        )
        registered_phrase = f"[AUTH] profile '{username}' registered"
        assert registered_phrase in output, (
            f"Expected registration confirmation {registered_phrase!r}; "
            f"UART returned:\n{output or '<no response>'}"
        )

    with allure.step("Log in and verify the registered profile with whoami"):
        login_output = "\n".join(
            registered_profile_device.login(username, password, timeout=3.0)
        )
        identity = registered_profile_device.whoami()
        assert identity["logged_in"] and identity["user"] == username, (
            f"Expected logged-in user {username!r}; login UART:\n"
            f"{login_output or '<no response>'}\nwhoami: {identity!r}"
        )
