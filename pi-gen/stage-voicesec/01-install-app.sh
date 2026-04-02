#!/bin/bash -e
# Install the voice-secretary Flask application into the image

# Copy the application source into the image filesystem
install -d "${ROOTFS_DIR}/opt/voice-secretary"
cp -r "${STAGE_DIR}/../../app" "${ROOTFS_DIR}/opt/voice-secretary/app"
cp -r "${STAGE_DIR}/../../db" "${ROOTFS_DIR}/opt/voice-secretary/db"
cp "${STAGE_DIR}/../../requirements.txt" "${ROOTFS_DIR}/opt/voice-secretary/requirements.txt"

# Create venv, install dependencies, initialize DB — all inside chroot
on_chroot << 'CHEOF'
cd /opt/voice-secretary

# Create Python virtual environment
python3 -m venv .venv

# Install pip requirements
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Initialize the SQLite database
if [ -f db/schema.sql ]; then
    mkdir -p instance
    sqlite3 instance/voice-secretary.db < db/schema.sql
fi

# Set ownership to the voicesec user
chown -R voicesec:voicesec /opt/voice-secretary
CHEOF
