import tempfile, os, shutil
import pytest
from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def cache_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def test_cache_greeting_without_tts(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    set_config("persona.greeting", "Hello, welcome to TestCo.", "persona", db_path)
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    path = cache.cache_greeting()
    assert path is None  # TTS not available, graceful


def test_get_greeting_path_returns_existing(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    set_config("persona.greeting", "Hello.", "persona", db_path)
    set_config("persona.company_name", "TestCo", "persona", db_path)
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    # Simulate a pre-existing cached file
    fake_path = os.path.join(cache_dir, "greeting.wav")
    with open(fake_path, "wb") as f:
        f.write(b"RIFF fake wav data")
    path = cache.get_greeting_path()
    assert path == fake_path


def test_cache_vacation_without_tts(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, response, active_from, active_until, enabled) "
        "VALUES ('vacation', 'We are closed for holidays.', date('now','-1 day'), date('now','+1 day'), 1)"
    )
    conn.commit()
    conn.close()
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    path = cache.cache_vacation_message()
    assert path is None


def test_empty_greeting_no_crash(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    set_config("persona.greeting", "", "persona", db_path)
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    path = cache.cache_greeting()
    assert path is None
