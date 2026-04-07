"""Voice Secretary Engine — main entry point.

Starts the AudioSocket server that receives calls from Asterisk
and processes them through the STT → LLM → TTS pipeline.
"""
import asyncio
import logging
from engine.audiosocket import start_server
from engine.call_handler import handle_call, init_vosk_model, init_audio_cache
from engine.llm import LLMClient
from app.helpers import get_config
from db.init_db import DEFAULT_DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


_llm_client = None


def warmup_ollama():
    """Send a dummy request to Ollama to load the model into memory."""
    global _llm_client
    model = get_config("ai.llm_model", default="llama3.2:1b", db_path=DEFAULT_DB_PATH)
    logger.info(f"Warming up Ollama ({model})...")
    _llm_client = LLMClient(model=model)
    if _llm_client.is_available():
        response = _llm_client.chat("Hello", system_prompt="Reply with just 'ready'.")
        logger.info(f"Ollama warm: {response[:50] if response else 'no response'}")
    else:
        logger.warning("Ollama not available for warmup")


async def keepalive_loop():
    """Ping Ollama every 5 minutes to keep the model loaded in memory.
    Also re-register SIP every 10 minutes to keep NAT pinhole open."""
    import subprocess
    tick = 0
    while True:
        await asyncio.sleep(300)
        tick += 1
        try:
            if _llm_client and _llm_client.is_available():
                _llm_client.chat("ping", system_prompt="Reply: ok")
                logger.debug("Ollama keepalive ping sent")
        except Exception:
            pass
        # Re-register SIP every 10 minutes (every 2nd tick)
        if tick % 2 == 0:
            try:
                subprocess.run(
                    ["sudo", "/usr/sbin/asterisk", "-rx", "pjsip send register inbound-reg"],
                    capture_output=True, timeout=5,
                )
                logger.debug("SIP re-registration sent")
            except Exception:
                pass


async def main():
    # Pre-load models and caches at startup
    init_vosk_model()
    warmup_ollama()
    init_audio_cache()

    # Start keepalive in background
    asyncio.create_task(keepalive_loop())

    server = await start_server(call_handler=handle_call)
    async with server:
        logger.info("Voice Secretary Engine running. Waiting for calls on port 9092...")
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
