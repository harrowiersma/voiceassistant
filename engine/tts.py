import logging
import subprocess

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(self, voice="en-us-amy-medium", model_dir="/opt/voice-secretary/models/piper"):
        self.voice = voice
        self.model_dir = model_dir

    def is_available(self):
        try:
            result = subprocess.run(["piper", "--version"], capture_output=True, timeout=3)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def synthesize(self, text):
        if not self.is_available():
            logger.warning("Piper not available, cannot synthesize")
            return None
        try:
            model_path = f"{self.model_dir}/voice-{self.voice}.onnx"
            result = subprocess.run(
                ["piper", "--model", model_path, "--output_raw"],
                input=text.encode(), capture_output=True, timeout=30,
            )
            if result.returncode == 0:
                return result.stdout
            logger.error(f"Piper error: {result.stderr.decode()}")
            return None
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None
