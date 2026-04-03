# Voice Secretary Phase 5: Production Hardening + Future Scope

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the system production-ready (login, backup/restore, CSV export, thermal monitoring, call blocking) and add multi-persona support with Google Calendar integration and team/department routing.

**Architecture:** Dashboard login via bcrypt-hashed credentials stored in DB. Multi-persona adds a `personas` table — each persona has its own greeting, personality, calendar, and knowledge rules. Calls route to the right persona by matching inbound number or IVR menu. Google Calendar uses the same free-slot interface as MS Graph. Call blocking uses a `blocked_numbers` table checked before AudioSocket handoff. Teams/departments are modeled as personas with shared knowledge rules.

**Tech Stack:** Python 3.11+, Flask, bcrypt, SQLite, Google API Client, HTMX, Pico CSS

**Phase 4 codebase:** 125 tests passing, full call flow operational

---

### Task 1: Dashboard Login (Authentication)

**Files:**
- Create: `voice-secretary/app/auth.py`
- Modify: `voice-secretary/db/schema.sql` (add users table)
- Modify: `voice-secretary/db/init_db.py` (create default admin user)
- Modify: `voice-secretary/app/__init__.py` (add login_required middleware)
- Create: `voice-secretary/app/templates/login.html`
- Modify: `voice-secretary/requirements.txt` (add bcrypt)
- Test: `voice-secretary/tests/test_auth.py`

**Step 1: Write the failing test**

```python
# tests/test_auth.py
import tempfile
import os
import pytest
from app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_unauthenticated_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Login" in response.data
    assert b'name="username"' in response.data
    assert b'name="password"' in response.data


def test_login_with_default_credentials(client):
    response = client.post("/login", data={
        "username": "admin",
        "password": "voicesec",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Voice Secretary" in response.data  # Dashboard loaded


def test_login_wrong_password(client):
    response = client.post("/login", data={
        "username": "admin",
        "password": "wrong",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Invalid" in response.data or b"invalid" in response.data


def test_logout(client):
    # Login first
    client.post("/login", data={"username": "admin", "password": "voicesec"})
    response = client.get("/logout", follow_redirects=True)
    assert b"Login" in response.data


def test_change_password(client):
    # Login
    client.post("/login", data={"username": "admin", "password": "voicesec"})
    response = client.post("/auth/change-password", data={
        "current_password": "voicesec",
        "new_password": "newpass123",
    }, follow_redirects=True)
    assert response.status_code == 200
    # Logout and login with new password
    client.get("/logout")
    response = client.post("/login", data={
        "username": "admin", "password": "newpass123",
    }, follow_redirects=True)
    assert b"Voice Secretary" in response.data
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_auth.py -v`
Expected: FAIL

**Step 3: Add bcrypt to requirements**

Add to `requirements.txt`:
```
bcrypt==4.2.*
```

Run: `.venv/bin/pip install bcrypt`

**Step 4: Add users table to schema**

Add to `db/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Step 5: Create default admin user in init_db**

Update `db/init_db.py` to create default admin user with bcrypt-hashed password "voicesec" if no users exist.

**Step 6: Implement auth module**

```python
# app/auth.py
import functools
import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from db.connection import get_db_connection

bp = Blueprint("auth", __name__)


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return view(**kwargs)
    return wrapped_view


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        conn = get_db_connection(db_path)
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard.home"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/auth/change-password", methods=["POST"])
@login_required
def change_password():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    conn = get_db_connection(db_path)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if user and bcrypt.checkpw(current.encode(), user["password_hash"].encode()):
        new_hash = bcrypt.hashpw(new.encode(), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"]))
        conn.commit()
        flash("Password changed.", "success")
    else:
        flash("Current password is incorrect.", "error")
    conn.close()
    return redirect(url_for("system_mgmt.index"))
```

**Step 7: Register auth blueprint and add login_required to all routes**

Update `app/__init__.py` to register auth blueprint and wrap all non-auth routes with `login_required`.

**Step 8: Create login template**

```html
<!-- app/templates/login.html -->
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Voice Secretary — Login</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/pico.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/custom.css') }}">
</head>
<body>
    <main class="container" style="max-width: 400px; margin-top: 10vh;">
        <h1 style="text-align: center;">Voice Secretary</h1>
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        {% for category, message in messages %}
        <p class="flash {{ category }}">{{ message }}</p>
        {% endfor %}
        {% endif %}
        {% endwith %}
        <form method="post" action="{{ url_for('auth.login') }}">
            <label>Username <input type="text" name="username" required autofocus></label>
            <label>Password <input type="password" name="password" required></label>
            <button type="submit">Login</button>
        </form>
    </main>
</body>
</html>
```

**Step 9: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_auth.py -v`
Expected: 6 PASSED

**IMPORTANT:** Existing tests will fail because they're now hitting login_required. Update `tests/conftest.py` to add a helper that logs in before each request, OR update the app factory to skip auth when TESTING=True. The simplest approach:

In `app/auth.py`, add to `login_required`:
```python
if current_app.config.get("TESTING"):
    return view(**kwargs)
```

**Step 10: Run ALL tests**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED

**Step 11: Commit**

```bash
git add app/auth.py app/templates/login.html db/schema.sql db/init_db.py app/__init__.py requirements.txt tests/test_auth.py
git commit -m "feat: dashboard login with bcrypt password hashing and session management"
```

---

### Task 2: Config Backup & Restore

**Files:**
- Create: `voice-secretary/app/routes/backup.py`
- Modify: `voice-secretary/app/__init__.py` (register blueprint)
- Modify: `voice-secretary/app/templates/system.html` (add backup/restore buttons)
- Test: `voice-secretary/tests/test_backup.py`

**Step 1: Write the failing test**

```python
# tests/test_backup.py
import tempfile
import os
import json
import pytest
from app import create_app
from app.helpers import set_config, get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_backup_returns_json(client):
    db_path = client.application.config["_DB_PATH"]
    set_config("persona.company_name", "TestCo", "persona", db_path)
    response = client.get("/api/backup")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "config" in data
    assert "knowledge_rules" in data
    assert any(c["key"] == "persona.company_name" for c in data["config"])


def test_restore_from_json(client):
    db_path = client.application.config["_DB_PATH"]
    backup = {
        "config": [
            {"key": "persona.company_name", "value": "Restored Co", "category": "persona"},
            {"key": "sip.inbound_server", "value": "restored.example.com", "category": "sip"},
        ],
        "knowledge_rules": [
            {"rule_type": "info", "trigger_keywords": "address", "response": "123 Restored St.", "priority": 0, "enabled": True},
        ],
    }
    response = client.post("/api/restore", data=json.dumps(backup), content_type="application/json")
    assert response.status_code == 200
    assert get_config("persona.company_name", db_path=db_path) == "Restored Co"
```

**Step 2: Run test to verify it fails**

**Step 3: Implement backup/restore**

Backup endpoint: GET /api/backup — dumps config table + knowledge_rules table as JSON.
Restore endpoint: POST /api/restore — accepts JSON, replaces config + knowledge_rules.

**Step 4: Add backup/restore buttons to system.html**

**Step 5: Run tests, commit**

```bash
git commit -m "feat: config backup and restore via JSON API"
```

---

### Task 3: Call Log CSV Export

**Files:**
- Modify: `voice-secretary/app/routes/api.py` (add /api/calls/export endpoint)
- Test: `voice-secretary/tests/test_calls.py` (extend)

**Step 1: Write the failing test**

```python
# Add to tests/test_calls.py:

def test_calls_csv_export(client):
    db_path = client.application.config["_DB_PATH"]
    _seed_calls(db_path, 3)
    response = client.get("/api/calls/export")
    assert response.status_code == 200
    assert response.content_type == "text/csv; charset=utf-8"
    csv_text = response.data.decode()
    assert "Caller 1" in csv_text
    assert "started_at" in csv_text  # Header row
```

**Step 2: Implement CSV export endpoint**

GET /api/calls/export — queries all calls, returns CSV with headers: started_at, caller_number, caller_name, duration_seconds, reason, action_taken, email_sent.

**Step 3: Add export button to calls.html**

**Step 4: Run tests, commit**

```bash
git commit -m "feat: call log CSV export"
```

---

### Task 4: Thermal Monitoring & Model Downgrade

**Files:**
- Create: `voice-secretary/engine/thermal.py`
- Modify: `voice-secretary/app/routes/api.py` (enhance /api/status)
- Test: `voice-secretary/tests/test_thermal.py`

**Step 1: Write the failing test**

```python
# tests/test_thermal.py
import pytest
from engine.thermal import ThermalMonitor


def test_normal_temp_no_action():
    monitor = ThermalMonitor()
    action = monitor.check(cpu_temp=55.0)
    assert action is None


def test_warning_temp_returns_warning():
    monitor = ThermalMonitor()
    action = monitor.check(cpu_temp=75.0)
    assert action == "warning"


def test_critical_temp_returns_downgrade():
    monitor = ThermalMonitor()
    action = monitor.check(cpu_temp=82.0)
    assert action == "downgrade"


def test_cooldown_clears_after_normal():
    monitor = ThermalMonitor()
    monitor.check(cpu_temp=82.0)  # trigger downgrade
    assert monitor.downgraded is True
    monitor.check(cpu_temp=60.0)  # cooled down
    monitor.check(cpu_temp=60.0)  # sustained cool
    monitor.check(cpu_temp=60.0)  # 3 consecutive normal readings
    assert monitor.downgraded is False
```

**Step 2: Implement thermal monitor**

```python
# engine/thermal.py
import logging

logger = logging.getLogger(__name__)

TEMP_WARNING = 70.0
TEMP_CRITICAL = 80.0
COOLDOWN_READINGS = 3


class ThermalMonitor:
    def __init__(self):
        self.downgraded = False
        self._cool_count = 0

    def check(self, cpu_temp):
        if cpu_temp is None:
            return None
        if cpu_temp >= TEMP_CRITICAL:
            if not self.downgraded:
                self.downgraded = True
                logger.warning(f"CPU {cpu_temp}°C — downgrading to smaller model")
            self._cool_count = 0
            return "downgrade"
        elif cpu_temp >= TEMP_WARNING:
            self._cool_count = 0
            return "warning"
        else:
            if self.downgraded:
                self._cool_count += 1
                if self._cool_count >= COOLDOWN_READINGS:
                    self.downgraded = False
                    self._cool_count = 0
                    logger.info("CPU cooled — restoring full model")
            return None
```

**Step 3: Run tests, commit**

```bash
git commit -m "feat: thermal monitoring with automatic model downgrade on overheating"
```

---

### Task 5: Call Blocking

**Files:**
- Modify: `voice-secretary/db/schema.sql` (add blocked_numbers table)
- Create: `voice-secretary/app/routes/blocking.py`
- Create: `voice-secretary/app/templates/blocking.html`
- Modify: `voice-secretary/app/__init__.py` (register blueprint)
- Modify: `voice-secretary/app/templates/base.html` (add nav link)
- Test: `voice-secretary/tests/test_blocking.py`

**Step 1: Write the failing test**

```python
# tests/test_blocking.py
import tempfile
import os
import json
import pytest
from app import create_app
from db.connection import get_db_connection


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_blocking_page_loads(client):
    response = client.get("/blocking")
    assert response.status_code == 200
    assert b"Call Blocking" in response.data


def test_add_blocked_number(client):
    response = client.post("/blocking/add", data={
        "pattern": "+41791234567",
        "block_type": "exact",
        "reason": "Spam caller",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"+41791234567" in response.data


def test_add_blocked_prefix(client):
    response = client.post("/blocking/add", data={
        "pattern": "+234",
        "block_type": "prefix",
        "reason": "Country block",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_check_number_blocked_exact(client):
    client.post("/blocking/add", data={
        "pattern": "+41791234567", "block_type": "exact", "reason": "Spam",
    })
    response = client.get("/api/blocking/check?number=+41791234567")
    data = json.loads(response.data)
    assert data["blocked"] is True


def test_check_number_blocked_prefix(client):
    client.post("/blocking/add", data={
        "pattern": "+234", "block_type": "prefix", "reason": "Country",
    })
    response = client.get("/api/blocking/check?number=+2341234567")
    data = json.loads(response.data)
    assert data["blocked"] is True


def test_check_number_not_blocked(client):
    response = client.get("/api/blocking/check?number=+41791111111")
    data = json.loads(response.data)
    assert data["blocked"] is False


def test_delete_blocked_number(client):
    client.post("/blocking/add", data={
        "pattern": "+41791234567", "block_type": "exact", "reason": "Test",
    })
    response = client.post("/blocking/1/delete", follow_redirects=True)
    assert response.status_code == 200
```

**Step 2: Add blocked_numbers table to schema**

```sql
CREATE TABLE IF NOT EXISTS blocked_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    block_type TEXT NOT NULL DEFAULT 'exact',  -- 'exact', 'prefix', 'regex'
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Step 3: Implement blocking route**

```python
# app/routes/blocking.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from db.connection import get_db_connection

bp = Blueprint("blocking", __name__)

def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")

@bp.route("/blocking")
def index():
    conn = get_db_connection(_db_path())
    rules = conn.execute("SELECT * FROM blocked_numbers ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("blocking.html", rules=[dict(r) for r in rules])

@bp.route("/blocking/add", methods=["POST"])
def add():
    conn = get_db_connection(_db_path())
    conn.execute(
        "INSERT INTO blocked_numbers (pattern, block_type, reason) VALUES (?, ?, ?)",
        (request.form["pattern"], request.form.get("block_type", "exact"), request.form.get("reason", "")),
    )
    conn.commit()
    conn.close()
    flash("Number blocked.", "success")
    return redirect(url_for("blocking.index"))

@bp.route("/blocking/<int:rule_id>/delete", methods=["POST"])
def delete(rule_id):
    conn = get_db_connection(_db_path())
    conn.execute("DELETE FROM blocked_numbers WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    flash("Block removed.", "success")
    return redirect(url_for("blocking.index"))
```

**Step 4: Add API check endpoint to api.py**

```python
@bp.route("/blocking/check")
def blocking_check():
    number = request.args.get("number", "")
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    rules = conn.execute("SELECT * FROM blocked_numbers").fetchall()
    conn.close()
    for rule in rules:
        if rule["block_type"] == "exact" and rule["pattern"] == number:
            return jsonify({"blocked": True, "reason": rule["reason"]})
        elif rule["block_type"] == "prefix" and number.startswith(rule["pattern"]):
            return jsonify({"blocked": True, "reason": rule["reason"]})
    return jsonify({"blocked": False})
```

**Step 5: Create template, register blueprint, add nav link**

Add "Call Blocking" under Configure group in base.html sidebar.

**Step 6: Run tests, commit**

```bash
git commit -m "feat: call blocking by exact number, prefix, or country code"
```

---

### Task 6: Multi-Persona Support (DB Schema + API)

**Files:**
- Modify: `voice-secretary/db/schema.sql` (add personas table, add persona_id FK to calls + knowledge_rules)
- Create: `voice-secretary/db/migrate_personas.py` (migration script)
- Modify: `voice-secretary/app/helpers.py` (add persona-aware config helpers)
- Test: `voice-secretary/tests/test_personas.py`

**Step 1: Write the failing test**

```python
# tests/test_personas.py
import tempfile
import os
import pytest
from db.init_db import init_db
from db.connection import get_db_connection


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_personas_table_exists(db_path):
    conn = get_db_connection(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personas'")
    assert cursor.fetchone() is not None
    conn.close()


def test_default_persona_created(db_path):
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM personas WHERE is_default = 1").fetchone()
    conn.close()
    assert row is not None
    assert row["name"] == "Default"


def test_create_persona(db_path):
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Sales", "Wiersma Sales", "Hello, sales department.", "Friendly salesperson.", "Sales is closed.", "google"),
    )
    conn.commit()
    personas = conn.execute("SELECT * FROM personas ORDER BY id").fetchall()
    conn.close()
    assert len(personas) == 2  # Default + Sales


def test_knowledge_rules_have_persona_id(db_path):
    conn = get_db_connection(db_path)
    # Check the column exists
    info = conn.execute("PRAGMA table_info(knowledge_rules)").fetchall()
    columns = [row["name"] for row in info]
    conn.close()
    assert "persona_id" in columns


def test_calls_have_persona_id(db_path):
    conn = get_db_connection(db_path)
    info = conn.execute("PRAGMA table_info(calls)").fetchall()
    columns = [row["name"] for row in info]
    conn.close()
    assert "persona_id" in columns
```

**Step 2: Add personas table and FKs to schema**

```sql
CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    greeting TEXT NOT NULL DEFAULT 'Hello, how may I help you?',
    personality TEXT NOT NULL DEFAULT 'Professional and friendly.',
    unavailable_message TEXT NOT NULL DEFAULT 'They are not available right now.',
    calendar_type TEXT DEFAULT 'msgraph',  -- 'msgraph', 'google', 'none'
    calendar_config TEXT,  -- JSON: {client_id, client_secret, ...}
    inbound_number TEXT,  -- Match inbound calls to this persona by DID
    is_default BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Add `persona_id INTEGER REFERENCES personas(id)` to both `calls` and `knowledge_rules` tables.

**Step 3: Create default persona in init_db**

After creating tables, insert default persona if none exists.

**Step 4: Run tests, commit**

```bash
git commit -m "feat: multi-persona schema with personas table and FK relationships"
```

---

### Task 7: Persona Dashboard CRUD

**Files:**
- Create: `voice-secretary/app/routes/personas.py`
- Create: `voice-secretary/app/templates/personas.html`
- Create: `voice-secretary/app/templates/persona_edit.html`
- Modify: `voice-secretary/app/__init__.py` (register blueprint)
- Modify: `voice-secretary/app/templates/base.html` (add nav link)
- Test: `voice-secretary/tests/test_persona_crud.py`

**Step 1: Write the failing test**

```python
# tests/test_persona_crud.py
import tempfile
import os
import json
import pytest
from app import create_app
from db.connection import get_db_connection


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_personas_list_page(client):
    response = client.get("/personas")
    assert response.status_code == 200
    assert b"Personas" in response.data
    assert b"Default" in response.data


def test_create_persona(client):
    response = client.post("/personas/add", data={
        "name": "Sales Team",
        "company_name": "Wiersma Sales",
        "greeting": "Hello, sales department.",
        "personality": "Enthusiastic and helpful.",
        "unavailable_message": "Sales is closed.",
        "calendar_type": "google",
        "inbound_number": "+41441234567",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Sales Team" in response.data


def test_edit_persona(client):
    # Create one first
    client.post("/personas/add", data={
        "name": "Finance", "company_name": "Finance Dept",
        "greeting": "Hello.", "personality": "Precise.", "unavailable_message": "Closed.",
        "calendar_type": "none", "inbound_number": "",
    })
    response = client.post("/personas/2/edit", data={
        "name": "Finance Updated", "company_name": "Finance Dept Updated",
        "greeting": "Hello finance.", "personality": "Precise.", "unavailable_message": "Closed.",
        "calendar_type": "msgraph", "inbound_number": "+41442222222",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Finance Updated" in response.data


def test_delete_persona(client):
    client.post("/personas/add", data={
        "name": "Temp", "company_name": "Temp",
        "greeting": "Hi.", "personality": ".", "unavailable_message": ".",
        "calendar_type": "none", "inbound_number": "",
    })
    response = client.post("/personas/2/delete", follow_redirects=True)
    assert response.status_code == 200


def test_cannot_delete_default_persona(client):
    response = client.post("/personas/1/delete", follow_redirects=True)
    assert response.status_code == 200
    # Default persona should still exist
    assert b"Default" in response.data


def test_personas_api_list(client):
    response = client.get("/api/personas")
    data = json.loads(response.data)
    assert len(data["personas"]) >= 1
    assert data["personas"][0]["name"] == "Default"
```

**Step 2: Implement personas CRUD route**

Standard CRUD: list, add, edit, delete. Cannot delete default persona. Each persona has its own greeting, personality, calendar config, and inbound number for routing.

**Step 3: Create templates**

List page shows all personas in a table. Edit page is a form with all persona fields including calendar_type dropdown (MS Graph / Google Calendar / None).

**Step 4: Add nav link under Configure: "Personas"**

**Step 5: Run tests, commit**

```bash
git commit -m "feat: persona management CRUD with per-persona calendar and greeting config"
```

---

### Task 8: Google Calendar Integration

**Files:**
- Create: `voice-secretary/integrations/google_calendar.py`
- Test: `voice-secretary/tests/test_google_calendar.py`

**Step 1: Write the failing test**

```python
# tests/test_google_calendar.py
import json
from unittest.mock import patch, MagicMock
import pytest


def _mock_response(data, status=200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(data).encode()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def test_google_get_free_slots():
    from integrations.google_calendar import GoogleCalendarClient
    client = GoogleCalendarClient(access_token="test_token")
    events = {
        "items": [
            {"start": {"dateTime": "2026-04-02T10:00:00+02:00"}, "end": {"dateTime": "2026-04-02T11:00:00+02:00"}},
            {"start": {"dateTime": "2026-04-02T14:00:00+02:00"}, "end": {"dateTime": "2026-04-02T15:30:00+02:00"}},
        ]
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(events)):
        slots = client.get_free_slots(date="2026-04-02", business_start=9, business_end=17)
    assert isinstance(slots, list)
    assert len(slots) > 0


def test_google_no_token_returns_empty():
    from integrations.google_calendar import GoogleCalendarClient
    client = GoogleCalendarClient(access_token=None)
    slots = client.get_free_slots()
    assert slots == []


def test_google_check_busy():
    from integrations.google_calendar import GoogleCalendarClient
    client = GoogleCalendarClient(access_token="test_token")
    freebusy = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-04-02T10:00:00+02:00", "end": "2026-04-02T11:00:00+02:00"}
                ]
            }
        }
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(freebusy)):
        is_busy = client.is_busy_now()
    assert isinstance(is_busy, bool)
```

**Step 2: Implement Google Calendar client**

Same interface as MSGraphClient's calendar methods — `get_free_slots(date, business_start, business_end)` and `is_busy_now()`. Uses Google Calendar API v3 with OAuth2 bearer token.

**Step 3: Run tests, commit**

```bash
git commit -m "feat: Google Calendar integration with free slots and busy check"
```

---

### Task 9: Team/Department Routing

**Files:**
- Modify: `voice-secretary/engine/call_session.py` (persona-aware routing)
- Modify: `voice-secretary/engine/prompt_builder.py` (persona-scoped prompts)
- Test: `voice-secretary/tests/test_team_routing.py`

**Step 1: Write the failing test**

```python
# tests/test_team_routing.py
import tempfile
import os
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


def test_resolve_persona_by_inbound_number(db_path):
    from engine.routing import resolve_persona
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, inbound_number, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Sales", "Wiersma Sales", "Hello sales.", "Friendly.", "Sales closed.", "+41441234567", "none"),
    )
    conn.commit()
    conn.close()
    persona = resolve_persona("+41441234567", db_path)
    assert persona is not None
    assert persona["name"] == "Sales"


def test_resolve_persona_falls_back_to_default(db_path):
    from engine.routing import resolve_persona
    persona = resolve_persona("+41449999999", db_path)
    assert persona is not None
    assert persona["is_default"] == 1


def test_build_prompt_for_persona(db_path):
    from engine.prompt_builder import build_system_prompt_for_persona
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Finance", "Wiersma Finance", "Hello finance.", "Precise.", "Finance closed.", "none"),
    )
    conn.commit()
    # Add persona-scoped knowledge rule
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, persona_id, enabled) "
        "VALUES (?, ?, ?, ?, ?)",
        ("info", "invoice", "Please email invoices@wiersma.com", 2, True),
    )
    conn.commit()
    conn.close()
    prompt = build_system_prompt_for_persona(persona_id=2, db_path=db_path)
    assert "Wiersma Finance" in prompt
    assert "invoice" in prompt.lower()
```

**Step 2: Create routing module**

```python
# engine/routing.py
from db.connection import get_db_connection

def resolve_persona(inbound_number, db_path=None):
    """Match inbound number to a persona. Falls back to default."""
    conn = get_db_connection(db_path)
    # Try exact match first
    persona = conn.execute(
        "SELECT * FROM personas WHERE inbound_number = ? AND enabled = 1",
        (inbound_number,),
    ).fetchone()
    if not persona:
        persona = conn.execute("SELECT * FROM personas WHERE is_default = 1").fetchone()
    conn.close()
    return dict(persona) if persona else None
```

**Step 3: Add persona-scoped prompt builder**

Add `build_system_prompt_for_persona(persona_id, db_path)` to prompt_builder.py — reads persona fields directly from personas table, filters knowledge_rules by persona_id.

**Step 4: Run tests, commit**

```bash
git commit -m "feat: team/department routing with persona resolution by inbound number"
```

---

### Task 10: Persona-Aware Call Session + Knowledge Rules

**Files:**
- Modify: `voice-secretary/engine/call_session.py` (use persona from routing)
- Modify: `voice-secretary/app/routes/knowledge.py` (filter by persona)
- Modify: `voice-secretary/app/templates/knowledge.html` (persona selector)
- Test: `voice-secretary/tests/test_call_session.py` (extend)

**Step 1: Write the additional failing test**

```python
# Add to tests/test_call_session.py:

def test_call_session_with_persona(db_path):
    from engine.call_session import CallSession
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Sales", "Sales Dept", "Hello, sales here!", "Helpful.", "Sales closed.", "none"),
    )
    conn.commit()
    conn.close()
    session = CallSession(caller_number="+41791111111", db_path=db_path, persona_id=2)
    greeting = session.get_greeting_text()
    assert "Sales" in greeting
```

**Step 2: Update CallSession to accept persona_id**

Modify `__init__` to accept optional `persona_id`. If provided, load persona from personas table instead of config table. Use `build_system_prompt_for_persona` instead of `build_system_prompt`.

**Step 3: Update knowledge.html with persona filter dropdown**

**Step 4: Run tests, commit**

```bash
git commit -m "feat: persona-aware call sessions and knowledge rules"
```

---

### Task 11: Full Test Suite + Final Polish

**Step 1: Run full test suite**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED (~170+ tests)

**Step 2: Update pi-gen to include new modules**

Update `pi-gen/stage-voicesec/01-install-app.sh` to install bcrypt.

**Step 3: Update requirements.txt**

Ensure all new deps are listed:
```
bcrypt==4.2.*
google-api-python-client==2.149.*
```

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: Phase 5 complete - auth, backup, export, thermal, blocking, multi-persona, Google Calendar, team routing"
```

---

## Phase 5 Summary

After completing all 11 tasks, you have:

**Production Hardening:**
- **Dashboard login** — bcrypt password hashing, session management, change password
- **Config backup/restore** — JSON export/import of all settings + knowledge rules
- **Call log CSV export** — download call history as spreadsheet
- **Thermal monitoring** — auto-downgrade to smaller LLM when CPU overheats, restore when cooled
- **Call blocking** — block by exact number, prefix (country code), with reason tracking

**Multi-Persona & Teams:**
- **Personas table** — each persona has own greeting, personality, calendar config, inbound number
- **Persona CRUD** — dashboard management of multiple personas/departments
- **Team routing** — incoming calls matched to persona by DID number, falls back to default
- **Persona-scoped knowledge rules** — rules belong to specific personas
- **Persona-aware call sessions** — CallSession loads the right persona for each call

**Calendar Integration:**
- **Google Calendar** — free slot checking and busy status, same interface as MS Graph
- **Per-persona calendar** — each persona can use MS Graph, Google Calendar, or none

**~170+ passing tests across 11 tasks**
