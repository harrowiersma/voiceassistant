#!/bin/bash -e
#
# Voice Secretary — Pi Image Builder
#
# Location: /Users/harrowiersma/Documents/CLAUDE/assistant/voice-secretary/build.sh
#
# Usage:
#   cd /Users/harrowiersma/Documents/CLAUDE/assistant/voice-secretary
#   ./build.sh
#
# Prerequisites:
#   - Docker Desktop must be running
#   - .env file must exist with your credentials
#
# Output:
#   Pi OS image in pi-gen/pi-gen-upstream/deploy/
#   Flash with Raspberry Pi Imager → boot → dashboard at http://voicesec.local:8080
#

echo "============================================"
echo "  Voice Secretary — Pi Image Builder"
echo "============================================"
echo ""

# Resolve paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
PIGEN_WRAPPER="${PROJECT_DIR}/pi-gen"
PIGEN_DIR="${PIGEN_WRAPPER}/pi-gen-upstream"

# Pre-flight checks
echo ">>> Pre-flight checks..."

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop and try again."
    exit 1
fi
echo "  Docker: OK"

if [ ! -f "${PROJECT_DIR}/.env" ]; then
    echo "ERROR: .env file not found at ${PROJECT_DIR}/.env"
    echo "  Copy .env.example to .env and fill in your credentials."
    exit 1
fi
echo "  .env: OK"

echo ""

# Clone pi-gen if not already present
if [ ! -d "${PIGEN_DIR}" ]; then
    echo ">>> Cloning pi-gen (official Raspberry Pi image builder)..."
    git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
else
    echo ">>> pi-gen already cloned"
fi

# Copy our pi-gen config
echo ">>> Copying pi-gen config..."
cp "${PIGEN_WRAPPER}/config" "${PIGEN_DIR}/config"

# Prepare our custom stage
echo ">>> Preparing stage-voicesec..."
rm -rf "${PIGEN_DIR}/stage-voicesec"
cp -r "${PIGEN_WRAPPER}/stage-voicesec" "${PIGEN_DIR}/stage-voicesec"

# The install scripts reference project files via STAGE_DIR
# Copy all project directories into the stage so they're available during Docker build
echo ">>> Copying project files into stage..."
STAGE="${PIGEN_DIR}/stage-voicesec"

cp -r "${PROJECT_DIR}/app"           "${STAGE}/app"
cp -r "${PROJECT_DIR}/db"            "${STAGE}/db"
cp -r "${PROJECT_DIR}/engine"        "${STAGE}/engine"
cp -r "${PROJECT_DIR}/integrations"  "${STAGE}/integrations"
cp -r "${PROJECT_DIR}/config"        "${STAGE}/config"
cp -r "${PROJECT_DIR}/scripts"       "${STAGE}/scripts"
cp -r "${PROJECT_DIR}/systemd"       "${STAGE}/systemd"
cp    "${PROJECT_DIR}/requirements.txt" "${STAGE}/requirements.txt"
cp    "${PROJECT_DIR}/Makefile"      "${STAGE}/Makefile"
cp    "${PROJECT_DIR}/.env"          "${STAGE}/.env"

# Make stage scripts executable
chmod +x "${STAGE}/"*.sh

# Update install script paths: since files are now IN the stage, use STAGE_DIR
# Rewrite 01-install-app.sh to reference files from STAGE_DIR (not ../../)
cat > "${STAGE}/01-install-app.sh" << 'INSTALLEOF'
#!/bin/bash -e
# Install the voice-secretary Flask application into the image

# Copy application source into the image filesystem
install -d "${ROOTFS_DIR}/opt/voice-secretary"
cp -r "${STAGE_DIR}/app"           "${ROOTFS_DIR}/opt/voice-secretary/app"
cp -r "${STAGE_DIR}/db"            "${ROOTFS_DIR}/opt/voice-secretary/db"
cp -r "${STAGE_DIR}/engine"        "${ROOTFS_DIR}/opt/voice-secretary/engine"
cp -r "${STAGE_DIR}/integrations"  "${ROOTFS_DIR}/opt/voice-secretary/integrations"
cp -r "${STAGE_DIR}/config"        "${ROOTFS_DIR}/opt/voice-secretary/config"
cp -r "${STAGE_DIR}/scripts"       "${ROOTFS_DIR}/opt/voice-secretary/scripts"
cp    "${STAGE_DIR}/requirements.txt" "${ROOTFS_DIR}/opt/voice-secretary/requirements.txt"
cp    "${STAGE_DIR}/Makefile"      "${ROOTFS_DIR}/opt/voice-secretary/Makefile"

# Copy .env with credentials
if [ -f "${STAGE_DIR}/.env" ]; then
    cp "${STAGE_DIR}/.env" "${ROOTFS_DIR}/opt/voice-secretary/.env"
fi

# Create venv, install dependencies, initialize DB, seed config
on_chroot << 'CHEOF'
cd /opt/voice-secretary

# Create Python virtual environment
python3 -m venv .venv

# Install pip requirements
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Initialize database (schema + default admin + default persona)
.venv/bin/python -c "from db.init_db import init_db; init_db()"

# Seed config from .env
if [ -f .env ]; then
    .venv/bin/python scripts/seed_config.py
fi

# Set ownership
chown -R voicesec:voicesec /opt/voice-secretary
CHEOF
INSTALLEOF
chmod +x "${STAGE}/01-install-app.sh"

# Copy systemd service files install script
cat > "${STAGE}/04-services.sh" << 'SVCEOF'
#!/bin/bash -e
# Install and enable systemd services

install -m 644 "${STAGE_DIR}/systemd/voice-secretary-web.service" "${ROOTFS_DIR}/etc/systemd/system/"
install -m 644 "${STAGE_DIR}/systemd/voice-secretary-engine.service" "${ROOTFS_DIR}/etc/systemd/system/"

on_chroot << 'CHEOF'
systemctl enable voice-secretary-web.service
systemctl enable voice-secretary-engine.service
systemctl enable asterisk || true
CHEOF
SVCEOF
chmod +x "${STAGE}/04-services.sh"

# Skip stages 3-5 (desktop environments — we only need lite + our stage)
for stage in stage3 stage4 stage5; do
    if [ -d "${PIGEN_DIR}/${stage}" ]; then
        touch "${PIGEN_DIR}/${stage}/SKIP"
    fi
done

# Mark our stage for image export
touch "${STAGE}/EXPORT_IMAGE"

# Build!
echo ""
echo ">>> Starting pi-gen Docker build..."
echo "    This will take 20-40 minutes on first run."
echo ""
cd "${PIGEN_DIR}"
./build-docker.sh

echo ""
echo "============================================"
echo "  BUILD COMPLETE"
echo "============================================"
echo ""
echo "  Image location: ${PIGEN_DIR}/deploy/"
echo ""
echo "  Next steps:"
echo "    1. Flash the .img file with Raspberry Pi Imager"
echo "    2. Boot the Pi"
echo "    3. Open http://voicesec.local:8080"
echo "    4. Login: admin / voicesec"
echo "    5. Change the default password!"
echo ""
