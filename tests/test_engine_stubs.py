import pytest


def test_llm_client_interface():
    from engine.llm import LLMClient
    client = LLMClient(model="llama3.2:1b")
    assert client.model == "llama3.2:1b"
    assert hasattr(client, "chat")
    assert hasattr(client, "is_available")


def test_llm_unavailable_returns_fallback():
    from engine.llm import LLMClient
    client = LLMClient(model="llama3.2:1b")
    if not client.is_available():
        response = client.chat("Hello", system_prompt="You are a secretary.")
        assert response is not None
        assert len(response) > 0


def test_stt_interface():
    from engine.stt import STTEngine
    engine = STTEngine(model_path="/nonexistent")
    assert hasattr(engine, "transcribe")
    assert hasattr(engine, "is_available")


def test_tts_interface():
    from engine.tts import TTSEngine
    engine = TTSEngine(voice="en-us-amy-medium")
    assert hasattr(engine, "synthesize")
    assert hasattr(engine, "is_available")


def test_tts_unavailable_returns_none():
    from engine.tts import TTSEngine
    engine = TTSEngine(voice="en-us-amy-medium")
    if not engine.is_available():
        result = engine.synthesize("Hello world")
        assert result is None
