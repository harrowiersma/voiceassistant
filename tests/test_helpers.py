import tempfile
import os
import pytest
from db.init_db import init_db
from app.helpers import get_config, set_config, get_configs_by_category


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_set_and_get_config(db_path):
    set_config("persona.company_name", "Wiersma", "persona", db_path)
    assert get_config("persona.company_name", db_path=db_path) == "Wiersma"


def test_get_config_returns_default_if_missing(db_path):
    assert get_config("nonexistent.key", default="fallback", db_path=db_path) == "fallback"


def test_set_config_upserts(db_path):
    set_config("sip.server", "old.example.com", "sip", db_path)
    set_config("sip.server", "new.example.com", "sip", db_path)
    assert get_config("sip.server", db_path=db_path) == "new.example.com"


def test_get_configs_by_category(db_path):
    set_config("sip.server", "sip.example.com", "sip", db_path)
    set_config("sip.port", "5060", "sip", db_path)
    set_config("ai.model", "llama3.2", "ai", db_path)
    configs = get_configs_by_category("sip", db_path)
    assert len(configs) == 2
    keys = [c["key"] for c in configs]
    assert "sip.server" in keys
    assert "sip.port" in keys
