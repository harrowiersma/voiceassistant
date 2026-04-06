"""Voice Secretary Engine — main entry point.

Starts the AudioSocket server that receives calls from Asterisk
and processes them through the STT → LLM → TTS pipeline.
"""
import asyncio
import logging
from engine.audiosocket import start_server
from engine.call_handler import handle_call, init_vosk_model
from engine.llm import LLMClient
from app.helpers import get_config
from db.init_db import DEFAULT_DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def warmup_ollama():
    """Send a dummy request to Ollama to load the model into memory."""
    model = get_config("ai.llm_model", default="llama3.2:1b", db_path=DEFAULT_DB_PATH)
    logger.info(f"Warming up Ollama ({model})...")
    client = LLMClient(model=model)
    if client.is_available():
        response = client.chat("Hello", system_prompt="Reply with just 'ready'.")
        logger.info(f"Ollama warm: {response[:50] if response else 'no response'}")
    else:
        logger.warning("Ollama not available for warmup")


async def main():
    # Pre-load models at startup
    init_vosk_model()
    warmup_ollama()

    server = await start_server(call_handler=handle_call)
    async with server:
        logger.info("Voice Secretary Engine running. Waiting for calls on port 9092...")
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
