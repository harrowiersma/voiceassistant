import tempfile
import os
import pytest
from app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    yield app.test_client()
    os.unlink(db_path)


def test_sidebar_contains_nav_groups(client):
    response = client.get("/")
    html = response.data.decode()
    assert "Monitor" in html
    assert "Configure" in html
    assert "System" in html


def test_sidebar_contains_nav_links(client):
    response = client.get("/")
    html = response.data.decode()
    assert 'href="/"' in html  # Home
    assert 'href="/calls"' in html  # Call Log
    assert 'href="/persona"' in html
    assert 'href="/knowledge"' in html
    assert 'href="/availability"' in html
    assert 'href="/sip"' in html
    assert 'href="/ai"' in html
    assert 'href="/actions"' in html
    assert 'href="/system"' in html


def test_theme_toggle_exists(client):
    response = client.get("/")
    html = response.data.decode()
    assert "theme-toggle" in html


def test_pico_css_loaded(client):
    response = client.get("/")
    html = response.data.decode()
    assert "pico" in html.lower()
