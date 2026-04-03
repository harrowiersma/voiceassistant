"""AudioSocket protocol parser and async TCP server for Asterisk integration.

Asterisk routes inbound calls to AudioSocket(host:port). The protocol is simple TCP:
- Frame format: 1 byte type + 2 bytes big-endian length + payload
- Types: 0x00 = hangup, 0x01 = UUID (16 bytes), 0x10 = audio (PCM 16-bit signed LE, 8kHz mono)
- First frame from Asterisk is always UUID, then audio frames stream continuously
- We send audio frames back for TTS playback
"""

import asyncio
import logging
import struct
import uuid

logger = logging.getLogger(__name__)

# Frame type constants
HANGUP_TYPE = 0x00
UUID_TYPE = 0x01
AUDIO_TYPE = 0x10

# Server defaults
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9092

# Header size: 1 byte type + 2 bytes length
HEADER_SIZE = 3


class AudioSocketProtocol:
    """Static methods for parsing and building AudioSocket frames."""

    @staticmethod
    def parse_frame(data: bytes) -> tuple:
        """Parse raw bytes into (type, payload).

        Returns (None, None) if data is shorter than the 3-byte header.
        """
        if len(data) < HEADER_SIZE:
            return (None, None)

        msg_type = data[0]
        length = struct.unpack("!H", data[1:3])[0]
        payload = data[3:3 + length] if length > 0 else b""
        return (msg_type, payload)

    @staticmethod
    def build_audio_frame(audio_data: bytes) -> bytes:
        """Pack audio data into an AudioSocket frame."""
        header = struct.pack("!BH", AUDIO_TYPE, len(audio_data))
        return header + audio_data

    @staticmethod
    def build_hangup_frame() -> bytes:
        """Pack a hangup frame with zero-length payload."""
        return struct.pack("!BH", HANGUP_TYPE, 0)


async def read_frame(reader: asyncio.StreamReader) -> tuple:
    """Read exactly one frame from the stream.

    Returns (msg_type, payload) or raises ConnectionError / asyncio.IncompleteReadError.
    """
    header = await reader.readexactly(HEADER_SIZE)
    msg_type = header[0]
    length = struct.unpack("!H", header[1:3])[0]

    payload = b""
    if length > 0:
        payload = await reader.readexactly(length)

    return (msg_type, payload)


async def handle_call(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    call_handler=None,
):
    """Handle an incoming AudioSocket connection from Asterisk.

    Reads the initial UUID frame, then either delegates to call_handler
    or runs a default echo loop (sends received audio back).
    """
    peer = writer.get_extra_info("peername")
    logger.info("New AudioSocket connection from %s", peer)

    try:
        # First frame must be UUID
        msg_type, payload = await read_frame(reader)
        if msg_type != UUID_TYPE or len(payload) != 16:
            logger.error("Expected UUID frame, got type=0x%02x len=%d", msg_type or 0, len(payload))
            writer.close()
            await writer.wait_closed()
            return

        call_uuid = uuid.UUID(bytes=payload)
        logger.info("Call UUID: %s", call_uuid)

        if call_handler is not None:
            await call_handler(call_uuid, reader, writer)
        else:
            # Default echo loop for testing
            logger.info("No call_handler provided, running echo loop")
            while True:
                msg_type, payload = await read_frame(reader)
                if msg_type == HANGUP_TYPE:
                    logger.info("Call %s hung up", call_uuid)
                    break
                elif msg_type == AUDIO_TYPE:
                    # Echo audio back
                    frame = AudioSocketProtocol.build_audio_frame(payload)
                    writer.write(frame)
                    await writer.drain()

    except asyncio.IncompleteReadError:
        logger.info("Connection closed (incomplete read)")
    except ConnectionResetError:
        logger.info("Connection reset by peer")
    except Exception:
        logger.exception("Error handling AudioSocket call")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_server(
    host: str = LISTEN_HOST,
    port: int = LISTEN_PORT,
    call_handler=None,
):
    """Start the AudioSocket TCP server.

    Args:
        host: Listen address (default 127.0.0.1)
        port: Listen port (default 9092)
        call_handler: Async callable(call_uuid, reader, writer) invoked per call.
                      If None, a simple echo loop is used.

    Returns:
        asyncio.Server instance (use async with server / server.serve_forever()).
    """

    async def _client_connected(reader, writer):
        await handle_call(reader, writer, call_handler)

    server = await asyncio.start_server(_client_connected, host, port)
    logger.info("AudioSocket server listening on %s:%d", host, port)
    return server
