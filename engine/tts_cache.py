"""Pre-render static greeting and vacation messages to WAV for instant playback."""

import logging
import os

from app.helpers import get_config
from engine.prompt_builder import get_active_vacation
from engine.tts import TTSEngine

logger = logging.getLogger(__name__)


class TTSCache:
    def __init__(self, db_path=None, cache_dir=None, tts_available=None):
        self.db_path = db_path
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "instance", "tts_cache"
        )
        os.makedirs(self.cache_dir, exist_ok=True)

        if tts_available is not None:
            self._tts_available = tts_available
        else:
            self._tts_available = TTSEngine().is_available()

    def cache_greeting(self):
        """Render persona greeting to greeting.wav. Returns path or None."""
        greeting_template = get_config("persona.greeting", "", self.db_path)
        if not greeting_template or not greeting_template.strip():
            return None
        company = get_config("persona.company_name", "the company", self.db_path)
        text = greeting_template.replace("{company}", company)
        return self._render_to_file(text, "greeting.wav")

    def cache_vacation_message(self):
        """Render active vacation message to vacation_{id}.wav. Returns path or None."""
        vacation = get_active_vacation(self.db_path)
        if not vacation:
            return None
        vacation_id = vacation.get("id", "unknown")
        text = vacation["response"]
        return self._render_to_file(text, f"vacation_{vacation_id}.wav")

    def get_greeting_path(self):
        """Return path to greeting.wav if it exists on disk, else None."""
        path = os.path.join(self.cache_dir, "greeting.wav")
        return path if os.path.isfile(path) else None

    def get_vacation_path(self):
        """Return path to active vacation WAV if it exists, else None."""
        vacation = get_active_vacation(self.db_path)
        if not vacation:
            return None
        vacation_id = vacation.get("id", "unknown")
        path = os.path.join(self.cache_dir, f"vacation_{vacation_id}.wav")
        return path if os.path.isfile(path) else None

    def _render_to_file(self, text, filename):
        """Synthesize text to WAV via TTSEngine. Returns file path or None."""
        if not self._tts_available:
            logger.info("TTS not available, skipping cache render for %s", filename)
            return None
        engine = TTSEngine()
        audio_bytes = engine.synthesize(text)
        if not audio_bytes:
            logger.warning("TTS synthesis returned no data for %s", filename)
            return None
        path = os.path.join(self.cache_dir, filename)
        with open(path, "wb") as f:
            f.write(audio_bytes)
        logger.info("Cached TTS audio: %s", path)
        return path
