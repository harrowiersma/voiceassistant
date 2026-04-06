"""Voice Secretary Engine — main entry point.

Starts the AudioSocket server that receives calls from Asterisk
and processes them through the STT → LLM → TTS pipeline.
"""
import asyncio
import logging
from engine.audiosocket import start_server
from engine.call_handler import handle_call, init_vosk_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    # Pre-load Vosk STT model (takes ~500ms, done once at startup)
    init_vosk_model()

    server = await start_server(call_handler=handle_call)
    async with server:
        logger.info("Voice Secretary Engine running. Waiting for calls on port 9092...")
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
