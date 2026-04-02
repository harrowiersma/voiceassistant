#!/bin/bash -e
# Build the voice-secretary Raspberry Pi OS image using pi-gen and Docker.
#
# Usage: ./build.sh
#
# Prerequisites: Docker must be running on the host machine.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen-upstream"

# Clone pi-gen if not already present
if [ ! -d "${PIGEN_DIR}" ]; then
    echo ">>> Cloning pi-gen..."
    git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
fi

# Copy our config into pi-gen
echo ">>> Copying config..."
cp "${SCRIPT_DIR}/config" "${PIGEN_DIR}/config"

# Copy the custom stage into pi-gen
echo ">>> Copying stage-voicesec..."
rm -rf "${PIGEN_DIR}/stage-voicesec"
cp -r "${SCRIPT_DIR}/stage-voicesec" "${PIGEN_DIR}/stage-voicesec"

# Make stage scripts executable
chmod +x "${PIGEN_DIR}/stage-voicesec/"*.sh

# The STAGE_DIR references in scripts need access to our project files,
# so we copy the relevant project directories into the stage
cp -r "${PROJECT_DIR}/app" "${PIGEN_DIR}/stage-voicesec/app"
cp -r "${PROJECT_DIR}/db" "${PIGEN_DIR}/stage-voicesec/db"
cp "${PROJECT_DIR}/requirements.txt" "${PIGEN_DIR}/stage-voicesec/requirements.txt"
cp -r "${PROJECT_DIR}/systemd" "${PIGEN_DIR}/stage-voicesec/systemd"

# Skip stages 3, 4, 5 (desktop, full desktop, etc.) — we only want lite + our stage
for stage in stage3 stage4 stage5; do
    if [ -d "${PIGEN_DIR}/${stage}" ]; then
        touch "${PIGEN_DIR}/${stage}/SKIP"
    fi
done

# Mark our custom stage for image export
touch "${PIGEN_DIR}/stage-voicesec/EXPORT_IMAGE"

# Run the Docker-based build
echo ">>> Starting pi-gen Docker build..."
cd "${PIGEN_DIR}"
./build-docker.sh

echo ">>> Build complete. Image is in ${PIGEN_DIR}/deploy/"
