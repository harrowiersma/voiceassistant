#!/bin/bash -e
# Install and enable systemd services for voice-secretary

# Copy service files into the image
install -m 644 "${STAGE_DIR}/../../systemd/voice-secretary-web.service" \
    "${ROOTFS_DIR}/etc/systemd/system/voice-secretary-web.service"
install -m 644 "${STAGE_DIR}/../../systemd/voice-secretary-engine.service" \
    "${ROOTFS_DIR}/etc/systemd/system/voice-secretary-engine.service"

# Enable services inside chroot
on_chroot << 'CHEOF'
systemctl enable voice-secretary-web.service
systemctl enable voice-secretary-engine.service
CHEOF
