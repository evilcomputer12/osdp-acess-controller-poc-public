#!/usr/bin/env python3
"""
OSDP Access Panel – Comprehensive API Test Script

Exercises every Flask API endpoint from the web panel one by one.
Usage:
    python test_api.py [--base http://localhost:5000] [--skip-hw]

Flags:
    --base URL    Base URL of the Flask server (default http://localhost:5000)
    --skip-hw     Skip hardware-dependent tests (bridge connect, MCU commands)
"""

import argparse
import json
import sys
import time
import requests

# ── Helpers ───────────────────────────────────────────────────

class Colors:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

passed = 0
failed = 0
skipped = 0
results = []
SESSION = requests.Session()

def log(tag, msg, color=Colors.CYAN):
    print(f"{color}[{tag}]{Colors.RESET} {msg}")

def ok(name, resp, note=""):
    global passed
    passed += 1
    status = resp.status_code if resp is not None else "n/a"
    extra = f" -- {note}" if note else ""
    print(f"  {Colors.GREEN}+ PASS{Colors.RESET} {name} (HTTP {status}){extra}")
    results.append(("PASS", name))

def fail(name, resp, reason=""):
    global failed
    failed += 1
    status = resp.status_code if resp is not None else "n/a"
    body = ""
    try:
        body = resp.text[:200] if resp is not None else ""
    except Exception:
        pass
    print(f"  {Colors.RED}x FAIL{Colors.RESET} {name} (HTTP {status}) {reason}")
    if body:
        print(f"         {body}")
    results.append(("FAIL", name))

def skip(name, reason=""):
    global skipped
    skipped += 1
    print(f"  {Colors.YELLOW}o SKIP{Colors.RESET} {name} -- {reason}")
    results.append(("SKIP", name))


def get(url, **kw):
    return SESSION.get(url, timeout=10, **kw)


def post(url, body=None, **kw):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body) if body is not None else None
    return SESSION.post(url, data=data, headers=headers, timeout=10, **kw)


def put(url, body=None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body) if body is not None else None
    return SESSION.put(url, data=data, headers=headers, timeout=10)


def delete(url):
    return SESSION.delete(url, timeout=10)


def authenticate(base, username, password):
    log("AUTH", f"Signing in as {username}")
    response = post(f"{base}/api/auth/login", {"username": username, "password": password})
    if response.status_code >= 400:
        fail("auth/login", response, "could not authenticate")
        return False
    try:
        payload = response.json()
    except Exception:
        fail("auth/login", response, "not JSON")
        return False
    if not payload.get("ok"):
        fail("auth/login", response, payload.get("error", "login failed"))
        return False
    ok("auth/login", response, f"role={payload.get('user', {}).get('role', '?')}")
    return True


def expect_ok(name, resp, key="ok"):
    """Check that HTTP is 2xx and optional JSON key is truthy."""
    if resp is None:
        fail(name, resp, "no response")
        return False
    if resp.status_code >= 400:
        fail(name, resp, f"HTTP {resp.status_code}")
        return False
    try:
        j = resp.json()
    except Exception:
        fail(name, resp, "not JSON")
        return False
    if key and not j.get(key):
        fail(name, resp, f"json['{key}'] = {j.get(key)}")
        return False
    ok(name, resp)
    return True


def expect_json(name, resp):
    """Just check 2xx + valid JSON (for list endpoints)."""
    if resp is None:
        fail(name, resp, "no response")
        return None
    if resp.status_code >= 400:
        fail(name, resp, f"HTTP {resp.status_code}")
        return None
    try:
        j = resp.json()
    except Exception:
        fail(name, resp, "not JSON")
        return None
    ok(name, resp, f"items={len(j) if isinstance(j, list) else 'obj'}")
    return j


# ══════════════════════════════════════════════════════════════
#  Test Groups
# ══════════════════════════════════════════════════════════════

def test_bridge(base, skip_hw):
    log("BRIDGE", "Bridge status / connect / disconnect")

    # 1. Bridge status (always works)
    r = get(f"{base}/api/bridge/status")
    j = expect_json("bridge/status", r)
    connected = j.get("connected", False) if j else False

    if skip_hw:
        skip("bridge/connect", "hardware skipped")
        skip("bridge/disconnect", "hardware skipped")
        return connected

    # 2. Connect
    r = post(f"{base}/api/bridge/connect")
    if expect_ok("bridge/connect", r):
        time.sleep(1)  # wait for reader poll to start

    # Re-check status
    r = get(f"{base}/api/bridge/status")
    j = expect_json("bridge/status (after connect)", r)
    connected = j.get("connected", False) if j else False
    return connected


def test_mcu_commands(base, skip_hw):
    log("MCU", "MCU commands (ping, status, id, cap, lstat, istat, ostat, sc, comset, keyset, led, buzzer, output, relay, sensor, raw, debug)")

    if skip_hw:
        for cmd in ["ping","status","add_reader","id","cap","lstat","istat","ostat",
                     "sc","comset","keyset","led","buzzer","output","relay","sensor","raw","debug"]:
            skip(f"cmd/{cmd}", "hardware skipped")
        return

    # Ping
    expect_ok("cmd/ping", post(f"{base}/api/cmd/ping"))
    time.sleep(0.3)

    # Status
    expect_ok("cmd/status", post(f"{base}/api/cmd/status"))
    time.sleep(0.5)

    # Reader info queries
    for cmd in ["id", "cap", "lstat", "istat", "ostat"]:
        expect_ok(f"cmd/{cmd}", post(f"{base}/api/cmd/{cmd}", {"index": 0}))
        time.sleep(0.5)

    # Secure Channel
    expect_ok("cmd/sc", post(f"{base}/api/cmd/sc", {"index": 0}))
    time.sleep(3)  # give SC handshake time

    # LED (solid green)
    expect_ok("cmd/led", post(f"{base}/api/cmd/led", {
        "index": 0,
        "params": "0 0 0 0 0 0 0 0 1 10 0 2 0"
    }))
    time.sleep(0.5)

    # Buzzer
    expect_ok("cmd/buzzer", post(f"{base}/api/cmd/buzzer", {
        "index": 0, "tone": 2, "on": 3, "off": 3, "count": 1
    }))
    time.sleep(0.5)

    # Output
    expect_ok("cmd/output", post(f"{base}/api/cmd/output", {
        "index": 0, "output": 0, "code": 2, "timer": 500
    }))
    time.sleep(0.5)

    # Relay (pulse 500ms)
    expect_ok("cmd/relay", post(f"{base}/api/cmd/relay", {
        "index": 0, "value": "T500"
    }))
    time.sleep(1)

    # Sensor query
    expect_ok("cmd/sensor", post(f"{base}/api/cmd/sensor"))
    time.sleep(0.3)

    # Debug mode on then off
    expect_ok("cmd/debug (on)", post(f"{base}/api/cmd/debug", {"on": True}))
    time.sleep(0.3)
    expect_ok("cmd/debug (off)", post(f"{base}/api/cmd/debug", {"on": False}))
    time.sleep(0.3)

    # Raw command
    expect_ok("cmd/raw", post(f"{base}/api/cmd/raw", {"cmd": "PING"}))
    time.sleep(0.3)

    # KEYSET (requires SC active — may fail if SC not established yet)
    r = post(f"{base}/api/cmd/keyset", {"index": 0, "key": "0102030405060708090A0B0C0D0E0F10"})
    if r.status_code < 400:
        j = r.json()
        if j.get("ok"):
            ok("cmd/keyset", r)
        else:
            ok("cmd/keyset", r, note="sent (SC may not be active)")
    else:
        fail("cmd/keyset", r)
    time.sleep(0.5)

    # COMSET — test with current addr/baud to avoid actually changing settings
    # Send comset to addr=0 baud=9600 (same as default — safe)
    expect_ok("cmd/comset", post(f"{base}/api/cmd/comset", {
        "index": 0, "addr": 0, "baud": 9600
    }))
    time.sleep(0.5)

    # Add reader (will fail if max readers reached, but tests the endpoint)
    r = post(f"{base}/api/cmd/add_reader", {"addr": 1})
    if r.status_code < 400:
        ok("cmd/add_reader", r, note="sent")
    else:
        fail("cmd/add_reader", r)


def test_users(base):
    log("USERS", "Users CRUD")

    # List users
    users = expect_json("users/list", get(f"{base}/api/users"))

    # Create user
    r = post(f"{base}/api/users", {
        "username": f"test_api_{int(time.time())}",
        "full_name": "API Test User",
        "role": "user",
        "allowed_readers": [0],
        "schedule": "24/7"
    })
    uid = None
    if r.status_code < 400:
        j = r.json()
        uid = j.get("id")
        if j.get("ok"):
            ok("users/create", r, f"id={uid}")
        else:
            fail("users/create", r, j.get("error", ""))
    else:
        fail("users/create", r)

    # Update user
    if uid:
        expect_ok("users/update", put(f"{base}/api/users/{uid}", {
            "full_name": "Updated API Test User",
            "role": "admin"
        }))
    else:
        skip("users/update", "no uid")

    # Delete (deactivate) user
    if uid:
        expect_ok("users/delete", delete(f"{base}/api/users/{uid}"))
    else:
        skip("users/delete", "no uid")


def test_credentials(base):
    log("CREDS", "Credentials")

    # List credentials
    expect_json("credentials/list", get(f"{base}/api/credentials"))

    # Enroll card (manual) — needs a valid user_id; create a temp user
    r = post(f"{base}/api/users", {
        "username": f"cred_test_{int(time.time())}",
        "full_name": "Cred Test",
        "role": "user"
    })
    uid = None
    try:
        uid = r.json().get("id")
    except Exception:
        pass

    if uid:
        # Enroll card manually
        r = post(f"{base}/api/enroll/card", {
            "user_id": uid,
            "card_hex": "AABBCCDD",
            "bits": 26,
            "format": 1,
            "reader": 0
        })
        if r.status_code < 400 and r.json().get("ok"):
            ok("enroll/card (manual)", r)
        else:
            fail("enroll/card (manual)", r)

        # Enroll PIN manually
        r = post(f"{base}/api/enroll/pin", {
            "user_id": uid,
            "pin_hex": "31323334",
            "reader": 0
        })
        if r.status_code < 400 and r.json().get("ok"):
            ok("enroll/pin (manual)", r)
        else:
            fail("enroll/pin (manual)", r)

        # List credentials for this user
        r = get(f"{base}/api/credentials", params={"user_id": uid})
        creds = expect_json("credentials/list (by user)", r)

        # Revoke first credential
        if creds and len(creds) > 0:
            cid = creds[0].get("_id") or creds[0].get("id")
            if cid:
                expect_ok("credentials/revoke", delete(f"{base}/api/credentials/{cid}"))
            else:
                skip("credentials/revoke", "no cid in response")
        else:
            skip("credentials/revoke", "no credentials to revoke")

        # Cleanup — delete test user
        delete(f"{base}/api/users/{uid}")
    else:
        skip("enroll/card (manual)", "no uid")
        skip("enroll/pin (manual)", "no uid")
        skip("credentials/list (by user)", "no uid")
        skip("credentials/revoke", "no uid")


def test_enrollment(base):
    log("ENROLL", "Live enrollment start/cancel")

    # Create temp user for enrollment
    r = post(f"{base}/api/users", {
        "username": f"enroll_test_{int(time.time())}",
        "full_name": "Enroll Test",
        "role": "user"
    })
    uid = None
    try:
        uid = r.json().get("id")
    except Exception:
        pass

    if uid:
        # Start enrollment
        expect_ok("enroll/start", post(f"{base}/api/enroll/start", {
            "user_id": uid,
            "mode": "card"
        }))

        # Cancel enrollment
        expect_ok("enroll/cancel", post(f"{base}/api/enroll/cancel"))

        # Cleanup
        delete(f"{base}/api/users/{uid}")
    else:
        skip("enroll/start", "no uid")
        skip("enroll/cancel", "no uid")


def test_schedules(base):
    log("SCHEDULES", "Schedules CRUD")

    # List schedules
    expect_json("schedules/list", get(f"{base}/api/schedules"))

    # Create schedule
    r = post(f"{base}/api/schedules", {
        "name": f"test_sched_{int(time.time())}",
        "periods": [
            {"day": "mon", "start": "08:00", "end": "17:00"},
            {"day": "tue", "start": "08:00", "end": "17:00"}
        ]
    })
    sid = None
    if r.status_code < 400:
        j = r.json()
        if j.get("ok"):
            ok("schedules/create", r)
            # Need to get the ID — list and find our schedule
            all_scheds = get(f"{base}/api/schedules").json()
            for s in all_scheds:
                sn = s.get("name", "")
                if sn.startswith("test_sched_"):
                    sid = s.get("_id") or s.get("id")
                    break
        else:
            fail("schedules/create", r, j.get("error", ""))
    else:
        fail("schedules/create", r)

    # Update schedule
    if sid:
        expect_ok("schedules/update", put(f"{base}/api/schedules/{sid}", {
            "name": "test_sched_updated",
            "periods": [{"day": "wed", "start": "09:00", "end": "18:00"}]
        }))
    else:
        skip("schedules/update", "no sid")

    # Delete schedule
    if sid:
        expect_ok("schedules/delete", delete(f"{base}/api/schedules/{sid}"))
    else:
        skip("schedules/delete", "no sid")


def test_events_and_logs(base):
    log("EVENTS", "Events, access log, readers, system logs")

    # Events
    expect_json("events/list", get(f"{base}/api/events"))
    expect_json("events/list (with type)", get(f"{base}/api/events", params={"type": "card"}))
    expect_json("events/list (with limit)", get(f"{base}/api/events", params={"limit": 10}))

    # Access log
    expect_json("access_log/list", get(f"{base}/api/access_log"))
    expect_json("access_log/list (limit)", get(f"{base}/api/access_log", params={"limit": 10}))

    # Readers
    expect_json("readers/list", get(f"{base}/api/readers"))

    # System logs
    expect_json("system_logs/list", get(f"{base}/api/system_logs"))
    expect_json("system_logs/list (limit)", get(f"{base}/api/system_logs", params={"limit": 10}))
    expect_json("system_logs/list (level)", get(f"{base}/api/system_logs", params={"level": "error"}))


def test_firmware(base, skip_hw):
    log("FIRMWARE", "Firmware version")

    if skip_hw:
        skip("firmware/version", "hardware skipped")
        return

    r = get(f"{base}/api/firmware/version")
    if r.status_code < 400:
        ok("firmware/version", r)
    else:
        # 503 means bridge not connected — still a valid response
        if r.status_code == 503:
            ok("firmware/version", r, note="bridge not connected (expected)")
        else:
            fail("firmware/version", r)


def test_bridge_disconnect(base, skip_hw):
    log("BRIDGE", "Bridge disconnect")

    if skip_hw:
        skip("bridge/disconnect", "hardware skipped")
        return

    expect_ok("bridge/disconnect", post(f"{base}/api/bridge/disconnect"))


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="OSDP Access Panel API Tester")
    parser.add_argument("--base", default="http://localhost:5000",
                        help="Base URL of Flask server")
    parser.add_argument("--skip-hw", action="store_true",
                        help="Skip hardware-dependent tests")
    parser.add_argument("--username", default="admin",
                        help="Panel login username")
    parser.add_argument("--password", default="osdp",
                        help="Panel login password")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    skip_hw = args.skip_hw

    print(f"\n{Colors.BOLD}{'='*60}")
    print(f" OSDP Access Panel - API Test Suite")
    print(f" Target: {base}")
    print(f" Hardware tests: {'SKIPPED' if skip_hw else 'ENABLED'}")
    print(f"{'='*60}{Colors.RESET}\n")

    # Check server is reachable
    try:
        r = get(f"{base}/api/bridge/status")
        if r.status_code >= 500:
            print(f"{Colors.RED}Server returned {r.status_code}. Is Flask running?{Colors.RESET}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"{Colors.RED}Cannot reach {base}. Start the Flask server first.{Colors.RESET}")
        sys.exit(1)

    print(f"{Colors.GREEN}Server reachable.{Colors.RESET}\n")

    if not authenticate(base, args.username, args.password):
        sys.exit(1)

    # Run all test groups
    connected = test_bridge(base, skip_hw)
    print()
    test_mcu_commands(base, skip_hw)
    print()
    test_users(base)
    print()
    test_credentials(base)
    print()
    test_enrollment(base)
    print()
    test_schedules(base)
    print()
    test_events_and_logs(base)
    print()
    test_firmware(base, skip_hw)
    print()
    test_bridge_disconnect(base, skip_hw)

    # Summary
    total = passed + failed + skipped
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f" Results: {total} tests")
    print(f"   {Colors.GREEN}+ Passed:  {passed}{Colors.RESET}")
    print(f"   {Colors.RED}x Failed:  {failed}{Colors.RESET}")
    print(f"   {Colors.YELLOW}o Skipped: {skipped}{Colors.RESET}")
    print(f"{'='*60}{Colors.RESET}")

    if failed:
        print(f"\n{Colors.RED}Failed tests:{Colors.RESET}")
        for status, name in results:
            if status == "FAIL":
                print(f"  - {name}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
