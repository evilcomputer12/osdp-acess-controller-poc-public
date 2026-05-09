"""
MongoDB models and helpers for the OSDP Access Control Panel.
Collections: users, credentials, events, readers, access_log, schedules
"""

from datetime import datetime, timezone
from pymongo import MongoClient, DESCENDING

DB_NAME = "osdp_access"

# ── Default schedule: 24/7 access ─────────────────────────────
DEFAULT_SCHEDULE = {
    "name": "24/7",
    "periods": [
        {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}
    ],
}


def get_db(uri="mongodb://localhost:27017"):
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    db = client[DB_NAME]
    _ensure_indexes(db)
    return db


def _ensure_indexes(db):
    db.users.create_index("username", unique=True)
    db.credentials.create_index("user_id")
    db.credentials.create_index("card_hex")
    db.events.create_index([("ts", DESCENDING)])
    db.access_log.create_index([("ts", DESCENDING)])
    db.readers.create_index("index", unique=True)
    db.schedules.create_index("name", unique=True)
    db.system_logs.create_index([("ts", DESCENDING)])
    # Seed default schedule if missing
    if db.schedules.count_documents({"name": "24/7"}) == 0:
        db.schedules.insert_one({
            "name": "24/7",
            "periods": [
                {"days": [0, 1, 2, 3, 4, 5, 6],
                 "start": "00:00", "end": "23:59"}
            ],
        })
    if db.schedules.count_documents({"name": "Weekdays 8-18"}) == 0:
        db.schedules.insert_one({
            "name": "Weekdays 8-18",
            "periods": [
                {"days": [0, 1, 2, 3, 4],
                 "start": "08:00", "end": "18:00"}
            ],
        })


# ── Users ─────────────────────────────────────────────────────
def create_user(db, username, full_name="", role="user",
                allowed_readers=None, schedule_name="24/7"):
    doc = {
        "username": username,
        "full_name": full_name,
        "role": role,
        "active": True,
        "allowed_readers": allowed_readers if allowed_readers is not None else [],
        "schedule": schedule_name,
        "created": datetime.now(timezone.utc),
    }
    return db.users.insert_one(doc)


def list_users(db, active_only=True):
    filt = {"active": True} if active_only else {}
    return list(db.users.find(filt).sort("username", 1))


def get_user(db, user_id):
    from bson import ObjectId
    return db.users.find_one({"_id": ObjectId(user_id)})


def update_user(db, user_id, fields):
    from bson import ObjectId
    return db.users.update_one({"_id": ObjectId(user_id)}, {"$set": fields})


def deactivate_user(db, user_id):
    return update_user(db, user_id, {"active": False})


# ── Credentials (cards / PINs) ────────────────────────────────
def enroll_card(db, user_id, card_hex, bits, fmt, reader_idx=0):
    from bson import ObjectId
    doc = {
        "user_id": ObjectId(user_id),
        "type": "card",
        "card_hex": card_hex.upper(),
        "card_dec": str(int(card_hex, 16)),
        "bits": bits,
        "format": fmt,
        "reader": reader_idx,
        "enrolled": datetime.now(timezone.utc),
        "active": True,
    }
    return db.credentials.insert_one(doc)


def enroll_pin(db, user_id, pin_hex, reader_idx=0):
    from bson import ObjectId
    doc = {
        "user_id": ObjectId(user_id),
        "type": "pin",
        "pin_hex": pin_hex.upper(),
        "reader": reader_idx,
        "enrolled": datetime.now(timezone.utc),
        "active": True,
    }
    return db.credentials.insert_one(doc)


def find_credential_by_card(db, card_hex):
    return db.credentials.find_one(
        {"card_hex": card_hex.upper(), "type": "card", "active": True})


def find_credential_by_pin(db, pin_hex):
    return db.credentials.find_one(
        {"pin_hex": pin_hex.upper(), "type": "pin", "active": True})


def list_credentials(db, user_id=None):
    from bson import ObjectId
    filt = {"active": True}
    if user_id:
        filt["user_id"] = ObjectId(user_id)
    return list(db.credentials.find(filt).sort("enrolled", DESCENDING))


def revoke_credential(db, cred_id):
    from bson import ObjectId
    return db.credentials.update_one(
        {"_id": ObjectId(cred_id)}, {"$set": {"active": False}})


# ── Schedules ─────────────────────────────────────────────────
def list_schedules(db):
    return list(db.schedules.find())


def get_schedule(db, name):
    return db.schedules.find_one({"name": name})


def create_schedule(db, name, periods):
    return db.schedules.insert_one({"name": name, "periods": periods})


def update_schedule(db, sched_id, fields):
    from bson import ObjectId
    return db.schedules.update_one(
        {"_id": ObjectId(sched_id)}, {"$set": fields})


def delete_schedule(db, sched_id):
    from bson import ObjectId
    return db.schedules.delete_one({"_id": ObjectId(sched_id)})


def check_schedule(db, schedule_name, now=None):
    """Return True if current time falls within the schedule."""
    if now is None:
        now = datetime.now()
    sched = db.schedules.find_one({"name": schedule_name})
    if not sched:
        return True  # no schedule = always allowed
    dow = now.weekday()  # 0=Monday
    cur_time = now.strftime("%H:%M")
    for period in sched.get("periods", []):
        if dow in period.get("days", []):
            if period.get("start", "00:00") <= cur_time <= period.get("end", "23:59"):
                return True
    return False


def check_reader_access(user, reader_idx):
    """Return True if user is allowed on this reader."""
    allowed = user.get("allowed_readers")
    if not allowed:
        return True  # empty list = all readers
    return reader_idx in allowed


# ── Events (raw MCU events log) ──────────────────────────────
def log_event(db, event_dict):
    event_dict["logged"] = datetime.now(timezone.utc)
    return db.events.insert_one(event_dict)


def get_events(db, limit=200, event_type=None):
    filt = {}
    if event_type:
        filt["type"] = event_type
    return list(db.events.find(filt).sort("ts", DESCENDING).limit(limit))


# ── Access log (card/pin match results) ──────────────────────
def log_access(db, *, card_hex=None, pin_hex=None, user_id=None,
               username=None, granted=False, reader=0, reason=""):
    doc = {
        "ts": datetime.now(timezone.utc),
        "card_hex": card_hex,
        "pin_hex": pin_hex,
        "user_id": user_id,
        "username": username,
        "granted": granted,
        "reader": reader,
        "reason": reason,
    }
    return db.access_log.insert_one(doc)


def get_access_log(db, limit=200):
    return list(db.access_log.find().sort("ts", DESCENDING).limit(limit))


# ── Readers ───────────────────────────────────────────────────
def upsert_reader(db, index, fields):
    return db.readers.update_one(
        {"index": index}, {"$set": fields}, upsert=True)


def list_readers(db):
    return list(db.readers.find().sort("index", 1))


# ── System logs (verbose comms / diagnostics) ────────────────
def log_system(db, level, source, message, data=None):
    doc = {
        "ts": datetime.now(timezone.utc),
        "level": level,
        "source": source,
        "message": message,
    }
    if data:
        doc["data"] = data
    return db.system_logs.insert_one(doc)


def get_system_logs(db, limit=500, level=None):
    filt = {}
    if level:
        filt["level"] = level
    return list(db.system_logs.find(filt).sort("ts", DESCENDING).limit(limit))
