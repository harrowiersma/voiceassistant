import struct
import pytest


def test_parse_uuid_frame():
    from engine.audiosocket import AudioSocketProtocol, UUID_TYPE
    uuid_bytes = b"\x01" * 16
    frame = struct.pack("!BH", UUID_TYPE, 16) + uuid_bytes
    msg_type, payload = AudioSocketProtocol.parse_frame(frame)
    assert msg_type == UUID_TYPE
    assert payload == uuid_bytes


def test_parse_audio_frame():
    from engine.audiosocket import AudioSocketProtocol, AUDIO_TYPE
    audio_data = b"\x00\x01" * 160  # 320 bytes = 20ms at 16kHz 16-bit
    frame = struct.pack("!BH", AUDIO_TYPE, len(audio_data)) + audio_data
    msg_type, payload = AudioSocketProtocol.parse_frame(frame)
    assert msg_type == AUDIO_TYPE
    assert payload == audio_data


def test_parse_hangup_frame():
    from engine.audiosocket import AudioSocketProtocol, HANGUP_TYPE
    frame = struct.pack("!BH", HANGUP_TYPE, 0)
    msg_type, payload = AudioSocketProtocol.parse_frame(frame)
    assert msg_type == HANGUP_TYPE


def test_build_audio_frame():
    from engine.audiosocket import AudioSocketProtocol, AUDIO_TYPE
    audio_data = b"\x00\x01" * 80
    frame = AudioSocketProtocol.build_audio_frame(audio_data)
    assert len(frame) == 3 + len(audio_data)
    assert frame[0] == AUDIO_TYPE
    length = struct.unpack("!H", frame[1:3])[0]
    assert length == len(audio_data)
