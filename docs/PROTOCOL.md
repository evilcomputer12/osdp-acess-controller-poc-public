# OSDP Protocol and Project Flow

## OSDP in One View

OSDP, the Open Supervised Device Protocol, is a serial protocol used between an access control panel and peripheral devices such as readers, keypads, and door interfaces. In this project:

- the controller side is the Flask app plus the Blue Pill bridge
- the peripheral device side is one or more OSDP readers
- the serial bridge exposes a line-oriented command interface that the backend speaks to over USB

This project does not generate raw OSDP frames in Python. The Blue Pill firmware does that. Python sends higher-level textual commands like `STATUS`, `SC 0`, or `LED 0 ...`, then parses back line-oriented events such as `!PD`, `!CARD`, `!KEYPAD`, and `!PDID`.

## Roles in This Project

### Backend

[app.py](../app.py) owns:

- REST API endpoints for UI actions
- Socket.IO fan-out to the frontend
- access decision logic for cards and PINs
- reader state persistence in MongoDB

### Bridge

[bridge.py](../bridge.py) owns:

- USB port discovery using VID:PID `0483:5740`
- serial command writes
- background receive loop
- parsing the Blue Pill textual event stream

### Data Store

[models.py](../models.py) owns:

- user and credential records
- schedule definitions
- raw event history
- access log history
- reader state documents
- system logs

## Command Flow

Typical command path:

1. The frontend calls an API endpoint such as `/api/cmd/sc`.
2. [app.py](../app.py) validates the request and calls a bridge helper.
3. [bridge.py](../bridge.py) writes a textual command like `SC 0` to the serial bridge.
4. The Blue Pill firmware talks real OSDP to the physical reader.
5. The Blue Pill sends text events back over USB.
6. [bridge.py](../bridge.py) parses those events.
7. [app.py](../app.py) updates MongoDB and emits Socket.IO events to the UI.

## Parsed Event Types

The backend currently understands these important event families:

- `!CARD`: card presentation
- `!KEYPAD`: keypad digits or control keys
- `!STATE`: reader state transition
- `!PD`: peripheral status snapshot, including secure-channel state
- `!PDID`: reader identification
- `!PDCAP`: capabilities
- `!LSTAT`, `!ISTAT`, `!OSTAT`: device state details
- `!SENSOR`, `!DOOR`, `!RELAY`, `!COM`: I/O and configuration events
- `PONG`, `OK`, `ERR:`: bridge-level status

## Secure Channel

Secure channel setup is initiated by `SC <reader_index>`. The backend now reports two facts separately:

- whether the command was successfully queued to the bridge
- whether the reader actually reported `sc=1` afterward

That matters because a serial write alone does not prove the OSDP secure channel completed. Real success depends on the reader entering secure mode with a matching SCBK and healthy transport.

## Card and PIN Flow

### Card

1. Reader sends `!CARD`.
2. Backend checks whether live enrollment is active.
3. If enrolling, the card is saved as a credential.
4. Otherwise, the backend looks up the credential in MongoDB.
5. If found, it checks user active state, reader access, and schedule.
6. Grant or deny feedback is sent back to the reader.

### PIN

1. Reader sends `!KEYPAD` bytes.
2. Backend accumulates digits until `#` or timeout.
3. Enrollment or access lookup then follows the same policy path as card access.

## Reader State Model

Reader documents in MongoDB include:

- `index`
- `addr`
- `state`
- `sc`
- `tamper`
- `power`
- `vendor`
- `model`
- `serial`
- `firmware`
- `last_seen`

The API also computes freshness metadata so the UI can distinguish live readers from stale records.

## Why the Blue Pill USB Bridge Works on Raspberry Pi

The USB path is platform-neutral because the Python code relies on pySerial port enumeration and VID:PID matching. On Linux, the main constraint is permission to open the serial device, usually handled by adding the runtime user to `dialout`.