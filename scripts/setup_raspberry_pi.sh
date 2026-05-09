#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${USER}"
APP_GROUP="$(id -gn)"
MONGO_URI="${MONGO_URI:-mongodb://localhost:27017}"
MONGO_CONTAINER="osdp-access-mongo"
MONGO_DATA_DIR="${HOME}/osdp-access-mongo"
MONGO_IMAGE="${MONGO_IMAGE:-mongo:4.4.18}"
SERVICE_NAME="osdp-access-panel"

log() {
    printf '\n[%s] %s\n' "$1" "$2"
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-Y}"
    local reply

    if [ "$default" = "Y" ]; then
        read -r -p "$prompt [Y/n]: " reply
        reply="${reply:-Y}"
    else
        read -r -p "$prompt [y/N]: " reply
        reply="${reply:-N}"
    fi

    [[ "$reply" =~ ^[Yy]$ ]]
}

if [ "$(uname -s)" != "Linux" ]; then
    echo "This setup script is intended for Raspberry Pi Linux." >&2
    exit 1
fi

if [ "${EUID}" -eq 0 ]; then
    echo "Run this script as your normal user, not as root. It will call sudo when needed." >&2
    exit 1
fi

log STEP "Installing system packages"
sudo apt-get update
sudo apt-get install -y git curl ca-certificates gnupg python3 python3-venv python3-pip build-essential pkg-config

if ! command -v node >/dev/null 2>&1; then
    log STEP "Installing Node.js 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
else
    log INFO "Node.js already present: $(node --version)"
fi

if ! command -v docker >/dev/null 2>&1; then
    log STEP "Installing Docker"
    curl -fsSL https://get.docker.com | sh
else
    log INFO "Docker already present"
fi

log STEP "Granting required Linux groups"
sudo usermod -aG docker "$APP_USER"
sudo usermod -aG dialout "$APP_USER"

log STEP "Starting MongoDB in Docker"
mkdir -p "$MONGO_DATA_DIR"
EXISTING_MONGO_IMAGE="$(sudo docker inspect --format '{{.Config.Image}}' "$MONGO_CONTAINER" 2>/dev/null || true)"
if [ -n "$EXISTING_MONGO_IMAGE" ] && [ "$EXISTING_MONGO_IMAGE" != "$MONGO_IMAGE" ]; then
    log WARN "Recreating ${MONGO_CONTAINER} because image ${EXISTING_MONGO_IMAGE} is not compatible with requested ${MONGO_IMAGE}"
    sudo docker rm -f "$MONGO_CONTAINER" >/dev/null || true
fi
if ! sudo docker ps -a --format '{{.Names}}' | grep -qx "$MONGO_CONTAINER"; then
    sudo docker run -d \
        --name "$MONGO_CONTAINER" \
        --restart unless-stopped \
        -p 127.0.0.1:27017:27017 \
        -v "$MONGO_DATA_DIR:/data/db" \
        "$MONGO_IMAGE"
else
    sudo docker start "$MONGO_CONTAINER" >/dev/null || true
    sudo docker update --restart unless-stopped "$MONGO_CONTAINER" >/dev/null
fi

if ! sudo docker ps --format '{{.Names}}' | grep -qx "$MONGO_CONTAINER"; then
    echo "MongoDB container failed to start. On older Raspberry Pi CPUs, use MONGO_IMAGE=mongo:4.4.18 or another compatible image." >&2
    sudo docker logs --tail 50 "$MONGO_CONTAINER" >&2 || true
    exit 1
fi

log STEP "Preparing Python environment"
if [ ! -d "$ROOT/.venv" ]; then
    python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" install --upgrade pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"

log STEP "Building frontend bundle"
cd "$ROOT/frontend"
if [ -f package-lock.json ]; then
    npm ci
else
    npm install
fi
npm run build
cd "$ROOT"

log STEP "Database setup"
echo "Choose a database action:"
echo "  1) Restore an existing backup"
echo "  2) Initialize a fresh database"
echo "  3) Skip for now"
read -r -p "Selection [1/2/3]: " DB_CHOICE

case "${DB_CHOICE:-3}" in
    1)
        DEFAULT_BACKUP="$(find "$ROOT/backups" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -n 1 || true)"
        if [ -n "$DEFAULT_BACKUP" ]; then
            echo "Latest local backup: $DEFAULT_BACKUP"
        else
            echo "No local backups found under $ROOT/backups"
        fi
        read -r -p "Enter backup directory to restore [${DEFAULT_BACKUP}]: " BACKUP_DIR
        BACKUP_DIR="${BACKUP_DIR:-$DEFAULT_BACKUP}"
        if [ -z "$BACKUP_DIR" ] || [ ! -f "$BACKUP_DIR/manifest.json" ]; then
            echo "A valid backup directory with manifest.json is required." >&2
            exit 1
        fi
        "$ROOT/.venv/bin/python" "$ROOT/restore_mongo.py" "$BACKUP_DIR" --mongo-uri "$MONGO_URI"
        ;;
    2)
        "$ROOT/.venv/bin/python" "$ROOT/scripts/init_db.py" --mongo-uri "$MONGO_URI"
        ;;
    *)
        log INFO "Skipping database initialization or restore"
        ;;
esac

log STEP "Checking USB bridge visibility"
if ! "$ROOT/.venv/bin/python" "$ROOT/scripts/check_usb_bridge.py"; then
    log WARN "Blue Pill bridge is not visible yet. Check the USB cable, power, and dialout group membership."
fi

log STEP "Installing systemd service"
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=OSDP Access Panel
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${ROOT}
Environment=MONGO_URI=${MONGO_URI}
ExecStart=${ROOT}/.venv/bin/python ${ROOT}/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

if prompt_yes_no "Enable and start ${SERVICE_NAME}.service now?" "Y"; then
    sudo systemctl enable --now "${SERVICE_NAME}.service"
    sudo systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
fi

log DONE "Raspberry Pi setup complete"
echo "MongoDB container: ${MONGO_CONTAINER}"
echo "App service: ${SERVICE_NAME}.service"
echo "Note: you may need to log out and back in before docker and dialout group membership fully apply."