# OSDP Access Controller PoC

Project GitHub repository: https://github.com/evilcomputer12/osdp-acess-controller-poc-public

This project is a proof-of-concept OSDP access controller built around a Flask and Socket.IO backend, a React frontend, a serial bridge to a Blue Pill OSDP controller, STM32 bridge firmware and bootloader source trees, and a MongoDB data store. It manages readers, users, credentials, enrollment, access decisions, firmware updates, and live event monitoring.

This repo intentionally excludes companion folders that are out of scope for this repository snapshot:

- `eps32-osdp-bridge`
- `flutter osdp app a`

## What It Does

- Detects and connects to the Blue Pill bridge over USB by VID:PID `0483:5740`
- Sends OSDP-oriented control commands such as `STATUS`, `SC`, `LED`, `BUZ`, `RELAY`, `OUT`, `KEYSET`, and `COMSET`
- Stores users, credentials, schedules, readers, events, access logs, and system logs in MongoDB
- Serves a React admin UI from Flask after building the frontend into `static/dist`
- Supports backup and restore of MongoDB using repo-local Python tools

## Architecture

- Backend: Flask + Flask-SocketIO in [app.py](app.py)
- Serial bridge: Blue Pill USB bridge in [bridge.py](bridge.py)
- MCU firmware: STM32 bridge firmware in [osdp-controller/platformio.ini](osdp-controller/platformio.ini)
- MCU bootloader: STM32 USB bootloader in [bootloader/platformio.ini](bootloader/platformio.ini)
- Firmware packaging: Windows helper in [build-firmware.ps1](build-firmware.ps1)
- Firmware flashing: ST-Link helper in [flash-stlink.ps1](flash-stlink.ps1)
- Data model: MongoDB helpers in [models.py](models.py)
- Frontend: Vite + React in [frontend/package.json](frontend/package.json)
- Backup/restore: [backup_mongo.py](backup_mongo.py) and [restore_mongo.py](restore_mongo.py)
- Interactive hardware check: [interactive_osdp_test.py](interactive_osdp_test.py)

## Repository Layout

- [app.py](app.py): backend entrypoint and REST/Socket.IO API
- [bridge.py](bridge.py): serial transport, command helpers, and event parser
- [models.py](models.py): MongoDB schema helpers and access policy logic
- [osdp-controller/platformio.ini](osdp-controller/platformio.ini): PlatformIO project for the STM32 OSDP bridge firmware
- [osdp-controller/src/main.cpp](osdp-controller/src/main.cpp): main MCU bridge application entrypoint
- [bootloader/platformio.ini](bootloader/platformio.ini): PlatformIO project for the STM32 USB bootloader
- [bootloader/src/main.cpp](bootloader/src/main.cpp): bootloader application entrypoint
- [build-firmware.ps1](build-firmware.ps1): builds the STM32 app and exports a timestamped `.bin` into `firmware`
- [flash-stlink.ps1](flash-stlink.ps1): builds and flashes the bootloader and app through ST-Link
- [share-ngrok.ps1](share-ngrok.ps1): starts an `ngrok` tunnel for the local Flask panel and prints the public URL
- [firmware/osdp-bridge-20260310-032700.bin](firmware/osdp-bridge-20260310-032700.bin): packaged firmware image for web-panel updates
- [frontend/package.json](frontend/package.json): frontend dependencies and build scripts
- [run.sh](run.sh): Linux and Raspberry Pi friendly local runner
- [backup_mongo.py](backup_mongo.py): database export to Extended JSON
- [restore_mongo.py](restore_mongo.py): database restore from Extended JSON
- [scripts/setup_raspberry_pi.sh](scripts/setup_raspberry_pi.sh): end-to-end Raspberry Pi installer
- [scripts/check_usb_bridge.py](scripts/check_usb_bridge.py): USB visibility check for the Blue Pill
- [scripts/init_db.py](scripts/init_db.py): initialize a fresh MongoDB database
- [docs/PROTOCOL.md](docs/PROTOCOL.md): OSDP and project protocol explainer
- [docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md): Raspberry Pi deployment notes

## Quick Start

### Windows

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
.venv\Scripts\python app.py
```

### Linux or Raspberry Pi

```bash
chmod +x run.sh
./run.sh
```

`run.sh` now creates a local virtual environment automatically, installs Python dependencies into `.venv`, builds the frontend, and starts Flask.

## Web Panel Login

The panel now uses two seeded web accounts stored in the `panel_users` collection:

- `admin` / `osdp`: full control of bridge connect/disconnect, reader commands, enrollment, schedules, firmware upload, and terminal access
- `demo` / `db2`: read-only viewer access for dashboard, live activity, events, access log, comms monitor, and system logs

For better operational security, the login page no longer exposes preset buttons or inline default credentials. Admins can manage seeded panel passwords from the Users page by either choosing a new password or resetting a seeded account back to its repository default.

The `demo` account is intended for DB2 report demonstrations and teacher review, not for configuration work.

## Public Sharing with ngrok

If you want to expose the panel temporarily over the internet for a demo, start the Flask app locally and then run:

```powershell
.\share-ngrok.ps1
```

The script starts `ngrok http 5000`, waits for the local ngrok API on `http://127.0.0.1:4040`, and prints the public HTTPS URL. You can then sign in with `demo / db2` for a safe read-only walkthrough.

If you rotated the seeded panel passwords earlier, reset them from the Users page or with `osdpAccess.resetPanelUserPassword('demo')` before you start the public demo.

## Firmware Build and Flash

Build a web-update firmware package on Windows:

```powershell
.\build-firmware.ps1
```

Flash the bootloader and application over ST-Link:

```powershell
.\flash-stlink.ps1
```

Use `.\flash-stlink.ps1 -BootloaderOnly` or `.\flash-stlink.ps1 -AppOnly` when you only want one stage.

## MongoDB Backup and Restore

Create a backup:

```bash
.venv/bin/python backup_mongo.py
```

Restore a backup:

```bash
.venv/bin/python restore_mongo.py backups/mongodb_osdp_access_YYYYMMDD_HHMMSS
```

Backups are stored as Extended JSON so `ObjectId` and BSON dates survive round-trips.

## Raspberry Pi Deployment

Use the guided installer:

```bash
chmod +x scripts/setup_raspberry_pi.sh
./scripts/setup_raspberry_pi.sh
```

The installer will:

- install Python, Node.js, Docker, and system dependencies
- run MongoDB in Docker on `localhost:27017` using `mongo:4.4.18` by default for older Raspberry Pi CPUs
- build the frontend
- ask whether to restore a backup or initialize a fresh database
- check Blue Pill USB visibility
- install and optionally start a `systemd` service for the app

If your board supports a newer MongoDB image, you can override the default with `MONGO_IMAGE=mongo:<tag> ./scripts/setup_raspberry_pi.sh`.

Detailed notes are in [docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md).

## USB Support on Raspberry Pi

USB bridge support should work on Raspberry Pi Linux because [bridge.py](bridge.py) uses `serial.tools.list_ports.comports()` and matches the Blue Pill by VID:PID instead of a Windows-only COM naming scheme. The main operational requirement is Linux serial permission membership in `dialout`.

Verify USB visibility with:

```bash
.venv/bin/python scripts/check_usb_bridge.py
```

## Project GitHub

The project GitHub repository is:

https://github.com/evilcomputer12/osdp-acess-controller-poc-public

## Additional Docs

- [docs/PROTOCOL.md](docs/PROTOCOL.md)
- [docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md)
