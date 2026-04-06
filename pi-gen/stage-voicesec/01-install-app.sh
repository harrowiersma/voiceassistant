#!/bin/bash -e
# Install the voice-secretary Flask application into the image

# Copy the application source into the image filesystem
install -d "${ROOTFS_DIR}/opt/voice-secretary"
cp -r "${STAGE_DIR}/../../app" "${ROOTFS_DIR}/opt/voice-secretary/app"
cp -r "${STAGE_DIR}/../../db" "${ROOTFS_DIR}/opt/voice-secretary/db"
cp -r "${STAGE_DIR}/../../engine" "${ROOTFS_DIR}/opt/voice-secretary/engine"
cp -r "${STAGE_DIR}/../../integrations" "${ROOTFS_DIR}/opt/voice-secretary/integrations"
cp -r "${STAGE_DIR}/../../config" "${ROOTFS_DIR}/opt/voice-secretary/config"
cp -r "${STAGE_DIR}/../../scripts" "${ROOTFS_DIR}/opt/voice-secretary/scripts"
cp "${STAGE_DIR}/../../requirements.txt" "${ROOTFS_DIR}/opt/voice-secretary/requirements.txt"
cp "${STAGE_DIR}/../../Makefile" "${ROOTFS_DIR}/opt/voice-secretary/Makefile"

# Copy .env if it exists (contains pre-configured credentials)
if [ -f "${STAGE_DIR}/../../.env" ]; then
    cp "${STAGE_DIR}/../../.env" "${ROOTFS_DIR}/opt/voice-secretary/.env"
fi

# Create venv, install dependencies, initialize DB — all inside chroot
on_chroot << 'CHEOF'
cd /opt/voice-secretary

# Create Python virtual environment
python3 -m venv .venv

# Install pip requirements
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Initialize the SQLite database (schema + default admin + default persona)
.venv/bin/python -c "from db.init_db import init_db; init_db()"

# Seed config from .env if present
if [ -f .env ]; then
    .venv/bin/python scripts/seed_config.py
fi

# Set ownership to the voicesec user
chown -R voicesec:voicesec /opt/voice-secretary
CHEOF
