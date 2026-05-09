#!/usr/bin/env python3
"""Inspect USB serial devices and report whether the Blue Pill bridge is visible."""

from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path

import serial.tools.list_ports

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge import BLUEPILL_PID, BLUEPILL_VID


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Blue Pill USB bridge visibility")
    parser.parse_args()

    ports = list(serial.tools.list_ports.comports())
    print(f"Detected {len(ports)} serial device(s).")
    for port in ports:
        print(
            f"- {port.device}: vid={port.vid!s} pid={port.pid!s} "
            f"desc={port.description!r} hwid={port.hwid!r}"
        )

    matches = [port for port in ports if port.vid == BLUEPILL_VID and port.pid == BLUEPILL_PID]
    if platform.system() == "Linux":
        import grp

        group_names = sorted({grp.getgrgid(gid).gr_name for gid in os.getgroups()})
        print(f"Linux groups: {', '.join(group_names)}")
        if "dialout" not in group_names:
            print("Warning: current user is not in the dialout group.")

    if matches:
        print(f"Blue Pill bridge visible on: {', '.join(port.device for port in matches)}")
        return 0

    print(
        "No Blue Pill bridge detected. "
        f"Expected VID:PID {BLUEPILL_VID:04x}:{BLUEPILL_PID:04x}."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())