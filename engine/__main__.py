"""Engine entry point — starts the AudioSocket server."""

import asyncio
import logging

from engine.audiosocket import start_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def main():
    server = await start_server()
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
