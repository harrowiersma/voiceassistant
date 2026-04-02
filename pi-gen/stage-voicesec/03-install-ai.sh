#!/bin/bash -e
# Install AI components: Ollama LLM, Vosk STT, Piper TTS

on_chroot << 'CHEOF'
# --- Ollama (local LLM inference) ---
curl -fsSL https://ollama.com/install.sh | sh

# --- Vosk (speech-to-text) ---
VOSK_MODEL_DIR="/opt/voice-secretary/models/vosk"
mkdir -p "${VOSK_MODEL_DIR}"
cd /tmp
curl -fsSL -o vosk-model.zip \
    https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip -q vosk-model.zip
mv vosk-model-small-en-us-0.15 "${VOSK_MODEL_DIR}/model"
rm -f vosk-model.zip

# Install vosk Python package into the app venv
/opt/voice-secretary/.venv/bin/pip install vosk

# --- Piper (text-to-speech) ---
/opt/voice-secretary/.venv/bin/pip install piper-tts

# Download Piper English voice (Amy medium)
PIPER_VOICE_DIR="/opt/voice-secretary/models/piper"
mkdir -p "${PIPER_VOICE_DIR}"
curl -fsSL -o "${PIPER_VOICE_DIR}/en-us-amy-medium.onnx" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx
curl -fsSL -o "${PIPER_VOICE_DIR}/en-us-amy-medium.onnx.json" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json

# Set ownership
chown -R voicesec:voicesec /opt/voice-secretary/models
CHEOF
