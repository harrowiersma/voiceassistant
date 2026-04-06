#!/bin/bash
set -e

#
# Voice Secretary — Raspberry Pi Installer
#
# Run on a fresh Raspberry Pi OS Lite (64-bit):
#   sudo bash scripts/install.sh
#
# Prerequisites:
#   - Raspberry Pi OS Lite (64-bit, Bookworm) flashed with Pi Imager
#   - SSH enabled, WiFi configured, user 'voicesec' created
#   - This repo cloned to ~/voiceassistant
#   - .env file present with your credentials
#
# What this script does:
#   1. Installs system packages (Asterisk, Python, audio libs, ffmpeg)
#   2. Installs Ollama (local LLM inference)
#   3. Downloads Vosk STT model (English, small — 50MB)
#   4. Installs Piper TTS + downloads English voice
#   5. Creates Python venv and installs pip requirements
#   6. Initializes SQLite database
#   7. Seeds config from .env file
#   8. Generates and applies Asterisk config
#   9. Installs systemd services (auto-start on boot)
#   10. Pulls Ollama model (Llama 3.2 1B)
#
# After install:
#   Dashboard:  http://voicesec.local:8080
#   Login:      admin / voicesec
#   SSH:        ssh voicesec@voicesec.local
#

echo "============================================"
echo "  Voice Secretary — Pi Installer"
echo "============================================"
echo ""

# Must run as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Run with sudo: sudo bash scripts/install.sh"
    exit 1
fi

# Detect project directory (script is in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="/opt/voice-secretary"
ACTUAL_USER="${SUDO_USER:-voicesec}"

echo "  Project: ${PROJECT_DIR}"
echo "  Install: ${INSTALL_DIR}"
echo "  User:    ${ACTUAL_USER}"
echo ""

# ──────────────────────────────────────────────
# Step 1: System packages
# ──────────────────────────────────────────────
echo ">>> [1/10] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    asterisk asterisk-core-sounds-en \
    sqlite3 git curl \
    build-essential \
    libportaudio2 libsndfile1 \
    ffmpeg \
    unzip

echo "  System packages: OK"

# ──────────────────────────────────────────────
# Step 2: Install Ollama
# ──────────────────────────────────────────────
echo ">>> [2/10] Installing Ollama..."
if command -v ollama &>/dev/null; then
    echo "  Ollama already installed, skipping"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "  Ollama: OK"
fi

# Enable and start Ollama service
systemctl enable ollama 2>/dev/null || true
systemctl start ollama 2>/dev/null || true

# ──────────────────────────────────────────────
# Step 3: Download Vosk STT model
# ──────────────────────────────────────────────
echo ">>> [3/10] Downloading Vosk speech-to-text model..."
VOSK_MODEL_DIR="${INSTALL_DIR}/models/vosk"
if [ -d "${VOSK_MODEL_DIR}/model" ]; then
    echo "  Vosk model already exists, skipping"
else
    mkdir -p "${VOSK_MODEL_DIR}"
    cd /tmp
    curl -fsSL -o vosk-model.zip \
        https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip -q vosk-model.zip
    mv vosk-model-small-en-us-0.15 "${VOSK_MODEL_DIR}/model"
    rm -f vosk-model.zip
    echo "  Vosk model (small-en-us): OK"
fi

# ──────────────────────────────────────────────
# Step 4: Copy project to /opt
# ──────────────────────────────────────────────
echo ">>> [4/10] Copying project to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"

# Copy application code
for dir in app db engine integrations config scripts; do
    rm -rf "${INSTALL_DIR}/${dir}"
    cp -r "${PROJECT_DIR}/${dir}" "${INSTALL_DIR}/${dir}"
done

# Copy config files
cp "${PROJECT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
cp "${PROJECT_DIR}/Makefile" "${INSTALL_DIR}/Makefile"

# Copy .env if present
if [ -f "${PROJECT_DIR}/.env" ]; then
    cp "${PROJECT_DIR}/.env" "${INSTALL_DIR}/.env"
    echo "  .env copied: OK"
else
    echo "  WARNING: No .env file found. Run 'make seed' after creating one."
fi

echo "  Project files: OK"

# ──────────────────────────────────────────────
# Step 5: Python venv + pip install
# ──────────────────────────────────────────────
echo ">>> [5/10] Setting up Python virtual environment..."
cd "${INSTALL_DIR}"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# Install Vosk Python bindings
.venv/bin/pip install vosk -q

# Install Piper TTS
.venv/bin/pip install piper-tts -q 2>/dev/null || echo "  Note: piper-tts pip install may require manual setup on aarch64"

echo "  Python venv: OK"

# ──────────────────────────────────────────────
# Step 6: Download Piper TTS voice
# ──────────────────────────────────────────────
echo ">>> [6/10] Downloading Piper TTS voice..."
PIPER_VOICE_DIR="${INSTALL_DIR}/models/piper"
if [ -f "${PIPER_VOICE_DIR}/en-us-amy-medium.onnx" ]; then
    echo "  Piper voice already exists, skipping"
else
    mkdir -p "${PIPER_VOICE_DIR}"
    curl -fsSL -o "${PIPER_VOICE_DIR}/en-us-amy-medium.onnx" \
        https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx
    curl -fsSL -o "${PIPER_VOICE_DIR}/en-us-amy-medium.onnx.json" \
        https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json
    echo "  Piper voice (Amy medium): OK"
fi

# ──────────────────────────────────────────────
# Step 7: Initialize database
# ──────────────────────────────────────────────
echo ">>> [7/10] Initializing database..."
cd "${INSTALL_DIR}"
.venv/bin/python -c "from db.init_db import init_db; init_db()"
echo "  Database: OK (admin/voicesec + default persona)"

# ──────────────────────────────────────────────
# Step 8: Seed config from .env
# ──────────────────────────────────────────────
echo ">>> [8/10] Seeding configuration from .env..."
if [ -f "${INSTALL_DIR}/.env" ]; then
    .venv/bin/python scripts/seed_config.py
    echo "  Config seeded: OK"
else
    echo "  SKIPPED: No .env file. Create one and run: make seed"
fi

# ──────────────────────────────────────────────
# Step 9: Generate Asterisk config + install systemd services
# ──────────────────────────────────────────────
echo ">>> [9/10] Configuring Asterisk and systemd services..."

# Generate Asterisk config from database
.venv/bin/python -c "
from app import create_app
from app.helpers import get_config
from config.defaults import SIP_DEFAULTS
from config.asterisk_gen import render_pjsip_conf, render_extensions_conf, render_rtp_conf
import os

app = create_app()
with app.app_context():
    db = app.config.get('DATABASE')
    sip_fields = list(SIP_DEFAULTS.keys()) + ['sip.stun_server']
    config = {}
    for key in sip_fields:
        config[key] = get_config(key, default=SIP_DEFAULTS.get(key, ''), db_path=db)

    config_dir = '/etc/asterisk'
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, 'pjsip.conf'), 'w') as f:
        f.write(render_pjsip_conf(config))
    with open(os.path.join(config_dir, 'extensions.conf'), 'w') as f:
        f.write(render_extensions_conf(config))
    with open(os.path.join(config_dir, 'rtp.conf'), 'w') as f:
        f.write(render_rtp_conf(config))
    print('  Asterisk config written to /etc/asterisk/')
" 2>/dev/null || echo "  WARNING: Could not generate Asterisk config (will be done via dashboard)"

# Install systemd services
cp "${PROJECT_DIR}/systemd/voice-secretary-web.service" /etc/systemd/system/
cp "${PROJECT_DIR}/systemd/voice-secretary-engine.service" /etc/systemd/system/

# Update service files to use correct user if not 'voicesec'
if [ "${ACTUAL_USER}" != "voicesec" ]; then
    sed -i "s/User=voicesec/User=${ACTUAL_USER}/" /etc/systemd/system/voice-secretary-web.service
    sed -i "s/Group=voicesec/Group=${ACTUAL_USER}/" /etc/systemd/system/voice-secretary-web.service
    sed -i "s/User=voicesec/User=${ACTUAL_USER}/" /etc/systemd/system/voice-secretary-engine.service
    sed -i "s/Group=voicesec/Group=${ACTUAL_USER}/" /etc/systemd/system/voice-secretary-engine.service
fi

systemctl daemon-reload
systemctl enable asterisk
systemctl enable voice-secretary-web
systemctl enable voice-secretary-engine

# Enable and start Asterisk
systemctl restart asterisk 2>/dev/null || echo "  Note: Asterisk restart may need reboot"

echo "  systemd services: OK (enabled, will start on boot)"

# ──────────────────────────────────────────────
# Step 10: Set ownership + pull Ollama model
# ──────────────────────────────────────────────
echo ">>> [10/10] Final setup..."

# Set ownership of everything to the service user
chown -R "${ACTUAL_USER}:${ACTUAL_USER}" "${INSTALL_DIR}"

# Create symlink for easy access
ln -sf "${INSTALL_DIR}" "/home/${ACTUAL_USER}/voice-secretary" 2>/dev/null || true

# Pull the Ollama model (this takes a few minutes)
echo "  Pulling Ollama model (llama3.2:1b — ~1.3GB, please wait)..."
sudo -u "${ACTUAL_USER}" ollama pull llama3.2:1b 2>/dev/null || echo "  WARNING: Could not pull model. Run manually: ollama pull llama3.2:1b"

echo ""
echo "============================================"
echo "  INSTALL COMPLETE"
echo "============================================"
echo ""
echo "  Starting services..."
systemctl start voice-secretary-web
echo ""
echo "  Dashboard:  http://voicesec.local:8080"
echo "  Login:      admin / voicesec"
echo "  SSH:        ssh ${ACTUAL_USER}@voicesec.local"
echo ""
echo "  IMPORTANT: Change the default password after first login!"
echo ""
echo "  To update later:"
echo "    cd ${PROJECT_DIR} && git pull"
echo "    sudo bash scripts/install.sh"
echo ""
echo "  To check status:"
echo "    systemctl status voice-secretary-web"
echo "    systemctl status voice-secretary-engine"
echo "    systemctl status asterisk"
echo "    systemctl status ollama"
echo ""
