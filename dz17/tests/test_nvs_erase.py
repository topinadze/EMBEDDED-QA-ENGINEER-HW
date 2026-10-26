from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import utils.nvs_erase as nvs_erase


def test_erase_nvs_invokes_esptool_for_only_the_nvs_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    expected_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Erase completed.", stderr=""
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return expected_result

    monkeypatch.setattr(nvs_erase.subprocess, "run", run)

    result = nvs_erase.erase_nvs("COM4", 115200)

    assert result is expected_result
    assert calls == [
        (
            [
                sys.executable,
                "-m",
                "esptool",
                "--port",
                "COM4",
                "--baud",
                "115200",
                "erase-region",
                "0x9000",
                "0x6000",
            ],
            {
                "cwd": Path(nvs_erase.__file__).resolve().parents[1],
                "capture_output": True,
                "check": False,
                "text": True,
                "timeout": 90,
            },
        )
    ]
