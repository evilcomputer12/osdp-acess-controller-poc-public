# Mongosh Script Walkthrough

## Why This Matters

Now for the main interest of this class: a database implementation expressed directly in native MongoDB shell syntax. Instead of describing MongoDB concepts only at the application level, this walkthrough shows the project as a pure `mongosh` solution.

The two files behind this walkthrough are:

1. [scripts/osdp_access_mongo.js](../scripts/osdp_access_mongo.js) - the reusable MongoDB helper library
2. [scripts/osdp_access_mongo_demo.js](../scripts/osdp_access_mongo_demo.js) - the end-to-end demonstration script

The library is modeled directly in Mongo shell operations such as:

1. `createCollection()` for explicit collection creation
2. `createIndex()` for uniqueness and read performance
3. `insertOne()` for creates
4. `find()` and `findOne()` for reads
5. `updateOne()` for updates and upserts
6. `deleteOne()` and `deleteMany()` for deletes
7. `countDocuments()` for database summaries

The goal is to show that the whole database side of the project can be understood and demonstrated without relying on the Python backend.

## What The Library Implements

The helper library provides all core database operations used by the project:

1. collection creation and index setup
2. default schedule and web-panel account seeding
3. panel user listing for the Flask login layer
4. user CRUD
5. credential CRUD for cards and PINs
6. schedule CRUD
7. reader state upserts and reads
8. raw event logging and queries
9. access log logging and queries
10. system log logging and queries
11. access evaluation helpers for card and PIN workflows
12. reset and summary helpers

One important addition is that the library now supports a factory function:

```javascript
const demo = createOsdpAccessApi("osdp_access_demo")
```

That allows the same logic to be run safely against a separate demo database, which is exactly what the demonstration script uses.

## How To Run It

### Load the library only

```bash
mongosh mongodb://localhost:27017/osdp_access
load("scripts/osdp_access_mongo.js")
osdpAccess.init()
osdpAccess.help()
```

### Run the full demo

```bash
mongosh mongodb://localhost:27017 --quiet --file scripts/osdp_access_mongo.js --file scripts/osdp_access_mongo_demo.js
```

The full raw transcript from the real run is stored in [docs/MONGO_SCRIPT_DEMO_OUTPUT.txt](MONGO_SCRIPT_DEMO_OUTPUT.txt).

## Script Design In Words

### 1. Initialization Layer

The library starts by defining the target collection set, the two default schedules used by the access-control logic, and the fixed `panel_users` needed by the web login flow. The `init()` function creates collections if needed, creates indexes, and seeds schedules plus the demo/admin panel accounts. This mirrors the role of `_ensure_indexes()` from the Python backend, but it is now expressed directly in `mongosh`.

### 2. Panel User Layer

The `panel_users` collection stores the fixed web-panel accounts used by the Flask login screen. In this project they are seeded automatically as `admin` and `demo`, with roles `admin` and `viewer`. This collection is separate from access-control `users` because it models UI operators rather than cardholders.

### 3. User Layer

The user API models a person or operator with `username`, `full_name`, `role`, `active`, `allowed_readers`, `schedule`, and `created`. The design uses a soft-delete style through `deactivateUser()` and also exposes `deleteUser()` for hard deletion.

### 4. Credential Layer

Card and PIN credentials are stored in the `credentials` collection and reference users through `user_id`. The library normalizes card and PIN values to uppercase and derives `card_dec` from `card_hex` so the data matches the backend schema.

### 5. Schedule Layer

Schedules are stored as named documents with embedded `periods`. The helper functions demonstrate create, read, update, delete, and also direct time evaluation through `checkSchedule()`.

### 6. Reader Layer

The `readers` collection is not append-only. It stores the latest known snapshot for each reader. That is why the library uses `upsertReader()` instead of inserting a new document every time state changes.

### 7. Logging Layer

The database keeps three different categories of operational data separate:

1. `events` for raw or normalized MCU and bridge events
2. `access_log` for final access decisions
3. `system_logs` for diagnostics and troubleshooting messages

That separation is visible in the library design and also in the demo output.

### 8. Access Evaluation Layer

The most interesting part from an access-control perspective is the evaluation logic. The script shows that an access decision is not just a credential lookup. It also depends on:

1. whether the user exists
2. whether the user is active
3. whether the user is allowed on the specific reader
4. whether the assigned schedule currently allows access

The `accessByCard()` and `accessByPin()` helpers execute the full lookup-and-log flow and then write the result into `access_log`.

## Demo Walkthrough With Real Output

The following sections describe what each demo step does and show the actual output produced by the live `mongosh` run.

### Step 1: Reset and Initialize Demo Database

This step proves that the demo database starts clean and that initialization creates the expected collections and default schedules.

```text
=== 1. Reset and initialize demo database ===
-- resetDatabase({ dropDatabase: true })
{
  "db": "osdp_access_demo",
  "collections": [
    "access_log",
    "credentials",
    "events",
    "panel_users",
    "readers",
    "schedules",
    "system_logs",
    "users"
  ],
  "counts": {
    "users": 0,
    "panel_users": 2,
    "credentials": 0,
    "events": 0,
    "access_log": 0,
    "readers": 0,
    "schedules": 2,
    "system_logs": 0
  }
}
```

The `panel_users` count is `2` immediately after initialization because the script seeds the fixed web accounts used by the Flask admin panel: `admin` and `demo`.

### Step 2: Create Users

This step inserts three demo users and then reads them back.

```text
=== 2. Create users ===
-- users after create
[
  {
    "username": "martin",
    "full_name": "Martin Velichkovski",
    "role": "admin",
    "active": true,
    "allowed_readers": [
      0
    ],
    "schedule": "24/7"
  },
  {
    "username": "temp-delete",
    "full_name": "Temporary Demo User",
    "role": "user",
    "active": true,
    "allowed_readers": [],
    "schedule": "24/7"
  },
  {
    "username": "visitor",
    "full_name": "Weekend Visitor",
    "role": "user",
    "active": true,
    "allowed_readers": [
      1
    ],
    "schedule": "Weekdays 8-18"
  }
]
```

### Step 3: Read and Update Users

This step demonstrates both read operations and a soft-delete style update.

```text
=== 3. Read and update users ===
-- getUserByUsername("martin")
{
  "username": "martin",
  "full_name": "Martin Velichkovski",
  "role": "admin",
  "active": true
}
-- updateUser(martin)
{
  "acknowledged": true,
  "matchedCount": 1,
  "modifiedCount": 1
}
-- getUserById(martinId)
{
  "username": "martin",
  "full_name": "Martin V.",
  "allowed_readers": [
    0,
    2
  ]
}
-- deactivateUser(tempUserId)
{
  "acknowledged": true,
  "matchedCount": 1,
  "modifiedCount": 1
}
```

### Step 4: Credential CRUD

This step creates card and PIN credentials, queries them, updates one, revokes another, and then deletes it.

```text
=== 4. Create, read, update, revoke, and delete credentials ===
-- findCredentialByCard("04A1B2C3D4")
{
  "type": "card",
  "card_hex": "04A1B2C3D4",
  "card_dec": "19892716500",
  "bits": 34,
  "format": 0,
  "reader": 0,
  "active": true
}
-- updateCredential(martinCardId)
{
  "acknowledged": true,
  "matchedCount": 1,
  "modifiedCount": 1
}
-- getCredentialById(martinCardId)
{
  "type": "card",
  "card_hex": "04A1B2C3D4",
  "bits": 37,
  "reader": 2,
  "active": true
}
-- revokeCredential(tempCredentialId)
{
  "acknowledged": true,
  "matchedCount": 1,
  "modifiedCount": 1
}
-- deleteCredential(tempCredentialId)
{
  "acknowledged": true,
  "deletedCount": 1
}
```

### Step 5: Schedule CRUD and Time Evaluation

This step shows schedule creation, schedule update, direct schedule evaluation, and deletion.

```text
=== 5. Create, read, update, delete schedules ===
-- checkSchedule("Weekdays 8-18", mondayMorning)
{
  "schedule": "Weekdays 8-18",
  "allowed": true
}
-- checkSchedule("Weekdays 8-18", saturdayNight)
{
  "schedule": "Weekdays 8-18",
  "allowed": false
}
-- deleteSchedule(deleteMeScheduleId)
{
  "acknowledged": true,
  "deletedCount": 1
}
```

### Step 6: Reader Snapshot Management

This step demonstrates why readers are stored as current state snapshots rather than append-only log rows.

```text
=== 6. Upsert, read, list, and delete readers ===
-- upsertReader(0, ...)
{
  "acknowledged": true,
  "matchedCount": 0,
  "modifiedCount": 0,
  "upsertedCount": 1
}
-- getReader(0)
{
  "index": 0,
  "addr": 0,
  "state": "ONLINE",
  "sc": 1,
  "serial": "21AA0145",
  "firmware": "2.83.0"
}
-- deleteReader(1)
{
  "acknowledged": true,
  "deletedCount": 1
}
```

### Step 7: Event Logging and Cleanup

This step logs raw events, reads them back, and deletes a test event.

```text
=== 7. Log, query, and delete events ===
-- getEvents({ limit: 10 })
[
  {
    "type": "card",
    "reader": 0,
    "hex": "04A1B2C3D4",
    "raw": "!CARD demo"
  },
  {
    "type": "pd_status",
    "reader": 0,
    "state": "ONLINE",
    "raw": "!PD 0 ONLINE"
  },
  {
    "type": "demo_delete",
    "reader": 9,
    "raw": "!DEMO DELETE"
  }
]
-- deleteEvents({ type: "demo_delete" })
{
  "acknowledged": true,
  "deletedCount": 1
}
```

### Step 8: System Log CRUD

This step shows that diagnostic logs are handled separately from raw device events and access decisions.

```text
=== 8. Log, query, and delete system logs ===
-- getSystemLogs({ limit: 10 })
[
  {
    "level": "info",
    "source": "demo-cleanup",
    "message": "This log will be deleted"
  },
  {
    "level": "warn",
    "source": "demo",
    "message": "Reader 1 was removed during cleanup"
  },
  {
    "level": "info",
    "source": "demo",
    "message": "Demo script started"
  }
]
-- deleteSystemLogs({ source: "demo-cleanup" })
{
  "acknowledged": true,
  "deletedCount": 1
}
```

### Step 9: Access Evaluation Helpers

This step is important conceptually because it shows that access depends on more than a credential lookup.

```text
=== 9. Access evaluation helpers ===
-- evaluateUserAccess(martin, reader 0, mondayMorning)
{
  "granted": true,
  "reason": "allowed"
}
-- evaluateUserAccess(visitor, reader 0, mondayMorning)
{
  "granted": false,
  "reason": "reader not allowed"
}
-- evaluateUserAccess(visitor, reader 1, saturdayNight)
{
  "granted": false,
  "reason": "outside schedule"
}
```

### Step 10: Full Access Workflows and Audit Trail

This step runs the complete `accessByCard()` and `accessByPin()` workflows and then reads the resulting audit log.

```text
=== 10. Access workflows and access log ===
-- accessByCard(martin card)
{
  "granted": true,
  "reason": "allowed"
}
-- accessByCard(unknown card)
{
  "granted": false,
  "reason": "unknown card"
}
-- accessByPin(visitor pin outside schedule)
{
  "granted": false,
  "reason": "outside schedule"
}
-- getAccessLog({ limit: 10 })
[
  {
    "card_hex": "DEADBEEF",
    "granted": false,
    "reader": 99,
    "reason": "manual demo delete"
  },
  {
    "pin_hex": "BEEF",
    "username": "visitor",
    "granted": false,
    "reason": "outside schedule"
  },
  {
    "card_hex": "FFFFFFFF",
    "granted": false,
    "reason": "unknown card"
  },
  {
    "card_hex": "04A1B2C3D4",
    "username": "martin",
    "granted": true,
    "reason": "allowed"
  }
]
```

### Step 11: Cleanup and Final Summary

This step removes the temporary user and prints the final database counts.

```text
=== 11. Delete temporary user and final summary ===
-- deleteUser(tempUserId)
{
  "acknowledged": true,
  "deletedCount": 1
}
-- final summary
{
  "db": "osdp_access_demo",
  "counts": {
    "users": 2,
    "credentials": 3,
    "events": 2,
    "access_log": 3,
    "readers": 1,
    "schedules": 3,
    "system_logs": 2
  }
}
```

## What This Demonstration Shows

From a class perspective, the important point is that the complete database workflow can now be shown directly in MongoDB shell syntax, without needing Flask, Python, or the frontend.

The demonstration proves that the MongoDB design supports:

1. creation of the access-control schema and indexes
2. real CRUD operations on administrative entities
3. logging of heterogeneous runtime events
4. separation between raw logs, access decisions, and diagnostics
5. schedule-aware and reader-aware access decisions
6. repeatable testing through a dedicated demo database

## Files Produced

1. [scripts/osdp_access_mongo.js](../scripts/osdp_access_mongo.js)
2. [scripts/osdp_access_mongo_demo.js](../scripts/osdp_access_mongo_demo.js)
3. [docs/MONGO_SCRIPT_DEMO_OUTPUT.txt](MONGO_SCRIPT_DEMO_OUTPUT.txt)

These three files together give you:

1. the reusable Mongo-only implementation
2. the live demonstration script
3. the captured shell output for documentation and submission support