"""
OSDP Bridge — Serial communication module.

Auto-detects the Blue Pill by USB VID:PID (0483:5740),
parses all MCU events, and provides a thread-safe command interface.
Compatible with eventlet monkey-patching.
"""

import threading
import time
import re
import logging
import serial
import serial.tools.list_ports
from datetime import datetime, timezone

log = logging.getLogger(__name__)

BLUEPILL_VID = 0x0483
BLUEPILL_PID = 0x5740
BAUD = 115200


class OsdpBridge:
    """Thread-safe serial bridge to the OSDP Blue Pill."""

    def __init__(self, on_event=None):
        self.port = None
        self.ser = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self.on_event = on_event
        self.connected = False
        self.tx_count = 0
        self.rx_count = 0

    # ── Auto-detect Blue Pill by VID:PID ──────────────────────
    @staticmethod
    def find_port():
        for p in serial.tools.list_ports.comports():
            if p.vid == BLUEPILL_VID and p.pid == BLUEPILL_PID:
                return p.device
        return None

    # ── Connect / Disconnect ──────────────────────────────────
    def connect(self, port=None, retries=3):
        if self.ser and self.ser.is_open and self.connected:
            return True
        # Clean up any stale state
        self._cleanup()
        port = port or self.find_port()
        if not port:
            log.warning("No Blue Pill port found")
            return False
        for attempt in range(retries):
            try:
                self.ser = serial.Serial(port, BAUD, timeout=0.1)
                self.ser.dtr = True
                self.port = port
                self.connected = True
                self._running = True
                self._thread = threading.Thread(target=self._reader_loop,
                                                daemon=True)
                self._thread.start()
                log.info("Connected to %s (attempt %d)", port, attempt + 1)
                return True
            except Exception as e:
                log.error("Connect attempt %d to %s: %s", attempt + 1, port, e)
                self._cleanup()
                if attempt < retries - 1:
                    time.sleep(1)
        self.connected = False
        return False

    def _cleanup(self):
        """Force-close serial and stop reader thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self.ser:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.connected = False

    def disconnect(self):
        self._cleanup()
        self.port = None
        log.info("Disconnected")

    # ── Send command to MCU ───────────────────────────────────
    def send(self, cmd):
        with self._lock:
            if not self.ser or not self.ser.is_open:
                return False
            try:
                self.ser.write((cmd.strip() + "\n").encode("ascii"))
                self.tx_count += 1
                return True
            except serial.SerialException:
                self.connected = False
                return False

    # ── Convenience commands ──────────────────────────────────
    def ping(self):
        return self.send("PING")

    def status(self):
        return self.send("STATUS")

    def add_reader(self, addr, scbk=None):
        cmd = f"+PD {addr}"
        if scbk:
            cmd += f" {scbk}"
        return self.send(cmd)

    def request_id(self, idx):
        return self.send(f"ID {idx}")

    def request_cap(self, idx):
        return self.send(f"CAP {idx}")

    def request_lstat(self, idx):
        return self.send(f"LSTAT {idx}")

    def request_istat(self, idx):
        return self.send(f"ISTAT {idx}")

    def request_ostat(self, idx):
        return self.send(f"OSTAT {idx}")

    def secure_channel(self, idx):
        return self.send(f"SC {idx}")

    def comset(self, idx, addr, baud):
        return self.send(f"COMSET {idx} {addr} {baud}")

    def keyset(self, idx, key_hex):
        return self.send(f"KEYSET {idx} {key_hex}")

    def led(self, idx, params):
        return self.send(f"LED {idx} {params}")

    def buzzer(self, idx, tone, on, off, count):
        return self.send(f"BUZ {idx} {tone} {on} {off} {count}")

    def output(self, idx, output_num, code, timer):
        return self.send(f"OUT {idx} {output_num} {code} {timer}")

    def relay(self, idx, value):
        return self.send(f"RELAY {idx} {value}")

    def sensor_query(self):
        return self.send("SENSOR?")

    def debug_mode(self, on=True):
        return self.send(f"DEBUG {1 if on else 0}")

    # ── High-level feedback commands ──────────────────────────
    def grant_feedback(self, reader_idx):
        """Green LED solid 2 s + single short beep → access granted.
        LED params: reader=0 led=0 tmpCtrl=2(set) tmpOn=20(2s)
                    tmpOff=0 tmpOnCol=2(green) tmpOffCol=0(black)
                    tmpTimer=20(2s) permCtrl=0 rest=0
        BUZ: tone=2(default) on=2(200ms) off=0 count=1
        """
        self.led(reader_idx,
                 "0 0 2 20 0 2 0 20 0 0 0 0 0")
        self.buzzer(reader_idx, 2, 2, 0, 1)

    def deny_feedback(self, reader_idx):
        """Red LED flash + warning triple-beep → access denied.
        LED params: reader=0 led=0 tmpCtrl=2(flash) tmpOn=3(300ms)
                    tmpOff=3(300ms) tmpOnCol=1(red) tmpOffCol=0(black)
                    tmpTimer=20(2s) permCtrl=0 rest=0
        BUZ: tone=2 on=2(200ms) off=2(200ms) count=3
        """
        self.led(reader_idx,
                 "0 0 2 3 3 1 0 20 0 0 0 0 0")
        self.buzzer(reader_idx, 2, 2, 2, 3)

    # ── Background reader thread ──────────────────────────────
    def _reader_loop(self):
        buf = ""
        while self._running:
            try:
                if not self.ser or not self.ser.is_open:
                    time.sleep(0.5)
                    continue
                data = self.ser.read(256)
                if not data:
                    continue
                buf += data.decode("ascii", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip("\r \t")
                    if not line:
                        continue
                    self.rx_count += 1
                    ev = self._parse_line(line)
                    if ev and self.on_event:
                        try:
                            self.on_event(ev)
                        except Exception as e:
                            log.error("Event handler error: %s", e)
            except serial.SerialException:
                log.warning("Serial disconnected in reader loop")
                self.connected = False
                if self.ser:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None
                # Auto-reconnect with backoff
                backoff = 2
                while self._running:
                    time.sleep(backoff)
                    port = self.find_port()
                    if port:
                        try:
                            self.ser = serial.Serial(port, BAUD, timeout=0.1)
                            self.ser.dtr = True
                            self.port = port
                            self.connected = True
                            buf = ""
                            log.info("Auto-reconnected to %s", port)
                            if self.on_event:
                                try:
                                    self.on_event({
                                        "type": "reconnected",
                                        "port": port,
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "raw": f"Auto-reconnected to {port}",
                                    })
                                except Exception:
                                    pass
                            break
                        except Exception as e:
                            log.debug("Reconnect attempt failed: %s", e)
                    if backoff < 10:
                        backoff = min(backoff + 2, 10)
            except Exception as e:
                log.error("Reader loop error: %s", e)
                time.sleep(0.1)

    # ── Parse one line from the MCU ───────────────────────────
    @staticmethod
    def _parse_line(line):
        ts = datetime.now(timezone.utc).isoformat()

        m = re.match(r"!CARD (\d+) ([0-9A-Fa-f]+) (\d+) (\d+)", line)
        if m:
            return {"type": "card", "reader": int(m.group(1)),
                    "hex": m.group(2), "bits": int(m.group(3)),
                    "format": int(m.group(4)), "ts": ts, "raw": line}

        m = re.match(r"!KEYPAD (\d+) ([0-9A-Fa-f]+)", line)
        if m:
            return {"type": "keypad", "reader": int(m.group(1)),
                    "hex": m.group(2), "ts": ts, "raw": line}

        m = re.match(r"!STATE (\d+) (\S+)", line)
        if m:
            return {"type": "state", "reader": int(m.group(1)),
                    "state": m.group(2), "ts": ts, "raw": line}

        m = re.match(r"!PDID (\d+) (\S+) (\d+) (\S+) (\S+)", line)
        if m:
            return {"type": "pdid", "reader": int(m.group(1)),
                    "vendor": m.group(2), "model": int(m.group(3)),
                    "serial": m.group(4), "firmware": m.group(5),
                    "ts": ts, "raw": line}

        m = re.match(r"!PDCAP (\d+)(.*)", line)
        if m:
            caps = re.findall(r"(\d+):(\d+):(\d+)", m.group(2))
            return {"type": "pdcap", "reader": int(m.group(1)),
                    "caps": [{"fc": int(c[0]), "compliance": int(c[1]),
                              "num": int(c[2])} for c in caps],
                    "ts": ts, "raw": line}

        m = re.match(r"!LSTAT (\d+) (\d+) (\d+)", line)
        if m:
            return {"type": "lstat", "reader": int(m.group(1)),
                    "tamper": int(m.group(2)), "power": int(m.group(3)),
                    "ts": ts, "raw": line}

        m = re.match(r"!ISTAT (\d+) (\S+)", line)
        if m:
            return {"type": "istat", "reader": int(m.group(1)),
                    "hex": m.group(2), "ts": ts, "raw": line}

        m = re.match(r"!OSTAT (\d+) (\S+)", line)
        if m:
            return {"type": "ostat", "reader": int(m.group(1)),
                    "hex": m.group(2), "ts": ts, "raw": line}

        m = re.match(r"!NAK (\d+) (\d+)", line)
        if m:
            return {"type": "nak", "reader": int(m.group(1)),
                    "code": int(m.group(2)), "ts": ts, "raw": line}

        m = re.match(r"!SENSOR (0x[0-9A-Fa-f]+|\d+)", line)
        if m:
            return {"type": "sensor", "mask": m.group(1), "ts": ts,
                    "raw": line}

        m = re.match(r"!DOOR (\d+) (\d+)", line)
        if m:
            return {"type": "door", "sensor": int(m.group(1)),
                    "closed": int(m.group(2)), "ts": ts, "raw": line}

        m = re.match(r"!BUSY (\d+)", line)
        if m:
            return {"type": "busy", "reader": int(m.group(1)),
                    "ts": ts, "raw": line}

        m = re.match(r"!COM (\d+) (\d+) (\d+)", line)
        if m:
            return {"type": "com", "reader": int(m.group(1)),
                    "addr": int(m.group(2)), "baud": int(m.group(3)),
                    "ts": ts, "raw": line}

        m = re.match(
            r"!STATUS readers=(\d+) tx=(\d+) rx=(\d+) uptime=(\d+)", line)
        if m:
            return {"type": "status", "readers": int(m.group(1)),
                    "tx": int(m.group(2)), "rx": int(m.group(3)),
                    "uptime": int(m.group(4)), "ts": ts, "raw": line}

        m = re.match(
            r"!PD (\d+) addr=(\d+) state=(\S+) sc=(\d+) "
            r"tamper=(\d+) power=(\d+)", line)
        if m:
            return {"type": "pd_status", "index": int(m.group(1)),
                    "addr": int(m.group(2)), "state": m.group(3),
                    "sc": int(m.group(4)), "tamper": int(m.group(5)),
                    "power": int(m.group(6)), "ts": ts, "raw": line}

        m = re.match(r"!RELAY (\d+) (\d+)", line)
        if m:
            return {"type": "relay", "index": int(m.group(1)),
                    "state": int(m.group(2)), "ts": ts, "raw": line}

        m = re.match(r"!BOOT (.+)", line)
        if m:
            return {"type": "boot", "version": m.group(1), "ts": ts,
                    "raw": line}

        m = re.match(r"!CONFIG (.+)", line)
        if m:
            return {"type": "config", "info": m.group(1), "ts": ts,
                    "raw": line}

        m = re.match(r"!DBG (\d+) (.+)", line)
        if m:
            return {"type": "debug", "reader": int(m.group(1)),
                    "message": m.group(2), "ts": ts, "raw": line}

        m = re.match(
            r"!HEARTBEAT tx=(\d+) rx=(\d+) uptime=(\d+)", line)
        if m:
            return {"type": "heartbeat",
                    "tx": int(m.group(1)), "rx": int(m.group(2)),
                    "uptime": int(m.group(3)), "ts": ts, "raw": line}

        if line == "PONG":
            return {"type": "pong", "ts": ts, "raw": line}

        if line.startswith("OK"):
            return {"type": "ok", "detail": line, "ts": ts, "raw": line}

        if line.startswith("ERR:"):
            return {"type": "error", "message": line[4:], "ts": ts,
                    "raw": line}

        return {"type": "unknown", "ts": ts, "raw": line}
