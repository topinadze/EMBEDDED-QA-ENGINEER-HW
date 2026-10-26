from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def erase_nvs(port: str, baudrate: int) -> subprocess.CompletedProcess[str]:
    command = [
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
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
    )
