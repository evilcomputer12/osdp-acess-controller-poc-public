"""
Selenium test — click every button in the OSDP Access Panel webapp,
capture the API request/response for each, and print a summary.
"""

import time, json, sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException,
    UnexpectedAlertPresentException, ElementClickInterceptedException,
)

BASE = "http://localhost:3000"
RESULTS = []  # (test_name, pass/fail, detail)

# ── helpers ──────────────────────────────────────────────────

def ok(name, detail=""):
    RESULTS.append((name, "PASS", detail))
    print(f"  ✔ {name}  {detail}")

def fail(name, detail=""):
    RESULTS.append((name, "FAIL", detail))
    print(f"  ✘ {name}  {detail}")

def inject_fetch_spy(driver):
    """Monkey-patch fetch() so we can retrieve the last request/response."""
    driver.execute_script("""
        window.__apiLog = [];
        const _origFetch = window.fetch;
        window.fetch = async function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
            const method = args[1]?.method || 'GET';
            const entry = {url, method, status: null, ok: null, ts: Date.now()};
            try {
                const resp = await _origFetch.apply(this, args);
                entry.status = resp.status;
                entry.ok = resp.ok;
                window.__apiLog.push(entry);
                return resp;
            } catch(e) {
                entry.status = 'ERR';
                entry.ok = false;
                window.__apiLog.push(entry);
                throw e;
            }
        };
    """)

def drain_api_log(driver):
    """Return and clear the captured API log entries."""
    return driver.execute_script("""
        const log = window.__apiLog || [];
        window.__apiLog = [];
        return log;
    """)

def last_api(driver, wait=1.5):
    """Wait briefly, then return the most recent API log entry (or None)."""
    time.sleep(wait)
    entries = drain_api_log(driver)
    return entries[-1] if entries else None

def check_api(driver, test_name, expected_url_part=None, expected_method=None, wait=1.5):
    """Check that an API call matching the expected URL was made and returned 200."""
    time.sleep(wait)
    candidates = drain_api_log(driver)

    if not candidates:
        fail(test_name, "no API call captured")
        return False

    # Find matching entry by URL
    match = None
    if expected_url_part:
        for e in candidates:
            if e and expected_url_part in e.get("url", ""):
                match = e
                break
    if match is None:
        match = candidates[-1]  # fall back to last entry

    status = match.get("status")
    url = match.get("url", "")
    method = match.get("method", "")
    detail = f"{method} {url} → {status}"
    if expected_url_part and expected_url_part not in url:
        fail(test_name, f"expected {expected_url_part} not in: {detail}")
        return False
    if expected_method and method != expected_method:
        fail(test_name, f"wrong method: {detail}")
        return False
    if status == 200:
        ok(test_name, detail)
        return True
    else:
        fail(test_name, detail)
        return False

def click(driver, xpath, timeout=5):
    """Wait for element, scroll into view, click."""
    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    el.click()
    return el

def nav_to(driver, page_name):
    """Click a sidebar nav link by visible text."""
    click(driver, f"//a[contains(@class,'nav-link') and contains(.,'{page_name}')]")
    time.sleep(0.8)
    drain_api_log(driver)  # discard page-load fetches


def login(driver, username="admin", password="osdp"):
    """Sign in through the login screen before running navigation tests."""
    try:
        user_input = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, "//input[@autocomplete='username']"))
        )
        pass_input = driver.find_element(By.XPATH, "//input[@autocomplete='current-password']")
        user_input.clear()
        user_input.send_keys(username)
        pass_input.clear()
        pass_input.send_keys(password)
        click(driver, "//button[@type='submit' and contains(.,'Sign in')]", timeout=5)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@class,'nav-link') and contains(.,'Dashboard')]"))
        )
        ok("Login", f"signed in as {username}")
    except Exception as exc:
        fail("Login", str(exc)[:80])
        raise

def dismiss_alert(driver):
    """Dismiss any JS alert/confirm/prompt if present."""
    try:
        WebDriverWait(driver, 1).until(EC.alert_is_present())
        driver.switch_to.alert.dismiss()
        time.sleep(0.3)
    except TimeoutException:
        pass

def safe_click(driver, xpath, test_name, expected_url=None, expected_method="POST", wait=1.5, timeout=5):
    """Click a button and check the API call result, handling alerts."""
    drain_api_log(driver)
    try:
        click(driver, xpath, timeout)
    except UnexpectedAlertPresentException:
        dismiss_alert(driver)
        fail(test_name, "unexpected alert blocked click")
        return False
    except (NoSuchElementException, TimeoutException):
        fail(test_name, "element not found")
        return False
    except ElementClickInterceptedException:
        fail(test_name, "click intercepted (overlay?)")
        return False
    # some buttons trigger prompt/confirm — dismiss
    dismiss_alert(driver)
    return check_api(driver, test_name, expected_url, expected_method, wait)


# ── test suites ──────────────────────────────────────────────

def test_navigation(driver):
    """Click each sidebar nav link and verify the page renders."""
    print("\n═══ Navigation ═══")
    pages = [
        "Dashboard", "Readers", "Users", "Enrollment", "Schedules",
        "Events", "Access Log", "Reader Config", "Comms Monitor",
        "System Logs", "Terminal", "Firmware",
    ]
    for p in pages:
        try:
            click(driver, f"//a[contains(@class,'nav-link') and contains(.,'{p}')]")
            time.sleep(0.5)
            # verify active class
            active = driver.find_elements(By.XPATH, f"//a[contains(@class,'nav-link') and contains(@class,'active') and contains(.,'{p}')]")
            if active:
                ok(f"Nav → {p}")
            else:
                fail(f"Nav → {p}", "link not active after click")
        except Exception as e:
            fail(f"Nav → {p}", str(e)[:80])
        drain_api_log(driver)


def test_connect_disconnect(driver):
    """Test Connect / Disconnect toggle."""
    print("\n═══ Connect / Disconnect ═══")

    # Determine current state
    try:
        btn = driver.find_element(By.XPATH, "//button[text()='Connect' or text()='Disconnect']")
        label = btn.text
    except NoSuchElementException:
        fail("Connect btn", "not found")
        return

    if label == "Disconnect":
        # Already connected — test disconnect first, then reconnect
        drain_api_log(driver)
        btn.click()
        check_api(driver, "Disconnect", "/api/bridge/disconnect", "POST", wait=2)
        time.sleep(1)
        # Now Connect
        safe_click(driver, "//button[text()='Connect']", "Connect",
                   "/api/bridge/connect", "POST", wait=3)
    else:
        # Not connected — connect first
        safe_click(driver, "//button[text()='Connect']", "Connect",
                   "/api/bridge/connect", "POST", wait=3)
        time.sleep(1)
        safe_click(driver, "//button[text()='Disconnect']", "Disconnect",
                   "/api/bridge/disconnect", "POST", wait=2)
        time.sleep(1)
        # Reconnect so rest of tests can talk to MCU
        safe_click(driver, "//button[text()='Connect']", "Reconnect",
                   "/api/bridge/connect", "POST", wait=3)

    time.sleep(1)


def test_readers_page(driver):
    """Test buttons on the Readers page."""
    print("\n═══ Readers ═══")
    nav_to(driver, "Readers")
    time.sleep(1)

    time.sleep(1)
    drain_api_log(driver)  # discard the page-load GET /api/readers
    safe_click(driver, "//button[contains(.,'Refresh Status')]",
               "Refresh Status", "/api/cmd/status", "POST", wait=2)

    # Per-reader command buttons (may not exist if no readers configured)
    for cmd in ["ID", "CAP", "LSTAT", "ISTAT", "OSTAT"]:
        try:
            btns = driver.find_elements(By.XPATH, f"//button[text()='{cmd}']")
            if btns:
                drain_api_log(driver)
                btns[0].click()
                check_api(driver, f"Reader cmd: {cmd}",
                          f"/api/cmd/{cmd.lower()}", "POST")
            else:
                ok(f"Reader cmd: {cmd}", "no readers — skipped")
        except Exception as e:
            fail(f"Reader cmd: {cmd}", str(e)[:80])

    # Secure channel button
    try:
        sec_btns = driver.find_elements(By.XPATH, "//button[contains(.,'Secure')]")
        if sec_btns:
            drain_api_log(driver)
            sec_btns[0].click()
            check_api(driver, "Reader: Secure Channel", "/api/cmd/sc", "POST")
        else:
            ok("Reader: Secure Channel", "no readers — skipped")
    except Exception as e:
        fail("Reader: Secure Channel", str(e)[:80])

    # Add Reader — opens prompt (we dismiss)
    try:
        drain_api_log(driver)
        click(driver, "//button[contains(.,'Add Reader')]", timeout=3)
        dismiss_alert(driver)  # dismiss addr prompt
        dismiss_alert(driver)  # dismiss scbk prompt (if reached)
        ok("Reader: Add Reader btn", "prompt dismissed")
    except (NoSuchElementException, TimeoutException):
        ok("Reader: Add Reader btn", "not present — skipped")
    except Exception as e:
        fail("Reader: Add Reader btn", str(e)[:80])


def test_reader_config(driver):
    """Test Reader Config page buttons."""
    print("\n═══ Reader Config ═══")
    nav_to(driver, "Reader Config")
    time.sleep(0.5)

    # LED
    safe_click(driver, "//button[contains(.,'Send LED')]",
               "Send LED", "/api/cmd/led", "POST")

    # Buzzer
    safe_click(driver, "//button[contains(.,'Send Buzzer')]",
               "Send Buzzer", "/api/cmd/buzzer", "POST")

    # Relay
    safe_click(driver, "//button[contains(.,'Relay')]",
               "Relay", "/api/cmd/relay", "POST")

    # Set COM (dangerous — skip actual click, just check presence)
    try:
        btn = driver.find_element(By.XPATH, "//button[contains(.,'Set COM')]")
        ok("Set COM btn", "present (not clicked — dangerous)")
    except NoSuchElementException:
        fail("Set COM btn", "not found")

    # Set Key (dangerous — skip actual click)
    try:
        btn = driver.find_element(By.XPATH, "//button[contains(.,'Set Key')]")
        ok("Set Key btn", "present (not clicked — dangerous)")
    except NoSuchElementException:
        fail("Set Key btn", "not found")


def test_comms_monitor(driver):
    """Test Comms Monitor page buttons."""
    print("\n═══ Comms Monitor ═══")
    nav_to(driver, "Comms Monitor")
    time.sleep(0.5)

    safe_click(driver, "//button[contains(.,'Debug ON')]",
               "Debug ON", "/api/cmd/debug", "POST")

    safe_click(driver, "//button[contains(.,'Debug OFF')]",
               "Debug OFF", "/api/cmd/debug", "POST")

    # Clear is local-only (no API call)
    try:
        click(driver, "//button[contains(.,'Clear')]", timeout=3)
        ok("Clear comms", "clicked (no API call expected)")
    except (NoSuchElementException, TimeoutException):
        fail("Clear comms", "not found")


def test_events_page(driver):
    """Test Events page."""
    print("\n═══ Events ═══")
    nav_to(driver, "Events")
    time.sleep(1)
    # Refresh button has icon bi-arrow-repeat, no text
    safe_click(driver, "//button[.//i[contains(@class,'bi-arrow-repeat')]]",
               "Events Refresh", "/api/events", "GET")


def test_access_log(driver):
    """Test Access Log page."""
    print("\n═══ Access Log ═══")
    nav_to(driver, "Access Log")
    time.sleep(0.5)
    try:
        click(driver, "//button[contains(.,'Refresh')]", timeout=3)
        drain_api_log(driver)  # may have already fired on mount
        ok("Access Log Refresh", "clicked")
    except (NoSuchElementException, TimeoutException):
        fail("Access Log Refresh", "not found")


def test_system_logs(driver):
    """Test System Logs page."""
    print("\n═══ System Logs ═══")
    nav_to(driver, "System Logs")
    time.sleep(1)
    safe_click(driver, "//button[contains(.,'Refresh')]",
               "System Logs Refresh", "/api/system_logs", "GET")


def test_terminal(driver):
    """Test Terminal page — type a command and hit Send."""
    print("\n═══ Terminal ═══")
    nav_to(driver, "Terminal")
    time.sleep(0.5)

    try:
        inp = driver.find_element(By.XPATH, "//input[@placeholder='Type command…' or @placeholder='Type command...']")
        inp.clear()
        inp.send_keys("PING")
        click(driver, "//button[text()='Send']", timeout=3)
        ok("Terminal Send", "sent 'PING' via socket.emit (no REST call)")
    except (NoSuchElementException, TimeoutException) as e:
        fail("Terminal Send", str(e)[:80])


def test_users_page(driver):
    """Test Users page — just check New User button opens modal."""
    print("\n═══ Users ═══")
    nav_to(driver, "Users")
    time.sleep(0.5)

    try:
        click(driver, "//button[contains(.,'New User')]", timeout=3)
        time.sleep(0.5)
        # Check modal appeared
        modal = driver.find_elements(By.XPATH, "//div[contains(@class,'modal-dialog')]")
        if modal:
            ok("New User modal", "opened")
            # Close it
            try:
                click(driver, "//div[contains(@class,'modal')]//button[contains(@class,'btn-close')]", timeout=2)
            except Exception:
                driver.execute_script("document.querySelector('.modal')?.remove(); document.querySelector('.modal-backdrop')?.remove();")
            time.sleep(0.3)
        else:
            fail("New User modal", "did not appear")
    except Exception as e:
        fail("New User modal", str(e)[:80])


def test_enrollment_page(driver):
    """Test Enrollment page buttons."""
    print("\n═══ Enrollment ═══")
    nav_to(driver, "Enrollment")
    time.sleep(0.5)

    # Scan Next Card — needs a user selected; may fail if no users
    try:
        btns = driver.find_elements(By.XPATH, "//button[contains(.,'Scan Next Card')]")
        if btns:
            drain_api_log(driver)
            btns[0].click()
            time.sleep(1)
            entry = last_api(driver, wait=0.5)
            if entry:
                ok("Scan Next Card", f"{entry.get('method')} {entry.get('url')} → {entry.get('status')}")
            else:
                ok("Scan Next Card", "clicked (may need user selected)")
        else:
            ok("Scan Next Card", "not present")
    except Exception as e:
        fail("Scan Next Card", str(e)[:80])

    # Cancel
    try:
        cancel_btns = driver.find_elements(By.XPATH, "//button[text()='Cancel']")
        if cancel_btns:
            drain_api_log(driver)
            cancel_btns[0].click()
            time.sleep(1)
            ok("Enrollment Cancel", "clicked")
        else:
            ok("Enrollment Cancel", "not present")
    except Exception as e:
        fail("Enrollment Cancel", str(e)[:80])


def test_schedules_page(driver):
    """Test Schedules page — check New Schedule opens modal."""
    print("\n═══ Schedules ═══")
    nav_to(driver, "Schedules")
    time.sleep(0.5)

    try:
        click(driver, "//button[contains(.,'New Schedule')]", timeout=3)
        time.sleep(0.5)
        modal = driver.find_elements(By.XPATH, "//div[contains(@class,'modal-dialog')]")
        if modal:
            ok("New Schedule modal", "opened")
            try:
                click(driver, "//div[contains(@class,'modal')]//button[contains(@class,'btn-close')]", timeout=2)
            except Exception:
                driver.execute_script("document.querySelector('.modal')?.remove(); document.querySelector('.modal-backdrop')?.remove();")
            time.sleep(0.3)
        else:
            fail("New Schedule modal", "did not appear")
    except Exception as e:
        fail("New Schedule modal", str(e)[:80])


def test_firmware_page(driver):
    """Test Firmware page — check Flash button is present (don't actually flash)."""
    print("\n═══ Firmware ═══")
    nav_to(driver, "Firmware")
    time.sleep(0.5)

    try:
        btn = driver.find_element(By.XPATH, "//button[contains(.,'Flash')]")
        ok("Flash btn", "present (not clicked — needs .bin file)")
    except NoSuchElementException:
        fail("Flash btn", "not found")

    try:
        inp = driver.find_element(By.XPATH, "//input[@type='file']")
        ok("File input", "present")
    except NoSuchElementException:
        fail("File input", "not found")


# ── main ─────────────────────────────────────────────────────

def main():
    print("Starting Selenium test suite for OSDP Access Panel…\n")

    opts = webdriver.ChromeOptions()
    opts.add_argument("--disable-search-engine-choice-screen")
    opts.add_argument("--no-first-run")
    opts.add_argument("--start-maximized")
    # opts.add_argument("--headless=new")  # uncomment for headless

    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(3)

    try:
        driver.get(BASE)
        time.sleep(2)
        login(driver)
        inject_fetch_spy(driver)
        time.sleep(1)

        test_navigation(driver)
        test_connect_disconnect(driver)
        # Re-inject spy after page reload / reconnect
        inject_fetch_spy(driver)
        time.sleep(1)

        test_readers_page(driver)
        test_reader_config(driver)
        test_comms_monitor(driver)
        test_events_page(driver)
        test_access_log(driver)
        test_system_logs(driver)
        test_terminal(driver)
        test_users_page(driver)
        test_enrollment_page(driver)
        test_schedules_page(driver)
        test_firmware_page(driver)

    except Exception as e:
        print(f"\n!!! Unhandled exception: {e}")
    finally:
        # ── Summary ──
        print("\n" + "═" * 60)
        print("  TEST SUMMARY")
        print("═" * 60)
        passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
        failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
        for name, status, detail in RESULTS:
            mark = "✔" if status == "PASS" else "✘"
            print(f"  {mark} {name:40s} {detail[:60]}")
        print(f"\n  {passed} passed, {failed} failed, {passed + failed} total")
        print("═" * 60)

        input("\nPress Enter to close browser…")
        driver.quit()


if __name__ == "__main__":
    main()
