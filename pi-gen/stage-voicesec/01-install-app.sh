#!/bin/bash -e
# Install the voice-secretary Flask application into the image

# Copy the application source into the image filesystem
install -d "${ROOTFS_DIR}/opt/voice-secretary"
cp -r "${STAGE_DIR}/../../app" "${ROOTFS_DIR}/opt/voice-secretary/app"
cp -r "${STAGE_DIR}/../../db" "${ROOTFS_DIR}/opt/voice-secretary/db"
cp -r "${STAGE_DIR}/../../engine" "${ROOTFS_DIR}/opt/voice-secretary/engine"
cp -r "${STAGE_DIR}/../../integrations" "${ROOTFS_DIR}/opt/voice-secretary/integrations"
cp -r "${STAGE_DIR}/../../config" "${ROOTFS_DIR}/opt/voice-secretary/config"
cp "${STAGE_DIR}/../../requirements.txt" "${ROOTFS_DIR}/opt/voice-secretary/requirements.txt"

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

# Set ownership to the voicesec user
chown -R voicesec:voicesec /opt/voice-secretary
CHEOF
