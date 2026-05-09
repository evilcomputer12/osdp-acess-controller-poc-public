# Raspberry Pi Deployment

## Supported Approach

The supported Raspberry Pi path in this repo is:

- Python app runs natively in a local virtual environment
- frontend is built locally into `static/dist`
- MongoDB runs in Docker on the Pi

This is the default because MongoDB packaging on ARM boards is less predictable than using the official Docker image.

The setup script defaults to `mongo:4.4.18` because many Raspberry Pi boards do not expose the ARMv8.2 features required by MongoDB 5+ and 7+ images. If your Pi is new enough, you can override the image at runtime with `MONGO_IMAGE=mongo:<tag> ./scripts/setup_raspberry_pi.sh`.

## One-Command Installer

Run:

```bash
chmod +x scripts/setup_raspberry_pi.sh
./scripts/setup_raspberry_pi.sh
```

The installer performs these actions:

1. installs base Linux packages, Python, Node.js, and Docker
2. adds the current user to `docker` and `dialout`
3. creates `.venv` and installs Python dependencies
4. builds the frontend bundle
5. starts MongoDB in Docker on `127.0.0.1:27017`
6. asks whether to restore a backup or initialize a fresh database
7. checks Blue Pill USB visibility
8. installs a `systemd` service for the app and offers to start it

If an incompatible MongoDB image is already present for `osdp-access-mongo`, the script recreates the container with the configured `MONGO_IMAGE`.

## USB Behavior on Pi

USB should work on Raspberry Pi because [bridge.py](../bridge.py) uses pySerial enumeration instead of Windows-specific COM assumptions. The practical requirements are:

- the Blue Pill must enumerate with VID:PID `0483:5740`
- the Linux user must be in the `dialout` group
- the serial port must not be held by another process

Check it with:

```bash
.venv/bin/python scripts/check_usb_bridge.py
```

## Data Choices During Setup

The setup script will ask you to choose one of:

- restore from an existing backup directory
- initialize a fresh empty database with default indexes and schedules
- skip database work for now

If you want to restore a sample backup, copy the desired backup folder under `backups/` before running the script or enter a custom path when prompted.

## Service Model

The setup script writes `/etc/systemd/system/osdp-access-panel.service` using the current user and repo path. After that you can manage it with:

```bash
sudo systemctl status osdp-access-panel
sudo systemctl restart osdp-access-panel
sudo journalctl -u osdp-access-panel -f
```