"""
OSDP Bridge Firmware Flasher
Uploads firmware to the STM32 Blue Pill via the USB CDC bootloader.

Usage (standalone):
    python flasher.py firmware.bin [--port COMx]

Usage (from code):
    from flasher import flash_firmware
    flash_firmware("firmware.bin", progress_cb=lambda pct, msg: print(f"{pct}% {msg}"))
"""

import os
import sys
import time
import struct
import logging
import binascii
import serial
import serial.tools.list_ports

log = logging.getLogger(__name__)

# Must match bootloader defines
APP_ADDR     = 0x08007000
APP_MAX_SIZE = 0x19000       # 100KB
CHUNK_SIZE   = 32            # bytes per W command (keep small for USB CDC buffer)
BL_VID       = 0x0483
BL_PID       = 0x5741       # bootloader PID
APP_PID      = 0x5740       # application PID


def crc32(data: bytes) -> int:
    """CRC-32 matching the bootloader's implementation (same as zlib)."""
    return binascii.crc32(data) & 0xFFFFFFFF


def find_port(pid: int) -> str | None:
    """Find the COM port for a given USB PID (VID is always 0x0483)."""
    for p in serial.tools.list_ports.comports():
        if p.vid == BL_VID and p.pid == pid:
            return p.device
    return None


def wait_for_port(pid: int, timeout: float = 20.0) -> str | None:
    """Wait for a USB serial device with the given PID to appear."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        port = find_port(pid)
        if port:
            # Let Windows finish driver init before we open the port
            time.sleep(0.5)
            # Verify it's still there (sometimes the port flickers)
            if find_port(pid):
                return port
        time.sleep(0.3)
    return None


def _send_cmd(ser: serial.Serial, cmd: str, timeout: float = 30.0) -> str:
    """Send a command and return the response line."""
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode("ascii"))
    ser.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = ser.readline().decode("ascii", errors="replace").strip()
        if line:
            return line
    raise TimeoutError(f"No response to: {cmd[:40]}...")


def flash_firmware(
    bin_path: str,
    port: str | None = None,
    reboot_from_app: bool = True,
    progress_cb=None,
):
    """
    Flash a firmware .bin file to the OSDP Bridge via the bootloader.

    Args:
        bin_path: Path to the .bin firmware file.
        port: COM port of the bootloader (auto-detected if None).
        reboot_from_app: If True, send BOOTLOADER command to the app first.
        progress_cb: Optional callback(percent: int, message: str).

    Raises:
        FileNotFoundError, ValueError, TimeoutError, serial.SerialException
    """
    if not os.path.isfile(bin_path):
        raise FileNotFoundError(f"Firmware file not found: {bin_path}")

    fw_data = open(bin_path, "rb").read()
    if len(fw_data) > APP_MAX_SIZE:
        raise ValueError(
            f"Firmware too large: {len(fw_data)} bytes (max {APP_MAX_SIZE})"
        )

    def progress(pct, msg):
        log.info("[%3d%%] %s", pct, msg)
        if progress_cb:
            progress_cb(pct, msg)

    # Step 1: Enter bootloader mode
    bl_port = find_port(BL_PID)
    if bl_port:
        progress(0, f"Bootloader already active on {bl_port}")
    elif reboot_from_app:
        app_port = port or find_port(APP_PID)
        if not app_port:
            raise RuntimeError(
                "OSDP Bridge not found. Connect the Blue Pill via USB."
            )
        progress(0, f"Sending BOOTLOADER command to {app_port}")
        try:
            with serial.Serial(app_port, 115200, timeout=2) as ser:
                ser.write(b"BOOTLOADER\n")
                ser.flush()
                time.sleep(0.5)
        except serial.SerialException:
            pass  # port may vanish as MCU resets — that's OK
        progress(2, "Waiting for bootloader to appear...")
        bl_port = wait_for_port(BL_PID, timeout=20)
        if not bl_port:
            raise TimeoutError("Bootloader did not appear after reboot")
    else:
        # Bootloader should already be running (e.g. app.py sent the command)
        progress(2, "Waiting for bootloader to appear...")
        bl_port = wait_for_port(BL_PID, timeout=20)
        if not bl_port:
            raise TimeoutError(
                "Bootloader not found. Is the Blue Pill connected via USB?"
            )

    progress(5, f"Connecting to bootloader on {bl_port}")

    # Retry opening the port — Windows may still be finishing driver setup
    ser = None
    for attempt in range(5):
        try:
            ser = serial.Serial(bl_port, 115200, timeout=5)
            break
        except serial.SerialException:
            if attempt == 4:
                raise
            time.sleep(1)

    with ser:
        time.sleep(0.2)
        ser.reset_input_buffer()

        # Handshake
        resp = _send_cmd(ser, "HELLO")
        if "BOOTLOADER" not in resp:
            raise RuntimeError(f"Unexpected bootloader response: {resp}")
        progress(8, f"Bootloader identified: {resp}")

        # Erase
        progress(10, "Erasing application flash...")
        resp = _send_cmd(ser, "ERASE", timeout=30)
        if resp != "OK":
            raise RuntimeError(f"Erase failed: {resp}")
        progress(20, "Flash erased")

        # Write chunks
        total_chunks = (len(fw_data) + CHUNK_SIZE - 1) // CHUNK_SIZE
        for i in range(total_chunks):
            offset = i * CHUNK_SIZE
            chunk = fw_data[offset : offset + CHUNK_SIZE]
            offset_hex = f"{offset:05X}"
            data_hex = chunk.hex().upper()
            cmd = f"W{offset_hex} {data_hex}"
            resp = _send_cmd(ser, cmd, timeout=5)
            if resp != "OK":
                raise RuntimeError(
                    f"Write failed at offset 0x{offset_hex}: {resp}"
                )
            pct = 20 + int(70 * (i + 1) / total_chunks)
            if (i + 1) % 16 == 0 or i == total_chunks - 1:
                progress(pct, f"Written {offset + len(chunk)}/{len(fw_data)} bytes")

        # Verify CRC
        fw_crc = crc32(fw_data)
        progress(92, f"Verifying CRC-32 (0x{fw_crc:08X})...")
        resp = _send_cmd(ser, f"CRC {len(fw_data):X} {fw_crc:08X}", timeout=10)
        if resp != "OK":
            raise RuntimeError(f"CRC verification failed: {resp}")
        progress(96, "CRC verified")

        # Boot
        progress(98, "Booting application...")
        resp = _send_cmd(ser, "BOOT", timeout=5)
        if not resp.startswith("OK"):
            raise RuntimeError(f"Boot failed: {resp}")

    progress(100, "Firmware update complete!")
    return True


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="OSDP Bridge Firmware Flasher")
    parser.add_argument("firmware", help="Path to firmware .bin file")
    parser.add_argument("--port", help="COM port (auto-detect if omitted)")
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        help="Don't try to reboot from app; assume bootloader is already running",
    )
    args = parser.parse_args()

    def cli_progress(pct, msg):
        bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
        print(f"\r[{bar}] {pct:3d}%  {msg:<50}", end="", flush=True)
        if pct == 100:
            print()

    try:
        flash_firmware(
            args.firmware,
            port=args.port,
            reboot_from_app=not args.no_reboot,
            progress_cb=cli_progress,
        )
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
