"""
OSDP Access Control Panel — Flask + SocketIO application.
Uses threading mode for SocketIO to avoid eventlet+pyserial conflicts on Windows.
"""

import os
import logging
import threading
import queue
import time
from functools import wraps
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify, send_from_directory, session
from flask_socketio import SocketIO, emit, disconnect
from werkzeug.security import check_password_hash

from bridge import OsdpBridge
from models import (
    get_db, create_user, list_users, get_user, update_user,
    deactivate_user, enroll_card, enroll_pin, find_credential_by_card,
    find_credential_by_pin, list_credentials, revoke_credential,
    log_event, get_events, log_access, get_access_log,
    upsert_reader, list_readers, list_schedules, get_schedule,
    create_schedule, update_schedule, delete_schedule,
    check_schedule, check_reader_access,
    log_system, get_system_logs,
    get_panel_user_by_username,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Serve React build from static/dist, fall back to templates for legacy
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static", "dist")
app = Flask(__name__,
            static_folder=os.path.join(STATIC_DIR, "assets"),
            static_url_path="/assets",
            template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ── Database ──────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
db = get_db(MONGO_URI)

# ── Bridge instance ──────────────────────────────────────────
# Event queue decouples serial reader from processing (prevents USB backpressure freeze)
_event_queue = queue.Queue(maxsize=500)

def _enqueue_event(ev):
    """Non-blocking enqueue — called from serial reader thread."""
    try:
        _event_queue.put_nowait(ev)
    except queue.Full:
        log.warning("Event queue full, dropping event: %s", ev.get("type"))

bridge = OsdpBridge(
    on_event=_enqueue_event,
)

# Track enrollment mode
_enroll_state = {"active": False, "user_id": None, "mode": None}

# PIN accumulation buffer — keyed by reader index
# Each entry: {"hex": "", "timer": Timer|None}
_pin_buffer = {}
_pin_lock = threading.Lock()
PIN_TIMEOUT_SEC = 5  # seconds to wait after last key before auto-submit


# Event types that are meaningful enough to persist in MongoDB
_DB_LOG_TYPES = frozenset({
    "card", "keypad", "state", "pd_status", "pdid", "pdcap",
    "lstat", "nak", "error", "reconnected", "boot", "config",
    "sensor", "door", "relay", "com",
})

AUTH_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
})

ADMIN_ONLY_GET_PATHS = frozenset({
    "/api/firmware/version",
})


def _handle_event(ev):
    """Process every MCU event: log, check access, push to frontend."""
    ev_type = ev.get("type", "unknown")

    # Only persist meaningful events to DB (skip heartbeat, pong, ok, debug, etc.)
    if ev_type in _DB_LOG_TYPES:
        log_event(db, {k: v for k, v in ev.items()})

    # Push to comms monitor (skip heartbeat — too noisy)
    if ev_type != "heartbeat":
        socketio.emit("comms", _jsonable(ev), namespace="/")

    # Push typed events to frontend
    socketio.emit("event", _jsonable(ev), namespace="/")

    # Handle specific event types
    if ev_type == "card":
        _process_card(ev)

    if ev_type == "keypad":
        _process_keypad(ev)

    if ev_type == "debug":
        socketio.emit("debug", _jsonable(ev), namespace="/")

    if ev_type == "heartbeat":
        socketio.emit("heartbeat", _jsonable(ev), namespace="/")

    if ev_type == "pd_status":
        upsert_reader(db, ev["index"], {
            "addr": ev["addr"], "state": ev["state"],
            "sc": ev["sc"], "tamper": ev["tamper"],
            "power": ev["power"], "last_seen": _coerce_event_ts(ev.get("ts")) or ev.get("ts"),
        })
        socketio.emit("reader_update", _jsonable(ev), namespace="/")

    if ev_type == "lstat":
        upsert_reader(db, ev["reader"], {
            "tamper": ev["tamper"], "power": ev["power"],
            "last_seen": _coerce_event_ts(ev.get("ts")) or ev.get("ts"),
        })

    if ev_type == "state":
        upsert_reader(db, ev["reader"], {
            "state": ev["state"], "last_seen": _coerce_event_ts(ev.get("ts")) or ev.get("ts"),
        })
        # Auto-initiate secure channel when reader comes online
        if ev["state"] == "ONLINE":
            bridge.secure_channel(ev["reader"])

    if ev_type == "pdid":
        upsert_reader(db, ev["reader"], {
            "vendor": ev["vendor"], "model": ev["model"],
            "serial": ev["serial"], "firmware": ev["firmware"],
            "last_seen": _coerce_event_ts(ev.get("ts")) or ev.get("ts"),
        })


def _check_access_policy(user, reader):
    """Check reader access + time schedule. Returns (allowed, reason)."""
    if not user.get("active", True):
        return False, "user disabled"
    if user.get("role") == "admin":
        return True, "admin override"
    if not check_reader_access(user, reader):
        return False, "reader not allowed"
    sched_name = user.get("schedule", "24/7")
    if not check_schedule(db, sched_name):
        return False, f"outside schedule ({sched_name})"
    return True, "policy ok"


def _process_card(ev):
    reader = ev.get("reader", 0)

    # Enrollment mode
    if _enroll_state["active"] and _enroll_state["mode"] == "card":
        uid = _enroll_state["user_id"]
        enroll_card(db, uid, ev["hex"], ev["bits"], ev["format"], reader)
        _enroll_state["active"] = False
        user = get_user(db, uid)
        name = user["username"] if user else "?"
        # Green + beep for enrollment success
        bridge.grant_feedback(reader)
        socketio.emit("enroll_done", {
            "type": "card", "user": name, "hex": ev["hex"],
        }, namespace="/")
        return

    cred = find_credential_by_card(db, ev["hex"])
    if cred:
        user = get_user(db, str(cred["user_id"]))
        name = user["username"] if user else "unknown"
        allowed, reason = _check_access_policy(user, reader) if user else (False, "user not found")
        if allowed:
            log_access(db, card_hex=ev["hex"], user_id=str(cred["user_id"]),
                       username=name, granted=True, reader=reader,
                       reason=reason)
            bridge.relay(reader, "T1500")
            bridge.grant_feedback(reader)
            socketio.emit("access", {
                "granted": True, "username": name, "method": "card",
                "hex": ev["hex"], "reader": reader,
            }, namespace="/")
        else:
            log_access(db, card_hex=ev["hex"], user_id=str(cred["user_id"]),
                       username=name, granted=False, reader=reader,
                       reason=reason)
            bridge.deny_feedback(reader)
            socketio.emit("access", {
                "granted": False, "username": name, "method": "card",
                "hex": ev["hex"], "reader": reader, "reason": reason,
            }, namespace="/")
    else:
        log_access(db, card_hex=ev["hex"], granted=False, reader=reader,
                   reason="unknown card")
        bridge.deny_feedback(reader)
        socketio.emit("access", {
            "granted": False, "method": "card",
            "hex": ev["hex"], "reader": reader, "reason": "unknown card",
        }, namespace="/")


def _process_keypad(ev):
    """Accumulate keypad presses; 0x0D (#) = enter/submit, 0x7F (*) = clear.
    Falls back to auto-submit after PIN_TIMEOUT_SEC of inactivity.
    """
    reader = ev.get("reader", 0)
    raw_hex = ev.get("hex", "").upper()
    flush_hex = None
    emit_progress = None  # (reader, length, cleared) or None

    with _pin_lock:
        if reader not in _pin_buffer:
            _pin_buffer[reader] = {"hex": "", "timer": None}
        buf = _pin_buffer[reader]

        # Cancel any pending timer
        if buf["timer"]:
            buf["timer"].cancel()
            buf["timer"] = None

        submit = False
        # Process each byte pair in the hex string
        for i in range(0, len(raw_hex), 2):
            byte_hex = raw_hex[i:i+2]
            if byte_hex == "0D":  # '#' key = enter/submit
                submit = True
                break
            elif byte_hex == "7F":  # '*' key = clear/backspace
                buf["hex"] = ""
                emit_progress = (reader, 0, True)
                continue
            else:
                buf["hex"] += byte_hex

        if submit and buf["hex"]:
            flush_hex = buf["hex"]
            buf["hex"] = ""
        elif buf["hex"]:
            pin_len = len(buf["hex"]) // 2
            emit_progress = (reader, pin_len, False)
            # Start / restart timeout — auto-submit after PIN_TIMEOUT_SEC
            buf["timer"] = threading.Timer(
                PIN_TIMEOUT_SEC, _flush_pin_from_timer, args=[reader])
            buf["timer"].daemon = True
            buf["timer"].start()

    # Emit outside the lock to avoid contention
    if emit_progress:
        socketio.emit("pin_progress", {
            "reader": emit_progress[0], "length": emit_progress[1],
            "cleared": emit_progress[2],
        }, namespace="/")

    if flush_hex:
        _flush_pin(reader, flush_hex)


def _flush_pin_from_timer(reader):
    """Called by the timer thread when PIN_TIMEOUT_SEC elapses."""
    with _pin_lock:
        buf = _pin_buffer.get(reader)
        if not buf or not buf["hex"]:
            return
        pin_hex = buf["hex"]
        buf["hex"] = ""
        buf["timer"] = None
    _flush_pin(reader, pin_hex)


def _flush_pin(reader, pin_hex):
    """Process a complete accumulated PIN."""
    log.info("PIN complete on reader %d: %d digits", reader, len(pin_hex) // 2)

    if _enroll_state["active"] and _enroll_state["mode"] == "pin":
        uid = _enroll_state["user_id"]
        enroll_pin(db, uid, pin_hex, reader)
        _enroll_state["active"] = False
        user = get_user(db, uid)
        name = user["username"] if user else "?"
        bridge.grant_feedback(reader)
        socketio.emit("enroll_done", {
            "type": "pin", "user": name, "hex": pin_hex,
        }, namespace="/")
        return

    cred = find_credential_by_pin(db, pin_hex)
    if cred:
        user = get_user(db, str(cred["user_id"]))
        name = user["username"] if user else "unknown"
        allowed, reason = _check_access_policy(user, reader) if user else (False, "user not found")
        if allowed:
            log_access(db, pin_hex=pin_hex, user_id=str(cred["user_id"]),
                       username=name, granted=True, reader=reader,
                       reason=reason)
            bridge.relay(reader, "T1500")
            bridge.grant_feedback(reader)
            socketio.emit("access", {
                "granted": True, "username": name, "method": "pin",
                "reader": reader,
            }, namespace="/")
        else:
            log_access(db, pin_hex=pin_hex, user_id=str(cred["user_id"]),
                       username=name, granted=False, reader=reader,
                       reason=reason)
            bridge.deny_feedback(reader)
            socketio.emit("access", {
                "granted": False, "username": name, "method": "pin",
                "reader": reader, "reason": reason,
            }, namespace="/")
    else:
        log_access(db, pin_hex=pin_hex, granted=False, reader=reader,
                   reason="unknown pin")
        bridge.deny_feedback(reader)
        socketio.emit("access", {
            "granted": False, "method": "pin", "reader": reader,
            "reason": "unknown pin",
        }, namespace="/")


def _jsonable(obj):
    """Make Mongo/BSON objects JSON-serialisable."""
    from bson import ObjectId
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "_id":
                out["id"] = str(v)
            elif isinstance(v, ObjectId):
                out[k] = str(v)
            elif isinstance(v, datetime):
                out[k] = v.isoformat()
            else:
                out[k] = _jsonable(v)
        return out
    if isinstance(obj, list):
        return [_jsonable(i) for i in obj]
    if isinstance(obj, ObjectId):
        return str(obj)
    return obj


def _reader_snapshot(index):
    return db.readers.find_one({"index": index})


def _coerce_event_ts(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _reader_freshness(reader_doc, stale_after_sec=90):
    if not reader_doc:
        return None
    last_seen = _coerce_event_ts(reader_doc.get("last_seen"))
    if last_seen is None:
        return {"stale": True, "last_seen_age_sec": None}

    now = datetime.now(timezone.utc)
    age_sec = max(0.0, (now - last_seen).total_seconds())
    return {
        "stale": age_sec > stale_after_sec,
        "last_seen_age_sec": round(age_sec, 1),
    }


def _bridge_not_connected_response():
    return jsonify({"ok": False, "error": "bridge not connected"}), 503


def _panel_user_payload(user_doc):
    if not user_doc:
        return None
    return {
        "username": user_doc.get("username"),
        "role": user_doc.get("role", "viewer"),
        "display_name": user_doc.get("display_name") or user_doc.get("username"),
    }


def _current_panel_user():
    username = session.get("panel_username")
    if not username:
        return None
    user_doc = get_panel_user_by_username(db, username)
    if not user_doc or not user_doc.get("active", True):
        session.clear()
        return None
    return user_doc


def _auth_error(status_code, message):
    return jsonify({"ok": False, "error": message}), status_code


def _require_panel_login():
    user_doc = _current_panel_user()
    if not user_doc:
        return None, _auth_error(401, "authentication required")
    return user_doc, None


def _require_panel_admin():
    user_doc, response = _require_panel_login()
    if response is not None:
        return None, response
    if user_doc.get("role") != "admin":
        return None, _auth_error(403, "admin access required")
    return user_doc, None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _, response = _require_panel_login()
        if response is not None:
            return response
        return fn(*args, **kwargs)
    return wrapper


@app.before_request
def enforce_panel_authentication():
    path = request.path.rstrip("/") or "/"
    if request.method == "OPTIONS":
        return None
    if path in AUTH_EXEMPT_PATHS:
        return None
    if path == "/" or path.startswith("/assets/"):
        return None
    if path.startswith("/socket.io/"):
        return None
    if not path.startswith("/api/"):
        return None

    user_doc, response = _require_panel_login()
    if response is not None:
        return response

    if path in ADMIN_ONLY_GET_PATHS or request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        if path == "/api/auth/logout":
            return None
        if user_doc.get("role") != "admin":
            return _auth_error(403, "admin access required")
    return None


def _command_enqueued(command, sent, *, reader_index=None):
    if not bridge.connected:
        return _bridge_not_connected_response()
    if not sent:
        return jsonify({
            "ok": False,
            "command": command,
            "error": "failed to write command to bridge",
        }), 500

    payload = {
        "ok": True,
        "command": command,
        "queued": True,
        "bridge_connected": bridge.connected,
    }
    if reader_index is not None:
        payload["reader"] = reader_index
        snapshot = _reader_snapshot(reader_index)
        if snapshot:
            payload["reader_snapshot"] = _jsonable(snapshot)
            payload.update(_reader_freshness(snapshot) or {})
    return jsonify(payload)


def _command_with_reader_followup(command, sender, *, reader_index, wait_seconds=2.0):
    if not bridge.connected:
        return _bridge_not_connected_response()

    before = _reader_snapshot(reader_index)
    before_ts = before.get("last_seen") if before else None
    sent = sender()
    if not sent:
        return jsonify({
            "ok": False,
            "command": command,
            "error": "failed to write command to bridge",
            "reader": reader_index,
        }), 500

    deadline = time.time() + wait_seconds
    after = before
    while time.time() < deadline:
        candidate = _reader_snapshot(reader_index)
        if candidate is None:
            time.sleep(0.1)
            continue
        candidate_ts = candidate.get("last_seen")
        if before is None or candidate_ts != before_ts or candidate.get("sc") != before.get("sc") or candidate.get("state") != before.get("state"):
            after = candidate
            break
        after = candidate
        time.sleep(0.1)

    payload = {
        "ok": True,
        "command": command,
        "queued": True,
        "bridge_connected": bridge.connected,
        "reader": reader_index,
        "reader_before": _jsonable(before) if before else None,
        "reader_after": _jsonable(after) if after else None,
    }
    payload.update(_reader_freshness(after) or {})

    if command == "sc":
        secure_channel_active = bool(after and after.get("sc"))
        payload["secure_channel_active"] = secure_channel_active
        if not secure_channel_active:
            payload["note"] = "SC command was queued, but the reader has not reported secure channel active yet"
    return jsonify(payload)


# ══════════════════════════════════════════════════════════════
#  REST API
# ══════════════════════════════════════════════════════════════

@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user_doc = get_panel_user_by_username(db, username)
    if not user_doc or not user_doc.get("active", True):
        return _auth_error(401, "invalid username or password")
    if not check_password_hash(user_doc.get("password_hash", ""), password):
        return _auth_error(401, "invalid username or password")

    session.clear()
    session["panel_username"] = user_doc["username"]
    session["panel_role"] = user_doc.get("role", "viewer")
    log_system(db, "info", "auth", f"Panel login: {user_doc['username']}")
    return jsonify({"ok": True, "user": _panel_user_payload(user_doc)})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    user_doc = _current_panel_user()
    if user_doc:
        log_system(db, "info", "auth", f"Panel logout: {user_doc['username']}")
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me")
@login_required
def api_auth_me():
    return jsonify({"ok": True, "user": _panel_user_payload(_current_panel_user())})

@app.route("/")
def index():
    # Serve React SPA if build exists, otherwise fall back to legacy template
    react_index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(react_index):
        resp = send_from_directory(STATIC_DIR, "index.html")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
    return render_template("index.html")


@app.route("/<path:path>")
def catch_all(path):
    """Serve React static assets or fall back to index.html for SPA routing."""
    # Don't intercept API routes
    if path.startswith("api/") or path.startswith("socket.io/"):
        return "Not found", 404
    file_path = os.path.join(STATIC_DIR, path)
    if os.path.isfile(file_path):
        resp = send_from_directory(STATIC_DIR, path)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
    react_index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(react_index):
        return send_from_directory(STATIC_DIR, "index.html")
    return "Not found", 404


# ── Bridge control ────────────────────────────────────────────
@app.route("/api/bridge/status")
@login_required
def bridge_status():
    port = OsdpBridge.find_port()
    return jsonify({
        "connected": bridge.connected,
        "port": bridge.port,
        "detected_port": port,
        "tx": bridge.tx_count,
        "rx": bridge.rx_count,
    })


@app.route("/api/bridge/connect", methods=["POST"])
def bridge_connect():
    d = request.get_json(silent=True) or {}
    port = d.get("port")
    ok = bridge.connect(port)
    if ok:
        import time
        time.sleep(0.3)  # let reader loop start
        bridge.ping()
        bridge.status()
    return jsonify({"ok": ok, "port": bridge.port})


@app.route("/api/bridge/disconnect", methods=["POST"])
def bridge_disconnect():
    bridge.disconnect()
    return jsonify({"ok": True})


# ── MCU commands ──────────────────────────────────────────────
@app.route("/api/cmd/ping", methods=["POST"])
def cmd_ping():
    return _command_enqueued("ping", bridge.ping())


@app.route("/api/cmd/status", methods=["POST"])
def cmd_status():
    return _command_enqueued("status", bridge.status())


@app.route("/api/cmd/add_reader", methods=["POST"])
def cmd_add_reader():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "add_reader",
        bridge.add_reader(d.get("addr", 0), d.get("scbk")),
    )


@app.route("/api/cmd/id", methods=["POST"])
def cmd_id():
    d = request.get_json(silent=True) or {}
    return _command_enqueued("id", bridge.request_id(d.get("index", 0)),
                             reader_index=d.get("index", 0))


@app.route("/api/cmd/cap", methods=["POST"])
def cmd_cap():
    d = request.get_json(silent=True) or {}
    return _command_enqueued("cap", bridge.request_cap(d.get("index", 0)),
                             reader_index=d.get("index", 0))


@app.route("/api/cmd/lstat", methods=["POST"])
def cmd_lstat():
    d = request.get_json(silent=True) or {}
    return _command_enqueued("lstat", bridge.request_lstat(d.get("index", 0)),
                             reader_index=d.get("index", 0))


@app.route("/api/cmd/istat", methods=["POST"])
def cmd_istat():
    d = request.get_json(silent=True) or {}
    return _command_enqueued("istat", bridge.request_istat(d.get("index", 0)),
                             reader_index=d.get("index", 0))


@app.route("/api/cmd/ostat", methods=["POST"])
def cmd_ostat():
    d = request.get_json(silent=True) or {}
    return _command_enqueued("ostat", bridge.request_ostat(d.get("index", 0)),
                             reader_index=d.get("index", 0))


@app.route("/api/cmd/sc", methods=["POST"])
def cmd_sc():
    d = request.get_json(silent=True) or {}
    reader_index = d.get("index", 0)
    return _command_with_reader_followup(
        "sc",
        lambda: bridge.secure_channel(reader_index),
        reader_index=reader_index,
        wait_seconds=2.5,
    )


@app.route("/api/cmd/comset", methods=["POST"])
def cmd_comset():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "comset",
        bridge.comset(d.get("index", 0), d.get("addr", 0), d.get("baud", 9600)),
        reader_index=d.get("index", 0),
    )


@app.route("/api/cmd/keyset", methods=["POST"])
def cmd_keyset():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "keyset",
        bridge.keyset(d.get("index", 0), d.get("key", "")),
        reader_index=d.get("index", 0),
    )


@app.route("/api/cmd/led", methods=["POST"])
def cmd_led():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "led",
        bridge.led(d.get("index", 0), d.get("params", "")),
        reader_index=d.get("index", 0),
    )


@app.route("/api/cmd/buzzer", methods=["POST"])
def cmd_buzzer():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "buzzer",
        bridge.buzzer(d.get("index", 0), d.get("tone", 1),
                      d.get("on", 5), d.get("off", 5), d.get("count", 3)),
        reader_index=d.get("index", 0),
    )


@app.route("/api/cmd/output", methods=["POST"])
def cmd_output():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "output",
        bridge.output(d.get("index", 0), d.get("output", 0),
                      d.get("code", 2), d.get("timer", 500)),
        reader_index=d.get("index", 0),
    )


@app.route("/api/cmd/relay", methods=["POST"])
def cmd_relay():
    d = request.get_json(silent=True) or {}
    return _command_enqueued(
        "relay",
        bridge.relay(d.get("index", 0), d.get("value", "1")),
        reader_index=d.get("index", 0),
    )


@app.route("/api/cmd/sensor", methods=["POST"])
def cmd_sensor():
    return _command_enqueued("sensor", bridge.sensor_query())


@app.route("/api/cmd/raw", methods=["POST"])
def cmd_raw():
    d = request.get_json(silent=True) or {}
    cmd = d.get("cmd", "").strip()
    if not cmd:
        return jsonify({"ok": False, "error": "empty command"})
    return _command_enqueued("raw", bridge.send(cmd))


# ── Users ─────────────────────────────────────────────────────
@app.route("/api/users", methods=["GET"])
def api_list_users():
    return jsonify(_jsonable(list_users(db)))


@app.route("/api/users", methods=["POST"])
def api_create_user():
    d = request.get_json(silent=True) or {}
    username = d.get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "error": "username required"}), 400
    try:
        allowed_readers = d.get("allowed_readers", [])
        if isinstance(allowed_readers, str):
            allowed_readers = [int(x.strip()) for x in allowed_readers.split(",") if x.strip()]
        r = create_user(db, username, d.get("full_name", ""),
                        d.get("role", "user"),
                        allowed_readers,
                        d.get("schedule", "24/7"))
        return jsonify({"ok": True, "id": str(r.inserted_id)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/users/<uid>", methods=["PUT"])
def api_update_user(uid):
    d = request.get_json(silent=True) or {}
    allowed = {"username", "full_name", "role", "active",
               "allowed_readers", "schedule"}
    fields = {k: v for k, v in d.items() if k in allowed}
    if "allowed_readers" in fields and isinstance(fields["allowed_readers"], str):
        fields["allowed_readers"] = [int(x.strip()) for x in fields["allowed_readers"].split(",") if x.strip()]
    update_user(db, uid, fields)
    return jsonify({"ok": True})


@app.route("/api/users/<uid>", methods=["DELETE"])
def api_deactivate_user(uid):
    deactivate_user(db, uid)
    return jsonify({"ok": True})


# ── Credentials ───────────────────────────────────────────────
@app.route("/api/credentials", methods=["GET"])
def api_list_credentials():
    uid = request.args.get("user_id")
    return jsonify(_jsonable(list_credentials(db, uid)))


@app.route("/api/credentials/<cid>", methods=["DELETE"])
def api_revoke_credential(cid):
    revoke_credential(db, cid)
    return jsonify({"ok": True})


@app.route("/api/enroll/card", methods=["POST"])
def api_enroll_card_manual():
    d = request.get_json(silent=True) or {}
    uid = d.get("user_id")
    card_hex = d.get("card_hex", "").strip().upper()
    if not uid or not card_hex:
        return jsonify({"ok": False, "error": "user_id and card_hex required"}), 400
    enroll_card(db, uid, card_hex, d.get("bits", 26),
                d.get("format", 1), d.get("reader", 0))
    return jsonify({"ok": True})


@app.route("/api/enroll/pin", methods=["POST"])
def api_enroll_pin_manual():
    d = request.get_json(silent=True) or {}
    uid = d.get("user_id")
    pin_hex = d.get("pin_hex", "").strip().upper()
    if not uid or not pin_hex:
        return jsonify({"ok": False, "error": "user_id and pin_hex required"}), 400
    enroll_pin(db, uid, pin_hex, d.get("reader", 0))
    return jsonify({"ok": True})


# ── Live enrollment (next swipe / keypad) ─────────────────────
@app.route("/api/enroll/start", methods=["POST"])
def api_enroll_start():
    d = request.get_json(silent=True) or {}
    uid = d.get("user_id")
    mode = d.get("mode", "card")
    if not uid:
        return jsonify({"ok": False}), 400
    _enroll_state["active"] = True
    _enroll_state["user_id"] = uid
    _enroll_state["mode"] = mode
    socketio.emit("enroll_waiting", {"mode": mode}, namespace="/")
    return jsonify({"ok": True})


@app.route("/api/enroll/cancel", methods=["POST"])
def api_enroll_cancel():
    _enroll_state["active"] = False
    return jsonify({"ok": True})


# ── Schedules ─────────────────────────────────────────────────
@app.route("/api/schedules", methods=["GET"])
def api_list_schedules():
    return jsonify(_jsonable(list_schedules(db)))


@app.route("/api/schedules", methods=["POST"])
def api_create_schedule():
    d = request.get_json(silent=True) or {}
    name = d.get("name", "").strip()
    periods = d.get("periods", [])
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    try:
        create_schedule(db, name, periods)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/schedules/<sid>", methods=["PUT"])
def api_update_schedule(sid):
    d = request.get_json(silent=True) or {}
    fields = {}
    if "name" in d:
        fields["name"] = d["name"]
    if "periods" in d:
        fields["periods"] = d["periods"]
    update_schedule(db, sid, fields)
    return jsonify({"ok": True})


@app.route("/api/schedules/<sid>", methods=["DELETE"])
def api_delete_schedule(sid):
    delete_schedule(db, sid)
    return jsonify({"ok": True})


# ── Events / Access log ──────────────────────────────────────
@app.route("/api/events")
@login_required
def api_events():
    t = request.args.get("type")
    limit = int(request.args.get("limit", 200))
    return jsonify(_jsonable(get_events(db, limit, t)))


@app.route("/api/access_log")
@login_required
def api_access_log():
    limit = int(request.args.get("limit", 200))
    return jsonify(_jsonable(get_access_log(db, limit)))


# ── Readers ───────────────────────────────────────────────────
@app.route("/api/readers")
@login_required
def api_readers():
    readers = []
    for reader in list_readers(db):
        enriched = _jsonable(reader)
        enriched.update(_reader_freshness(reader) or {})
        readers.append(enriched)
    return jsonify(readers)


# ── System logs ───────────────────────────────────────────────
@app.route("/api/system_logs")
@login_required
def api_system_logs():
    limit = int(request.args.get("limit", 500))
    level = request.args.get("level")
    return jsonify(_jsonable(get_system_logs(db, limit, level)))


# ── Debug mode ────────────────────────────────────────────────
@app.route("/api/cmd/debug", methods=["POST"])
def cmd_debug():
    d = request.get_json(silent=True) or {}
    on = d.get("on", True)
    return _command_enqueued("debug", bridge.debug_mode(on))


# ══════════════════════════════════════════════════════════════
#  SocketIO events
# ══════════════════════════════════════════════════════════════
@socketio.on("connect")
def ws_connect():
    if _current_panel_user() is None:
        disconnect()
        return False
    emit("bridge_status", {
        "connected": bridge.connected,
        "port": bridge.port,
        "tx": bridge.tx_count,
        "rx": bridge.rx_count,
    })
    emit("session", {"user": _panel_user_payload(_current_panel_user())})


@socketio.on("send_cmd")
def ws_send_cmd(data):
    user_doc = _current_panel_user()
    if user_doc is None:
        disconnect()
        return
    if user_doc.get("role") != "admin":
        emit("cmd_error", {"error": "admin access required"})
        return
    cmd = data.get("cmd", "") if isinstance(data, dict) else str(data)
    bridge.send(cmd)


# ══════════════════════════════════════════════════════════════
#  Firmware Update
# ══════════════════════════════════════════════════════════════

@app.route("/api/firmware/version")
def firmware_version():
    """Ask the MCU for its firmware version."""
    if not bridge.connected:
        return jsonify({"error": "Bridge not connected"}), 503
    bridge.send("FWVERSION")
    return jsonify({"ok": True, "note": "Version will arrive via event"})


@app.route("/api/firmware/upload", methods=["POST"])
def firmware_upload():
    """Upload a .bin file and flash it to the MCU via the bootloader."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename or not f.filename.endswith(".bin"):
        return jsonify({"error": "Only .bin files accepted"}), 400

    import tempfile
    import time as _time
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    try:
        f.save(tmp.name)
        tmp.close()

        from flasher import flash_firmware, find_port, BL_PID

        def progress(pct, msg):
            socketio.emit("fw_progress", {"percent": pct, "message": msg},
                          namespace="/")

        # If bootloader is already running (e.g. retry), skip the reboot step
        if find_port(BL_PID):
            progress(0, "Bootloader already active")
        else:
            # Send BOOTLOADER command via the existing bridge connection,
            # then disconnect.  This is more reliable than opening a second
            # serial connection from the flasher.
            if bridge.connected:
                progress(0, "Sending BOOTLOADER command...")
                bridge.send("BOOTLOADER")
                _time.sleep(0.2)          # let MCU process + start reset
            bridge.disconnect()
            _time.sleep(0.5)              # let Windows release the old COM port

        flash_firmware(tmp.name, reboot_from_app=False, progress_cb=progress)

        # Reconnect bridge after update — retry for up to 10s
        progress(95, "Waiting for MCU to boot...")
        for attempt in range(10):
            _time.sleep(1)
            if bridge.connect(retries=1):
                progress(100, "Reconnected to bridge")
                break
        else:
            log.warning("Could not reconnect after firmware update")

        log_system(db, "info", "firmware", f"Firmware updated: {f.filename}")
        return jsonify({"ok": True})
    except Exception as e:
        log.exception("Firmware update failed")
        log_system(db, "error", "firmware", str(e))
        # Try to reconnect (works if MCU is back in app mode)
        for _ in range(10):
            _time.sleep(1)
            if bridge.connect(retries=1):
                break
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp.name)


# ══════════════════════════════════════════════════════════════
#  Startup
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("Starting OSDP Access Control Panel")
    log_system(db, "info", "app", "Access Control Panel starting")

    # Start event worker thread — processes events from the queue
    # so the serial reader thread never blocks on DB/SocketIO
    def _event_worker():
        while True:
            try:
                ev = _event_queue.get()
                _handle_event(ev)
            except Exception as e:
                log.error("Event worker error: %s", e)

    _worker = threading.Thread(target=_event_worker, daemon=True)
    _worker.start()

    bridge.connect()
    if bridge.connected:
        log.info("Bridge connected on %s — requesting status", bridge.port)
        log_system(db, "info", "bridge", f"Connected on {bridge.port}")
        bridge.ping()
        bridge.status()
    else:
        log.warning("Blue Pill not found — connect manually from the UI")
        log_system(db, "warn", "bridge", "Blue Pill not found at startup")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
