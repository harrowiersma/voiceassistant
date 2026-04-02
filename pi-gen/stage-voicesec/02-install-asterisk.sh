#!/bin/bash -e
# Configure Asterisk PBX for voice-secretary

on_chroot << 'CHEOF'
# Enable asterisk service to start on boot
systemctl enable asterisk

# Create directory for voice-secretary generated Asterisk configs
mkdir -p /etc/asterisk/voicesec
chown asterisk:asterisk /etc/asterisk/voicesec
CHEOF
