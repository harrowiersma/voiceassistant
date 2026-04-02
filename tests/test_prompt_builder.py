import tempfile, os
from datetime import datetime, timedelta
import pytest
from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    set_config("persona.company_name", "Wiersma Consulting", "persona", path)
    set_config("persona.greeting", "Hello, you've reached {company}.", "persona", path)
    set_config("persona.personality", "Professional and friendly.", "persona", path)
    set_config("persona.unavailable_message", "They are not available.", "persona", path)
    yield path
    os.unlink(path)


def _add_rule(db_path, rule_type="topic", keywords="", response="", priority=0, enabled=True, active_from=None, active_until=None):
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, priority, enabled, active_from, active_until) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rule_type, keywords, response, priority, enabled, active_from, active_until),
    )
    conn.commit()
    conn.close()


def test_prompt_with_no_rules(db_path):
    from engine.prompt_builder import build_system_prompt
    prompt = build_system_prompt(db_path)
    assert "Wiersma Consulting" in prompt
    assert "Professional and friendly" in prompt


def test_prompt_with_active_rules(db_path):
    from engine.prompt_builder import build_system_prompt
    _add_rule(db_path, "topic", "book, publication", "Recommend the Amazon link.")
    _add_rule(db_path, "info", "address", "We are at 123 Main St.")
    prompt = build_system_prompt(db_path)
    assert "Amazon link" in prompt
    assert "123 Main St" in prompt


def test_prompt_excludes_disabled_rules(db_path):
    from engine.prompt_builder import build_system_prompt
    _add_rule(db_path, "topic", "book", "Active rule.", enabled=True)
    _add_rule(db_path, "topic", "secret", "Disabled rule.", enabled=False)
    prompt = build_system_prompt(db_path)
    assert "Active rule" in prompt
    assert "Disabled rule" not in prompt


def test_prompt_excludes_expired_rules(db_path):
    from engine.prompt_builder import build_system_prompt
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    _add_rule(db_path, "vacation", "", "Old vacation.", active_from=last_week, active_until=yesterday)
    prompt = build_system_prompt(db_path)
    assert "Old vacation" not in prompt


def test_prompt_includes_active_date_range(db_path):
    from engine.prompt_builder import build_system_prompt
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    _add_rule(db_path, "vacation", "", "Current vacation.", active_from=yesterday, active_until=tomorrow)
    prompt = build_system_prompt(db_path)
    assert "Current vacation" in prompt


def test_prompt_null_dates_always_active(db_path):
    from engine.prompt_builder import build_system_prompt
    _add_rule(db_path, "info", "hours", "Open 9-5.", active_from=None, active_until=None)
    prompt = build_system_prompt(db_path)
    assert "Open 9-5" in prompt


def test_prompt_priority_ordering(db_path):
    from engine.prompt_builder import build_system_prompt
    _add_rule(db_path, "topic", "low", "Low priority rule.", priority=1)
    _add_rule(db_path, "topic", "high", "High priority rule.", priority=3)
    _add_rule(db_path, "topic", "mid", "Mid priority rule.", priority=2)
    prompt = build_system_prompt(db_path)
    high_pos = prompt.index("High priority")
    mid_pos = prompt.index("Mid priority")
    low_pos = prompt.index("Low priority")
    assert high_pos < mid_pos < low_pos


def test_active_vacation_detected(db_path):
    from engine.prompt_builder import get_active_vacation
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    _add_rule(db_path, "vacation", "", "We are on holiday.", active_from=yesterday, active_until=tomorrow)
    vacation = get_active_vacation(db_path)
    assert vacation is not None
    assert "holiday" in vacation["response"]


def test_no_active_vacation(db_path):
    from engine.prompt_builder import get_active_vacation
    vacation = get_active_vacation(db_path)
    assert vacation is None
