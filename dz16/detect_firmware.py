from __future__ import annotations

import argparse
import re
import sys

from drivers.device_driver import DeviceDriver


SUPPORTED_VERSIONS = {"1.3.0", "1.4.0", "1.5.0"}
VERSION_PATTERN = re.compile(r"\bFW:\s*v?(\d+\.\d+\.\d+)", re.IGNORECASE)


def parse_firmware_version(lines: list[str]) -> str:
    for line in lines:
        match = VERSION_PATTERN.search(line)
        if match is not None:
            version = match.group(1)
            if version not in SUPPORTED_VERSIONS:
                raise ValueError(
                    f"Unsupported firmware version {version}; expected one of "
                    f"{', '.join(sorted(SUPPORTED_VERSIONS))}."
                )
            return version
    raise ValueError(f"Could not parse firmware version from UART response: {lines!r}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the running firmware version over the device UART."
    )
    parser.add_argument("--port", required=True, help="UART port, for example COM4.")
    parser.add_argument("--baudrate", type=int, default=115200)
    args = parser.parse_args()

    driver = DeviceDriver(args.port, baudrate=args.baudrate)
    try:
        driver.open()
        lines = driver.send_command("version", timeout=2.0)
        try:
            version = parse_firmware_version(lines)
        except ValueError as error:
            print(
                str(error),
                file=sys.stderr,
            )
            return 1

        print(f"DETECTED_FIRMWARE={version}")
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
