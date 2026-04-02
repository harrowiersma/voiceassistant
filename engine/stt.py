import logging

logger = logging.getLogger(__name__)


class STTEngine:
    def __init__(self, model_path=None):
        self.model_path = model_path
        self._recognizer = None

    def is_available(self):
        try:
            import vosk  # noqa: F401
            return self.model_path is not None
        except ImportError:
            return False

    def _load_model(self):
        if self._recognizer is None and self.is_available():
            import vosk
            model = vosk.Model(self.model_path)
            self._recognizer = vosk.KaldiRecognizer(model, 16000)
        return self._recognizer

    def transcribe(self, audio_bytes):
        recognizer = self._load_model()
        if recognizer is None:
            logger.warning("Vosk not available, cannot transcribe")
            return ""
        import json
        recognizer.AcceptWaveform(audio_bytes)
        result = json.loads(recognizer.FinalResult())
        return result.get("text", "")
