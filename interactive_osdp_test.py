#!/usr/bin/env python3
"""Interactive OSDP hardware verification assistant.

Guides an operator through the OSDP bridge, secure channel, buzzer, and
card-enrollment flows using the existing Flask API.

Usage:
    python interactive_osdp_test.py --base http://localhost:5000 --reader 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import requests


class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


RESULTS = []


def print_header(title: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.CYAN}=== {title} ==={Colors.RESET}")


def print_step(message: str) -> None:
    print(f"{Colors.CYAN}-> {message}{Colors.RESET}")


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    color = {
        "PASS": Colors.GREEN,
        "FAIL": Colors.RED,
        "SKIP": Colors.YELLOW,
    }.get(status, Colors.CYAN)
    suffix = f" -- {detail}" if detail else ""
    print(f"  {color}{status:<4}{Colors.RESET} {name}{suffix}")


def prompt(text: str, default: str | None = None) -> str:
    if default:
        raw = input(f"{text} [{default}]: ").strip()
        return raw or default
    return input(f"{text}: ").strip()


def prompt_yes_no(text: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{text} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


def wait_for_enter(text: str) -> None:
    input(f"{text} Press Enter to continue...")


def api_request(base: str, method: str, path: str, body: dict | None = None) -> tuple[bool, object]:
    url = f"{base}{path}"
    try:
        if method == "GET":
            response = requests.get(url, timeout=10)
        else:
            response = requests.post(url, json=body or {}, timeout=10)
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"

    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = response.text[:200]
        return False, f"HTTP {response.status_code}: {payload}"

    try:
        return True, response.json()
    except json.JSONDecodeError:
        return False, "response was not JSON"


def expect_ok(base: str, name: str, path: str, body: dict | None = None) -> bool:
    ok, payload = api_request(base, "POST", path, body)
    if not ok:
        record("FAIL", name, str(payload))
        return False
    if not isinstance(payload, dict) or not payload.get("ok"):
        record("FAIL", name, f"unexpected payload: {payload}")
        return False
    record("PASS", name)
    return True


def get_json(base: str, name: str, path: str) -> dict | list | None:
    ok, payload = api_request(base, "GET", path)
    if not ok:
        record("FAIL", name, str(payload))
        return None
    record("PASS", name)
    return payload


def poll_for(predicate, timeout_sec: int = 20, interval_sec: float = 1.0):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval_sec)
    return None


def ensure_server(base: str) -> bool:
    print_header("Server Reachability")
    payload = get_json(base, "bridge/status", "/api/bridge/status")
    if payload is None:
        print("\nStart the Flask app first, then rerun this script.")
        return False
    detected = payload.get("detected_port") if isinstance(payload, dict) else None
    print_step(f"Detected Blue Pill port: {detected or 'none'}")
    return True


def ensure_connected(base: str) -> bool:
    print_header("Bridge Connection")
    payload = get_json(base, "bridge/status (pre-check)", "/api/bridge/status")
    if not isinstance(payload, dict):
        return False

    if payload.get("connected"):
        print_step(f"Bridge already connected on {payload.get('port')}")
        return True

    print_step("Connect the Blue Pill and reader before continuing.")
    wait_for_enter("When the hardware is powered and connected,")
    if not expect_ok(base, "bridge/connect", "/api/bridge/connect", {}):
        return False

    payload = get_json(base, "bridge/status (after connect)", "/api/bridge/status")
    if not isinstance(payload, dict) or not payload.get("connected"):
        record("FAIL", "bridge connected state", f"status payload: {payload}")
        return False
    record("PASS", "bridge connected state", str(payload.get("port")))
    return True


def test_reader_commands(base: str, reader: int) -> None:
    print_header("Reader API Commands")
    expect_ok(base, "cmd/ping", "/api/cmd/ping")
    expect_ok(base, "cmd/status", "/api/cmd/status")
    for command in ("id", "cap", "lstat", "istat", "ostat"):
        expect_ok(base, f"cmd/{command}", f"/api/cmd/{command}", {"index": reader})
        time.sleep(0.3)


def test_secure_channel(base: str, reader: int) -> None:
    print_header("Secure Channel / SCBK")
    print_step("Reader and controller must already share the same SCBK for SC to come up.")
    if not prompt_yes_no("Run secure channel handshake now?", True):
        record("SKIP", "cmd/sc")
        return

    if not expect_ok(base, "cmd/sc", "/api/cmd/sc", {"index": reader}):
        return

    time.sleep(2)
    readers = get_json(base, "readers/list", "/api/readers")
    sc_state = None
    if isinstance(readers, list):
        for entry in readers:
            if entry.get("index") == reader:
                sc_state = entry.get("sc")
                break

    if sc_state is True:
        record("PASS", "secure channel state", f"reader {reader} reports sc=true")
    else:
        detail = f"reader {reader} did not report sc=true"
        if prompt_yes_no("Did the reader stay online and complete secure channel successfully?", False):
            record("PASS", "secure channel operator confirmation", detail)
        else:
            record("FAIL", "secure channel operator confirmation", detail)

    if prompt_yes_no("Do you want to send KEYSET to test SCBK programming? This changes device state.", False):
        key_hex = prompt("Enter 32 hex chars for the new SCBK")
        if len(key_hex) != 32:
            record("FAIL", "cmd/keyset", "SCBK must be exactly 32 hex characters")
        elif not prompt_yes_no("Confirm you want to program this SCBK now?", False):
            record("SKIP", "cmd/keyset")
        else:
            expect_ok(base, "cmd/keyset", "/api/cmd/keyset", {"index": reader, "key": key_hex.upper()})


def test_buzzer(base: str, reader: int) -> None:
    print_header("Buzzer / Beep")
    print_step("This sends a single short buzzer tone to the reader.")
    if not expect_ok(
        base,
        "cmd/buzzer",
        "/api/cmd/buzzer",
        {"index": reader, "tone": 2, "on": 3, "off": 2, "count": 1},
    ):
        return
    if prompt_yes_no("Did you hear a single beep from the reader?", True):
        record("PASS", "buzzer audible confirmation")
    else:
        record("FAIL", "buzzer audible confirmation")


def create_test_user(base: str, reader: int) -> str | None:
    stamp = datetime.now().strftime("%H%M%S")
    username = prompt("Username for the temporary test user", f"osdp-test-{stamp}")
    body = {
        "username": username,
        "full_name": "Interactive OSDP Test User",
        "role": "user",
        "allowed_readers": [reader],
        "schedule": "24/7",
    }
    ok, payload = api_request(base, "POST", "/api/users", body)
    if not ok:
        record("FAIL", "users/create", str(payload))
        return None
    if not isinstance(payload, dict) or not payload.get("ok") or not payload.get("id"):
        record("FAIL", "users/create", f"unexpected payload: {payload}")
        return None
    user_id = payload["id"]
    record("PASS", "users/create", username)
    return user_id


def list_user_credentials(base: str, user_id: str) -> list:
    payload = get_json(base, f"credentials/list for {user_id}", f"/api/credentials?user_id={user_id}")
    return payload if isinstance(payload, list) else []


def test_card_enrollment(base: str, reader: int) -> None:
    print_header("Card Enrollment")
    if not prompt_yes_no("Do you have a card ready to enroll on this reader?", True):
        record("SKIP", "card enrollment")
        return

    user_id = create_test_user(base, reader)
    if not user_id:
        return

    before = list_user_credentials(base, user_id)
    before_count = len(before)

    if not expect_ok(base, "enroll/start card", "/api/enroll/start", {"user_id": user_id, "mode": "card"}):
        return

    print_step("Present the card to the reader now. Wait for the reader response, then return here.")
    wait_for_enter("After swiping the card,")

    def credential_added():
        creds = list_user_credentials(base, user_id)
        if len(creds) > before_count:
            return creds[0]
        return None

    credential = poll_for(credential_added, timeout_sec=20, interval_sec=1)
    if not credential:
        record("FAIL", "card enrollment capture", "no new credential appeared within 20s")
        expect_ok(base, "enroll/cancel", "/api/enroll/cancel")
        return

    record("PASS", "card enrollment capture", credential.get("card_hex", "unknown card"))
    if prompt_yes_no("Did the reader give enrollment success feedback (green/beep)?", True):
        record("PASS", "enrollment feedback confirmation")
    else:
        record("FAIL", "enrollment feedback confirmation")

    logs_before = get_json(base, "access_log before access test", "/api/access_log")
    before_log_count = len(logs_before) if isinstance(logs_before, list) else 0

    print_header("Card Access Verification")
    print_step("Present the same enrolled card again. The relay and grant feedback should trigger.")
    wait_for_enter("After swiping the enrolled card again,")

    def granted_access():
        logs = get_json(base, "access_log poll", "/api/access_log")
        if not isinstance(logs, list):
            return None
        for entry in logs[: max(before_log_count + 5, 10)]:
            if entry.get("user_id") == user_id and entry.get("granted") is True:
                return entry
        return None

    access_entry = poll_for(granted_access, timeout_sec=20, interval_sec=1)
    if access_entry:
        record("PASS", "card access log", access_entry.get("reason", "granted"))
    else:
        record("FAIL", "card access log", "no granted access entry found within 20s")

    if prompt_yes_no("Did you hear the grant beep / see green LED / hear relay action?", True):
        record("PASS", "card grant hardware confirmation")
    else:
        record("FAIL", "card grant hardware confirmation")

    if prompt_yes_no("Deactivate the temporary test user now?", True):
        expect_ok(base, "users/delete (deactivate)", f"/api/users/{user_id}")
    else:
        record("SKIP", "users/delete (deactivate)")


def print_summary() -> int:
    print_header("Summary")
    passed = sum(1 for status, _, _ in RESULTS if status == "PASS")
    failed = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    skipped = sum(1 for status, _, _ in RESULTS if status == "SKIP")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive OSDP hardware verification")
    parser.add_argument("--base", default="http://localhost:5000", help="Flask base URL")
    parser.add_argument("--reader", type=int, default=0, help="Reader index to test")
    args = parser.parse_args()

    print_header("Interactive OSDP Verification")
    print("This assistant will call the panel API and tell you when to interact with the hardware.")

    if not ensure_server(args.base):
        return 1
    if not ensure_connected(args.base):
        return 1

    test_reader_commands(args.base, args.reader)
    test_secure_channel(args.base, args.reader)
    test_buzzer(args.base, args.reader)
    test_card_enrollment(args.base, args.reader)
    return print_summary()


if __name__ == "__main__":
    sys.exit(main())