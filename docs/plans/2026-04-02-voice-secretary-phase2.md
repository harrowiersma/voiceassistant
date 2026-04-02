# Voice Secretary Phase 2: SIP + AI Engine + Pi Image

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a flashable Raspberry Pi OS image (.img) with the complete voice secretary stack: Asterisk PBX, Vosk STT, Ollama LLM, Piper TTS, plus all dashboard screens fleshed out with full CRUD. Flash the SD card, boot, and configure everything via the web dashboard.

**Architecture:** pi-gen (official Pi image builder) running via Docker on Mac creates a custom image. The Flask app, AI engine, and Asterisk are installed into custom pi-gen stages. systemd services auto-start everything on boot. Dashboard screens use HTMX for real-time config persistence to SQLite via the existing helpers.

**Tech Stack:** pi-gen + Docker (image build), Asterisk (SIP), Vosk (STT), Ollama + Llama 3.2 (LLM), Piper (TTS), Flask + HTMX + Pico CSS (dashboard), systemd (process management)

**Design reference:** `/Users/harrowiersma/Documents/CLAUDE/assistant/develop.md` (full spec)

**Phase 1 codebase:** `/Users/harrowiersma/Documents/CLAUDE/assistant/voice-secretary/` (Flask app, DB, 25 tests)

---

### Task 1: Pi Image Build Infrastructure (pi-gen + Docker)

**Files:**
- Create: `voice-secretary/pi-gen/config`
- Create: `voice-secretary/pi-gen/stage-voicesec/00-packages`
- Create: `voice-secretary/pi-gen/stage-voicesec/01-install-app.sh`
- Create: `voice-secretary/pi-gen/stage-voicesec/02-install-asterisk.sh`
- Create: `voice-secretary/pi-gen/stage-voicesec/03-install-ai.sh`
- Create: `voice-secretary/pi-gen/stage-voicesec/04-services.sh`
- Create: `voice-secretary/pi-gen/build.sh`
- Create: `voice-secretary/systemd/voice-secretary-web.service`
- Create: `voice-secretary/systemd/voice-secretary-engine.service`

**Step 1: Create pi-gen config**

```bash
mkdir -p voice-secretary/pi-gen/stage-voicesec
```

```
# pi-gen/config
IMG_NAME=voice-secretary
RELEASE=bookworm
TARGET_HOSTNAME=voicesec
FIRST_USER_NAME=voicesec
FIRST_USER_PASS=voicesec
ENABLE_SSH=1
LOCALE_DEFAULT=en_US.UTF-8
KEYBOARD_KEYMAP=us
TIMEZONE_DEFAULT=Europe/Zurich
STAGE_LIST="stage0 stage1 stage2 stage-voicesec"
```

**Step 2: Create package list**

```
# pi-gen/stage-voicesec/00-packages
python3
python3-pip
python3-venv
python3-dev
asterisk
asterisk-core-sounds-en
sqlite3
git
curl
build-essential
libportaudio2
libsndfile1
ffmpeg
```

**Step 3: Create app installation script**

```bash
#!/bin/bash -e
# pi-gen/stage-voicesec/01-install-app.sh
# Install the Flask web dashboard

on_chroot << 'CHEOF'
# Create app directory
mkdir -p /opt/voice-secretary
CHEOF

# Copy application files into the image
install -d "${ROOTFS_DIR}/opt/voice-secretary"
cp -r /path/to/voice-secretary/app "${ROOTFS_DIR}/opt/voice-secretary/"
cp -r /path/to/voice-secretary/db "${ROOTFS_DIR}/opt/voice-secretary/"
cp /path/to/voice-secretary/requirements.txt "${ROOTFS_DIR}/opt/voice-secretary/"
cp /path/to/voice-secretary/Makefile "${ROOTFS_DIR}/opt/voice-secretary/"

on_chroot << 'CHEOF'
cd /opt/voice-secretary
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "from db.init_db import init_db; init_db()"
chown -R voicesec:voicesec /opt/voice-secretary
CHEOF
```

**Step 4: Create Asterisk installation script**

```bash
#!/bin/bash -e
# pi-gen/stage-voicesec/02-install-asterisk.sh
# Configure Asterisk for SIP trunk + AudioSocket

on_chroot << 'CHEOF'
# Enable Asterisk service
systemctl enable asterisk

# Create config directories
mkdir -p /etc/asterisk/voicesec

# The Flask app will generate pjsip.conf and extensions.conf
# from Jinja2 templates when the user configures SIP via dashboard
CHEOF
```

**Step 5: Create AI engine installation script**

```bash
#!/bin/bash -e
# pi-gen/stage-voicesec/03-install-ai.sh
# Install Ollama, Vosk model, and Piper

on_chroot << 'CHEOF'
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Install Vosk model (English, small - 50MB)
mkdir -p /opt/voice-secretary/models/vosk
cd /opt/voice-secretary/models/vosk
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
mv vosk-model-small-en-us-0.15 model
rm vosk-model-small-en-us-0.15.zip

# Install Piper TTS
pip3 install piper-tts

# Download Piper English voice
mkdir -p /opt/voice-secretary/models/piper
cd /opt/voice-secretary/models/piper
curl -LO https://github.com/rhasspy/piper/releases/download/v1.2.0/voice-en-us-amy-medium.onnx
curl -LO https://github.com/rhasspy/piper/releases/download/v1.2.0/voice-en-us-amy-medium.onnx.json

# Install Vosk Python bindings
/opt/voice-secretary/.venv/bin/pip install vosk

# Pre-pull Ollama model (will run on first boot instead if too slow during build)
# ollama pull llama3.2:1b
CHEOF
```

**Step 6: Create systemd services**

```ini
# systemd/voice-secretary-web.service
[Unit]
Description=Voice Secretary Web Dashboard
After=network.target

[Service]
Type=simple
User=voicesec
WorkingDirectory=/opt/voice-secretary
ExecStart=/opt/voice-secretary/.venv/bin/python -m app
Restart=on-failure
RestartSec=5
Environment=FLASK_ENV=production

[Install]
WantedBy=multi-user.target
```

```ini
# systemd/voice-secretary-engine.service
[Unit]
Description=Voice Secretary AI Engine
After=network.target asterisk.service ollama.service
Wants=asterisk.service ollama.service

[Service]
Type=simple
User=voicesec
WorkingDirectory=/opt/voice-secretary
ExecStart=/opt/voice-secretary/.venv/bin/python -m engine
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
#!/bin/bash -e
# pi-gen/stage-voicesec/04-services.sh

# Copy systemd services
install -m 644 /path/to/systemd/voice-secretary-web.service "${ROOTFS_DIR}/etc/systemd/system/"
install -m 644 /path/to/systemd/voice-secretary-engine.service "${ROOTFS_DIR}/etc/systemd/system/"

on_chroot << 'CHEOF'
systemctl enable voice-secretary-web.service
systemctl enable voice-secretary-engine.service
systemctl enable ollama.service
CHEOF
```

**Step 7: Create build script**

```bash
#!/bin/bash
# pi-gen/build.sh
# Build the Voice Secretary Pi image using Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Building Voice Secretary Pi image..."

# Clone pi-gen if not present
if [ ! -d "$SCRIPT_DIR/pi-gen" ]; then
    git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "$SCRIPT_DIR/pi-gen"
fi

# Copy our config
cp "$SCRIPT_DIR/config" "$SCRIPT_DIR/pi-gen/config"

# Copy our custom stage
cp -r "$SCRIPT_DIR/stage-voicesec" "$SCRIPT_DIR/pi-gen/stage-voicesec"

# Skip stages 3-5 (we only need lite + our stage)
touch "$SCRIPT_DIR/pi-gen/stage3/SKIP" "$SCRIPT_DIR/pi-gen/stage4/SKIP" "$SCRIPT_DIR/pi-gen/stage5/SKIP"

# Export image at stage2 and our custom stage
touch "$SCRIPT_DIR/pi-gen/stage-voicesec/EXPORT_IMAGE"

# Build via Docker
cd "$SCRIPT_DIR/pi-gen"
./build-docker.sh

echo "Image built! Find it in: $SCRIPT_DIR/pi-gen/deploy/"
```

**Step 8: Commit**

```bash
git add pi-gen/ systemd/
git commit -m "feat: pi-gen image build infrastructure with Docker support"
```

---

### Task 2: SIP Configuration Screen (Form + Asterisk Config Generation)

**Files:**
- Create: `voice-secretary/config/__init__.py`
- Create: `voice-secretary/config/asterisk/pjsip.conf.j2`
- Create: `voice-secretary/config/asterisk/extensions.conf.j2`
- Create: `voice-secretary/config/defaults.py`
- Modify: `voice-secretary/app/routes/sip.py`
- Modify: `voice-secretary/app/templates/sip.html`
- Create: `voice-secretary/app/templates/partials/sip_status.html`
- Test: `voice-secretary/tests/test_sip.py`

**Step 1: Write the failing test**

```python
# tests/test_sip.py
import tempfile
import os
import json
import pytest
from app import create_app
from app.helpers import get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_sip_page_has_form(client):
    response = client.get("/sip")
    html = response.data.decode()
    assert 'name="sip.inbound_server"' in html
    assert 'name="sip.inbound_username"' in html
    assert 'name="sip.inbound_password"' in html
    assert 'name="sip.inbound_port"' in html
    assert 'name="sip.forward_number"' in html


def test_sip_save_inbound(client):
    response = client.post("/sip/save", data={
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"saved" in response.data.lower() or b"Settings saved" in response.data


def test_sip_save_persists_to_db(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/sip/save", data={
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
    })
    assert get_config("sip.inbound_server", db_path=db_path) == "sip.example.com"
    assert get_config("sip.forward_number", db_path=db_path) == "+41791234567"


def test_sip_form_prefills_saved_values(client):
    client.post("/sip/save", data={
        "sip.inbound_server": "saved.example.com",
        "sip.inbound_username": "saveduser",
        "sip.inbound_password": "savedpass",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
    })
    response = client.get("/sip")
    html = response.data.decode()
    assert 'value="saved.example.com"' in html
    assert 'value="saveduser"' in html


def test_sip_outbound_optional(client):
    response = client.post("/sip/save", data={
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
        # No outbound fields
    }, follow_redirects=True)
    assert response.status_code == 200


def test_asterisk_config_generation(client):
    from config.asterisk_gen import render_pjsip_conf, render_extensions_conf
    config = {
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
    }
    pjsip = render_pjsip_conf(config)
    assert "sip.example.com" in pjsip
    assert "user123" in pjsip
    assert "inbound-trunk" in pjsip

    extensions = render_extensions_conf(config)
    assert "+41791234567" in extensions
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_sip.py -v`
Expected: FAIL (form fields don't exist)

**Step 3: Create config defaults and Asterisk templates**

```python
# config/__init__.py
# (empty)
```

```python
# config/defaults.py
SIP_DEFAULTS = {
    "sip.inbound_server": "",
    "sip.inbound_username": "",
    "sip.inbound_password": "",
    "sip.inbound_port": "5060",
    "sip.outbound_server": "",
    "sip.outbound_username": "",
    "sip.outbound_password": "",
    "sip.outbound_port": "5060",
    "sip.forward_number": "",
}
```

```python
# config/asterisk_gen.py
import os
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "asterisk")

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    keep_trailing_newline=True,
)


def render_pjsip_conf(config):
    template = _env.get_template("pjsip.conf.j2")
    return template.render(**config)


def render_extensions_conf(config):
    template = _env.get_template("extensions.conf.j2")
    return template.render(**config)
```

```jinja2
; config/asterisk/pjsip.conf.j2
; Auto-generated by Voice Secretary dashboard — do not edit manually

; === Inbound SIP Trunk ===
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0

[inbound-trunk]
type=registration
transport=transport-udp
outbound_auth=inbound-trunk-auth
server_uri=sip:{{ sip_inbound_server | default('', true) }}:{{ sip_inbound_port | default('5060', true) }}
client_uri=sip:{{ sip_inbound_username | default('', true) }}@{{ sip_inbound_server | default('', true) }}

[inbound-trunk-auth]
type=auth
auth_type=userpass
username={{ sip_inbound_username | default('', true) }}
password={{ sip_inbound_password | default('', true) }}

[inbound-trunk-aor]
type=aor
contact=sip:{{ sip_inbound_server | default('', true) }}:{{ sip_inbound_port | default('5060', true) }}

[inbound-trunk-endpoint]
type=endpoint
transport=transport-udp
context=inbound
disallow=all
allow=ulaw
allow=alaw
outbound_auth=inbound-trunk-auth
aors=inbound-trunk-aor
from_user={{ sip_inbound_username | default('', true) }}
from_domain={{ sip_inbound_server | default('', true) }}

{% if sip_outbound_server %}
; === Outbound SIP Trunk (optional) ===
[outbound-trunk]
type=registration
transport=transport-udp
outbound_auth=outbound-trunk-auth
server_uri=sip:{{ sip_outbound_server }}:{{ sip_outbound_port | default('5060', true) }}
client_uri=sip:{{ sip_outbound_username }}@{{ sip_outbound_server }}

[outbound-trunk-auth]
type=auth
auth_type=userpass
username={{ sip_outbound_username }}
password={{ sip_outbound_password }}

[outbound-trunk-aor]
type=aor
contact=sip:{{ sip_outbound_server }}:{{ sip_outbound_port | default('5060', true) }}

[outbound-trunk-endpoint]
type=endpoint
transport=transport-udp
context=outbound
disallow=all
allow=ulaw
allow=alaw
outbound_auth=outbound-trunk-auth
aors=outbound-trunk-aor
{% endif %}
```

```jinja2
; config/asterisk/extensions.conf.j2
; Auto-generated by Voice Secretary dashboard — do not edit manually

[general]
static=yes
writeprotect=no

[inbound]
; Incoming calls -> Voice Secretary AI via AudioSocket
exten => _X.,1,NoOp(Incoming call from ${CALLERID(num)})
 same => n,Answer()
 same => n,AudioSocket(127.0.0.1:9092)
 same => n,Hangup()

[outbound]
; Outbound calls (forwarding, test calls)
{% if sip_outbound_server %}
exten => _+X.,1,NoOp(Outbound call to ${EXTEN} via outbound trunk)
 same => n,Dial(PJSIP/${EXTEN}@outbound-trunk-endpoint,30)
 same => n,Hangup()
{% else %}
exten => _+X.,1,NoOp(Outbound call to ${EXTEN} via inbound trunk)
 same => n,Dial(PJSIP/${EXTEN}@inbound-trunk-endpoint,30)
 same => n,Hangup()
{% endif %}

[forward]
; Forward call to user's phone
exten => forward,1,NoOp(Forwarding call to {{ sip_forward_number | default('', true) }})
 same => n,Dial(PJSIP/{{ sip_forward_number | default('', true) }}@{% if sip_outbound_server %}outbound-trunk-endpoint{% else %}inbound-trunk-endpoint{% endif %},30)
 same => n,Hangup()
```

**Step 4: Update SIP route with form handling**

```python
# app/routes/sip.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.helpers import get_config, set_config, get_configs_by_category
from config.defaults import SIP_DEFAULTS

bp = Blueprint("sip", __name__)

SIP_FIELDS = [
    "sip.inbound_server", "sip.inbound_username", "sip.inbound_password", "sip.inbound_port",
    "sip.outbound_server", "sip.outbound_username", "sip.outbound_password", "sip.outbound_port",
    "sip.forward_number",
]


@bp.route("/sip")
def index():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    values = {}
    for key in SIP_FIELDS:
        values[key] = get_config(key, default=SIP_DEFAULTS.get(key, ""), db_path=db_path)
    return render_template("sip.html", values=values)


@bp.route("/sip/save", methods=["POST"])
def save():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    for key in SIP_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "sip", db_path)
    flash("Settings saved successfully.", "success")
    return redirect(url_for("sip.index"))
```

**Step 5: Update SIP template with form**

```html
<!-- app/templates/sip.html -->
{% extends "base.html" %}
{% block page_title %}SIP Settings{% endblock %}
{% block content %}

{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="flash-messages">
    {% for category, message in messages %}
    <p class="flash {{ category }}">{{ message }}</p>
    {% endfor %}
</div>
{% endif %}
{% endwith %}

<form method="post" action="{{ url_for('sip.save') }}">
    <h2>Inbound SIP Trunk</h2>
    <p class="help-text">Your SIP provider credentials for receiving incoming calls.</p>

    <div class="grid">
        <label>
            Server
            <input type="text" name="sip.inbound_server" value="{{ values['sip.inbound_server'] }}" placeholder="sip.provider.com" required>
        </label>
        <label>
            Port
            <input type="text" name="sip.inbound_port" value="{{ values['sip.inbound_port'] }}" placeholder="5060">
        </label>
    </div>
    <div class="grid">
        <label>
            Username
            <input type="text" name="sip.inbound_username" value="{{ values['sip.inbound_username'] }}" required>
        </label>
        <label>
            Password
            <input type="password" name="sip.inbound_password" value="{{ values['sip.inbound_password'] }}" required>
        </label>
    </div>

    <h2>Outbound SIP Trunk <small>(optional)</small></h2>
    <p class="help-text">Separate account for outbound calls (forwarding, test calls). If empty, inbound trunk is used.</p>

    <div class="grid">
        <label>
            Server
            <input type="text" name="sip.outbound_server" value="{{ values['sip.outbound_server'] }}" placeholder="sip.provider.com">
        </label>
        <label>
            Port
            <input type="text" name="sip.outbound_port" value="{{ values['sip.outbound_port'] }}" placeholder="5060">
        </label>
    </div>
    <div class="grid">
        <label>
            Username
            <input type="text" name="sip.outbound_username" value="{{ values['sip.outbound_username'] }}">
        </label>
        <label>
            Password
            <input type="password" name="sip.outbound_password" value="{{ values['sip.outbound_password'] }}">
        </label>
    </div>

    <h2>Call Forwarding</h2>
    <label>
        Forward calls to (your mobile number)
        <input type="tel" name="sip.forward_number" value="{{ values['sip.forward_number'] }}" placeholder="+41791234567" required>
    </label>

    <button type="submit">Save SIP Settings</button>
</form>
{% endblock %}
```

**Step 6: Install jinja2 (already in requirements) and run tests**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_sip.py -v`
Expected: ALL PASSED

**Step 7: Commit**

```bash
git add config/ app/routes/sip.py app/templates/sip.html tests/test_sip.py
git commit -m "feat: SIP configuration screen with form persistence and Asterisk config generation"
```

---

### Task 3: Persona Editor Screen

**Files:**
- Modify: `voice-secretary/app/routes/persona.py`
- Modify: `voice-secretary/app/templates/persona.html`
- Test: `voice-secretary/tests/test_persona.py`

**Step 1: Write the failing test**

```python
# tests/test_persona.py
import tempfile
import os
import pytest
from app import create_app
from app.helpers import get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_persona_page_has_form(client):
    response = client.get("/persona")
    html = response.data.decode()
    assert 'name="persona.company_name"' in html
    assert 'name="persona.greeting"' in html
    assert 'name="persona.personality"' in html
    assert 'name="persona.unavailable_message"' in html


def test_persona_save(client):
    response = client.post("/persona/save", data={
        "persona.company_name": "Wiersma Consulting",
        "persona.greeting": "Hello, you've reached Wiersma Consulting. How may I help you?",
        "persona.personality": "Professional, friendly, concise.",
        "persona.unavailable_message": "I'm sorry, they're not available right now. May I take a message?",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_persona_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/persona/save", data={
        "persona.company_name": "Wiersma Consulting",
        "persona.greeting": "Hello from Wiersma!",
        "persona.personality": "Friendly",
        "persona.unavailable_message": "Not available",
    })
    assert get_config("persona.company_name", db_path=db_path) == "Wiersma Consulting"
    assert get_config("persona.greeting", db_path=db_path) == "Hello from Wiersma!"


def test_persona_prefills(client):
    client.post("/persona/save", data={
        "persona.company_name": "TestCo",
        "persona.greeting": "Hello TestCo",
        "persona.personality": "Warm",
        "persona.unavailable_message": "Sorry",
    })
    response = client.get("/persona")
    html = response.data.decode()
    assert "TestCo" in html
    assert "Hello TestCo" in html
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_persona.py -v`
Expected: FAIL

**Step 3: Update persona route**

```python
# app/routes/persona.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.helpers import get_config, set_config

bp = Blueprint("persona", __name__)

PERSONA_FIELDS = [
    "persona.company_name",
    "persona.greeting",
    "persona.personality",
    "persona.unavailable_message",
]

PERSONA_DEFAULTS = {
    "persona.company_name": "",
    "persona.greeting": "Hello, you've reached {company}. How may I help you today?",
    "persona.personality": "You are a professional, friendly, and concise virtual secretary. You speak clearly and help callers efficiently. Always be polite and helpful.",
    "persona.unavailable_message": "I'm sorry, they're not available at the moment. Would you like to leave a message? I'll make sure they get it.",
}


@bp.route("/persona")
def index():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    values = {}
    for key in PERSONA_FIELDS:
        values[key] = get_config(key, default=PERSONA_DEFAULTS.get(key, ""), db_path=db_path)
    return render_template("persona.html", values=values)


@bp.route("/persona/save", methods=["POST"])
def save():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    for key in PERSONA_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "persona", db_path)
    flash("Persona settings saved.", "success")
    return redirect(url_for("persona.index"))
```

**Step 4: Update persona template**

```html
<!-- app/templates/persona.html -->
{% extends "base.html" %}
{% block page_title %}Persona{% endblock %}
{% block content %}

{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="flash-messages">
    {% for category, message in messages %}
    <p class="flash {{ category }}">{{ message }}</p>
    {% endfor %}
</div>
{% endif %}
{% endwith %}

<form method="post" action="{{ url_for('persona.save') }}">
    <label>
        Company / Person Name
        <input type="text" name="persona.company_name" value="{{ values['persona.company_name'] }}" placeholder="Wiersma Consulting">
        <small>Used in the greeting and throughout the conversation.</small>
    </label>

    <label>
        Greeting Message
        <textarea name="persona.greeting" rows="3" placeholder="Hello, you've reached...">{{ values['persona.greeting'] }}</textarea>
        <small>What callers hear first. Use {company} to insert the company name.</small>
    </label>

    <label>
        Personality Prompt
        <textarea name="persona.personality" rows="5" placeholder="You are a professional...">{{ values['persona.personality'] }}</textarea>
        <small>Instructions for the AI's tone and behavior during calls.</small>
    </label>

    <label>
        "Not Available" Message
        <textarea name="persona.unavailable_message" rows="3" placeholder="I'm sorry, they're not available...">{{ values['persona.unavailable_message'] }}</textarea>
        <small>What callers hear when you're busy or away.</small>
    </label>

    <button type="submit">Save Persona</button>
</form>
{% endblock %}
```

**Step 5: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_persona.py -v`
Expected: 4 PASSED

**Step 6: Commit**

```bash
git add app/routes/persona.py app/templates/persona.html tests/test_persona.py
git commit -m "feat: persona editor with config persistence"
```

---

### Task 4: Knowledge Base CRUD

**Files:**
- Modify: `voice-secretary/app/routes/knowledge.py`
- Modify: `voice-secretary/app/templates/knowledge.html`
- Create: `voice-secretary/app/templates/partials/knowledge_row.html`
- Test: `voice-secretary/tests/test_knowledge.py`

**Step 1: Write the failing test**

```python
# tests/test_knowledge.py
import tempfile
import os
import json
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


def test_knowledge_page_loads(client):
    response = client.get("/knowledge")
    assert response.status_code == 200
    assert b"Knowledge Base" in response.data


def test_knowledge_page_has_add_button(client):
    response = client.get("/knowledge")
    html = response.data.decode()
    assert "Add Rule" in html


def test_create_topic_rule(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "topic",
        "trigger_keywords": "book, publication, author",
        "response": "You can find the book on Amazon.",
        "active_from": "",
        "active_until": "",
        "priority": "0",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"book" in response.data.lower()


def test_create_vacation_rule_with_dates(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "vacation",
        "trigger_keywords": "",
        "response": "Our office is closed for the holidays.",
        "active_from": "2026-12-24",
        "active_until": "2027-01-02",
        "priority": "10",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_create_rule_missing_response_fails(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "topic",
        "trigger_keywords": "test",
        "response": "",
        "active_from": "",
        "active_until": "",
        "priority": "0",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"required" in response.data.lower() or b"error" in response.data.lower()


def test_toggle_rule(client):
    # Create a rule
    client.post("/knowledge/add", data={
        "rule_type": "info",
        "trigger_keywords": "address",
        "response": "We are at 123 Main St.",
        "active_from": "",
        "active_until": "",
        "priority": "0",
    })
    # Toggle it
    response = client.post("/knowledge/1/toggle", follow_redirects=True)
    assert response.status_code == 200


def test_delete_rule(client):
    # Create a rule
    client.post("/knowledge/add", data={
        "rule_type": "info",
        "trigger_keywords": "test",
        "response": "Test response.",
        "active_from": "",
        "active_until": "",
        "priority": "0",
    })
    # Delete it
    response = client.post("/knowledge/1/delete", follow_redirects=True)
    assert response.status_code == 200


def test_list_rules_api(client):
    client.post("/knowledge/add", data={
        "rule_type": "topic",
        "trigger_keywords": "book",
        "response": "Amazon link.",
        "active_from": "",
        "active_until": "",
        "priority": "0",
    })
    response = client.get("/api/knowledge/rules")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data["rules"]) == 1
    assert data["rules"][0]["rule_type"] == "topic"
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_knowledge.py -v`
Expected: FAIL

**Step 3: Update knowledge route with full CRUD**

```python
# app/routes/knowledge.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from db.connection import get_db_connection

bp = Blueprint("knowledge", __name__)


def _get_db(app=None):
    if app is None:
        app = current_app
    return app.config.get("_DB_PATH") or app.config.get("DATABASE")


@bp.route("/knowledge")
def index():
    conn = get_db_connection(_get_db())
    rules = conn.execute(
        "SELECT * FROM knowledge_rules ORDER BY priority DESC, id"
    ).fetchall()
    conn.close()
    return render_template("knowledge.html", rules=[dict(r) for r in rules])


@bp.route("/knowledge/add", methods=["POST"])
def add():
    response_text = request.form.get("response", "").strip()
    if not response_text:
        flash("Response text is required.", "error")
        return redirect(url_for("knowledge.index"))

    conn = get_db_connection(_get_db())
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, active_from, active_until, priority) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            request.form.get("rule_type", "topic"),
            request.form.get("trigger_keywords", ""),
            response_text,
            request.form.get("active_from") or None,
            request.form.get("active_until") or None,
            int(request.form.get("priority", 0)),
        ),
    )
    conn.commit()
    conn.close()
    flash("Rule added.", "success")
    return redirect(url_for("knowledge.index"))


@bp.route("/knowledge/<int:rule_id>/toggle", methods=["POST"])
def toggle(rule_id):
    conn = get_db_connection(_get_db())
    conn.execute(
        "UPDATE knowledge_rules SET enabled = NOT enabled, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (rule_id,),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("knowledge.index"))


@bp.route("/knowledge/<int:rule_id>/delete", methods=["POST"])
def delete(rule_id):
    conn = get_db_connection(_get_db())
    conn.execute("DELETE FROM knowledge_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    flash("Rule deleted.", "success")
    return redirect(url_for("knowledge.index"))
```

**Step 4: Add API endpoint for rules (used by prompt_builder later)**

Add to `app/routes/api.py`:

```python
# Add at the top:
from db.connection import get_db_connection

# Add this route:
@bp.route("/knowledge/rules")
def knowledge_rules():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    rules = conn.execute(
        "SELECT * FROM knowledge_rules WHERE enabled = 1 ORDER BY priority DESC, id"
    ).fetchall()
    conn.close()
    return jsonify({"rules": [dict(r) for r in rules]})
```

**Step 5: Update knowledge template with rules table + add form**

```html
<!-- app/templates/knowledge.html -->
{% extends "base.html" %}
{% block page_title %}Knowledge Base{% endblock %}
{% block content %}

{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="flash-messages">
    {% for category, message in messages %}
    <p class="flash {{ category }}">{{ message }}</p>
    {% endfor %}
</div>
{% endif %}
{% endwith %}

<details>
    <summary role="button" class="outline">Add Rule</summary>
    <form method="post" action="{{ url_for('knowledge.add') }}">
        <div class="grid">
            <label>
                Type
                <select name="rule_type">
                    <option value="topic">Topic Response</option>
                    <option value="redirect">Redirect</option>
                    <option value="vacation">Vacation / Closure</option>
                    <option value="info">Info</option>
                    <option value="custom">Custom</option>
                </select>
            </label>
            <label>
                Priority
                <input type="number" name="priority" value="0" min="0" max="100">
            </label>
        </div>
        <label>
            Trigger Keywords
            <input type="text" name="trigger_keywords" placeholder="book, publication, author">
            <small>Comma-separated. Leave empty for vacation rules (applies globally).</small>
        </label>
        <label>
            Response Text
            <textarea name="response" rows="3" placeholder="What the secretary should say..." required></textarea>
        </label>
        <div class="grid">
            <label>
                Active From
                <input type="date" name="active_from">
            </label>
            <label>
                Active Until
                <input type="date" name="active_until">
            </label>
        </div>
        <button type="submit">Add Rule</button>
    </form>
</details>

{% if rules %}
<figure>
<table>
    <thead>
        <tr>
            <th>Enabled</th>
            <th>Type</th>
            <th>Keywords</th>
            <th>Response</th>
            <th>Date Range</th>
            <th>Priority</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for rule in rules %}
        <tr>
            <td>
                <form method="post" action="{{ url_for('knowledge.toggle', rule_id=rule.id) }}" style="display:inline;">
                    <button type="submit" class="outline {{ 'secondary' if not rule.enabled }}" style="padding:0.2rem 0.5rem; font-size:0.75rem;">
                        {{ "On" if rule.enabled else "Off" }}
                    </button>
                </form>
            </td>
            <td><mark>{{ rule.rule_type }}</mark></td>
            <td>{{ rule.trigger_keywords or "—" }}</td>
            <td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ rule.response }}</td>
            <td>
                {% if rule.active_from %}{{ rule.active_from }}{% endif %}
                {% if rule.active_from and rule.active_until %} → {% endif %}
                {% if rule.active_until %}{{ rule.active_until }}{% endif %}
                {% if not rule.active_from and not rule.active_until %}Always{% endif %}
            </td>
            <td>{{ rule.priority }}</td>
            <td>
                <form method="post" action="{{ url_for('knowledge.delete', rule_id=rule.id) }}" style="display:inline;">
                    <button type="submit" class="outline secondary" style="padding:0.2rem 0.5rem; font-size:0.75rem;">Delete</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</figure>
{% else %}
<div class="empty-state">
    <p>No rules yet.</p>
    <p>Add your first rule to teach your secretary what to say.</p>
</div>
{% endif %}
{% endblock %}
```

**Step 6: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_knowledge.py -v`
Expected: 8 PASSED

**Step 7: Commit**

```bash
git add app/routes/knowledge.py app/routes/api.py app/templates/knowledge.html tests/test_knowledge.py
git commit -m "feat: knowledge base CRUD with rules table, toggle, and delete"
```

---

### Task 5: AI Settings Screen

**Files:**
- Modify: `voice-secretary/app/routes/ai.py`
- Modify: `voice-secretary/app/templates/ai.html`
- Test: `voice-secretary/tests/test_ai_settings.py`

**Step 1: Write the failing test**

```python
# tests/test_ai_settings.py
import tempfile
import os
import pytest
from app import create_app
from app.helpers import get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_ai_page_has_form(client):
    response = client.get("/ai")
    html = response.data.decode()
    assert 'name="ai.stt_model"' in html
    assert 'name="ai.llm_model"' in html
    assert 'name="ai.tts_voice"' in html
    assert 'name="ai.response_timeout"' in html
    assert 'name="ai.max_call_duration"' in html


def test_ai_save(client):
    response = client.post("/ai/save", data={
        "ai.stt_model": "vosk-small",
        "ai.llm_model": "llama3.2:1b",
        "ai.tts_voice": "en-us-amy-medium",
        "ai.response_timeout": "10",
        "ai.max_call_duration": "300",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_ai_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/ai/save", data={
        "ai.stt_model": "vosk-small",
        "ai.llm_model": "llama3.2:1b",
        "ai.tts_voice": "en-us-amy-medium",
        "ai.response_timeout": "10",
        "ai.max_call_duration": "300",
    })
    assert get_config("ai.llm_model", db_path=db_path) == "llama3.2:1b"
    assert get_config("ai.response_timeout", db_path=db_path) == "10"
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_ai_settings.py -v`
Expected: FAIL

**Step 3: Update AI route**

```python
# app/routes/ai.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.helpers import get_config, set_config

bp = Blueprint("ai", __name__)

AI_FIELDS = [
    "ai.stt_model", "ai.llm_model", "ai.tts_voice",
    "ai.response_timeout", "ai.max_call_duration",
]

AI_DEFAULTS = {
    "ai.stt_model": "vosk-small",
    "ai.llm_model": "llama3.2:1b",
    "ai.tts_voice": "en-us-amy-medium",
    "ai.response_timeout": "10",
    "ai.max_call_duration": "300",
}


@bp.route("/ai")
def index():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    values = {}
    for key in AI_FIELDS:
        values[key] = get_config(key, default=AI_DEFAULTS.get(key, ""), db_path=db_path)
    return render_template("ai.html", values=values)


@bp.route("/ai/save", methods=["POST"])
def save():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    for key in AI_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "ai", db_path)
    flash("AI settings saved.", "success")
    return redirect(url_for("ai.index"))
```

**Step 4: Update AI template**

```html
<!-- app/templates/ai.html -->
{% extends "base.html" %}
{% block page_title %}AI Settings{% endblock %}
{% block content %}

{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="flash-messages">
    {% for category, message in messages %}
    <p class="flash {{ category }}">{{ message }}</p>
    {% endfor %}
</div>
{% endif %}
{% endwith %}

<form method="post" action="{{ url_for('ai.save') }}">
    <h2>Speech-to-Text (Vosk)</h2>
    <label>
        STT Model
        <select name="ai.stt_model">
            <option value="vosk-small" {{ 'selected' if values['ai.stt_model'] == 'vosk-small' }}>Small (50MB, faster)</option>
            <option value="vosk-large" {{ 'selected' if values['ai.stt_model'] == 'vosk-large' }}>Large (1.8GB, more accurate)</option>
        </select>
    </label>

    <h2>Language Model (Ollama)</h2>
    <label>
        LLM Model
        <select name="ai.llm_model">
            <option value="llama3.2:1b" {{ 'selected' if values['ai.llm_model'] == 'llama3.2:1b' }}>Llama 3.2 1B (fast, ~1.5GB RAM)</option>
            <option value="llama3.2:3b" {{ 'selected' if values['ai.llm_model'] == 'llama3.2:3b' }}>Llama 3.2 3B (better, ~3GB RAM)</option>
        </select>
    </label>

    <h2>Text-to-Speech (Piper)</h2>
    <label>
        TTS Voice
        <select name="ai.tts_voice">
            <option value="en-us-amy-medium" {{ 'selected' if values['ai.tts_voice'] == 'en-us-amy-medium' }}>Amy (US English, medium)</option>
            <option value="en-gb-alan-medium" {{ 'selected' if values['ai.tts_voice'] == 'en-gb-alan-medium' }}>Alan (British English, medium)</option>
        </select>
    </label>

    <h2>Timeouts</h2>
    <div class="grid">
        <label>
            Response Timeout (seconds)
            <input type="number" name="ai.response_timeout" value="{{ values['ai.response_timeout'] }}" min="5" max="30">
            <small>Max time to wait for LLM response before fallback.</small>
        </label>
        <label>
            Max Call Duration (seconds)
            <input type="number" name="ai.max_call_duration" value="{{ values['ai.max_call_duration'] }}" min="60" max="600">
            <small>Automatically end calls after this duration.</small>
        </label>
    </div>

    <button type="submit">Save AI Settings</button>
</form>
{% endblock %}
```

**Step 5: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_ai_settings.py -v`
Expected: 3 PASSED

**Step 6: Commit**

```bash
git add app/routes/ai.py app/templates/ai.html tests/test_ai_settings.py
git commit -m "feat: AI settings screen with model selection and timeout config"
```

---

### Task 6: Prompt Builder (Engine Module)

**Files:**
- Create: `voice-secretary/engine/__init__.py`
- Create: `voice-secretary/engine/prompt_builder.py`
- Test: `voice-secretary/tests/test_prompt_builder.py`

**Step 1: Write the failing test**

```python
# tests/test_prompt_builder.py
import tempfile
import os
import sqlite3
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
        "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, priority, enabled, active_from, active_until) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_prompt_builder.py -v`
Expected: FAIL (engine module doesn't exist)

**Step 3: Implement prompt_builder**

```python
# engine/__init__.py
# (empty)
```

```python
# engine/prompt_builder.py
from datetime import datetime
from db.connection import get_db_connection
from app.helpers import get_config


def _get_active_rules(db_path):
    """Get all enabled, date-valid knowledge rules ordered by priority."""
    conn = get_db_connection(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rules = conn.execute(
        """
        SELECT * FROM knowledge_rules
        WHERE enabled = 1
          AND (active_from IS NULL OR active_from <= ?)
          AND (active_until IS NULL OR active_until >= ?)
        ORDER BY priority DESC, id
        """,
        (now, now),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rules]


def get_active_vacation(db_path):
    """Check for an active vacation/closure rule. Returns the rule dict or None."""
    conn = get_db_connection(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rule = conn.execute(
        """
        SELECT * FROM knowledge_rules
        WHERE enabled = 1
          AND rule_type = 'vacation'
          AND active_from IS NOT NULL AND active_from <= ?
          AND active_until IS NOT NULL AND active_until >= ?
        ORDER BY priority DESC
        LIMIT 1
        """,
        (now, now),
    ).fetchone()
    conn.close()
    return dict(rule) if rule else None


def build_system_prompt(db_path):
    """Assemble the LLM system prompt from persona config + active knowledge rules."""
    company = get_config("persona.company_name", default="", db_path=db_path)
    personality = get_config("persona.personality", default="", db_path=db_path)
    greeting = get_config("persona.greeting", default="", db_path=db_path).replace("{company}", company)
    unavailable = get_config("persona.unavailable_message", default="", db_path=db_path)

    rules = _get_active_rules(db_path)

    prompt_parts = [
        f"You are a virtual secretary for {company}.",
        f"Personality: {personality}",
        f"Greeting (say this first): {greeting}",
        f"When the person is unavailable, say: {unavailable}",
    ]

    if rules:
        prompt_parts.append("\n## Knowledge Rules (follow these instructions):")
        for rule in rules:
            rule_line = f"- [{rule['rule_type'].upper()}]"
            if rule["trigger_keywords"]:
                rule_line += f" When caller mentions: {rule['trigger_keywords']}."
            rule_line += f" {rule['response']}"
            prompt_parts.append(rule_line)

    return "\n".join(prompt_parts)
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_prompt_builder.py -v`
Expected: 9 PASSED

**Step 5: Commit**

```bash
git add engine/ tests/test_prompt_builder.py
git commit -m "feat: prompt builder assembles LLM system prompt from persona + knowledge rules"
```

---

### Task 7: Engine Wrappers (LLM, STT, TTS stubs with interface)

**Files:**
- Create: `voice-secretary/engine/llm.py`
- Create: `voice-secretary/engine/stt.py`
- Create: `voice-secretary/engine/tts.py`
- Test: `voice-secretary/tests/test_engine_stubs.py`

These are stubbed wrappers with the correct interface. They check if the actual tool is available and fall back gracefully. Full integration happens on the Pi.

**Step 1: Write the failing test**

```python
# tests/test_engine_stubs.py
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
        assert "not available" in response.lower() or "sorry" in response.lower()


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
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_engine_stubs.py -v`
Expected: FAIL

**Step 3: Implement engine wrappers**

```python
# engine/llm.py
import json
import logging

logger = logging.getLogger(__name__)

FALLBACK_RESPONSE = "I'm sorry, the AI assistant is not available right now. Please leave a message after the tone."


class LLMClient:
    def __init__(self, model="llama3.2:1b", base_url="http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self._available = None

    def is_available(self):
        if self._available is not None:
            return self._available
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False
        return self._available

    def chat(self, user_message, system_prompt="", history=None):
        if not self.is_available():
            logger.warning("Ollama not available, returning fallback response")
            return FALLBACK_RESPONSE

        try:
            import urllib.request
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": user_message})

            data = json.dumps({
                "model": self.model,
                "messages": messages,
                "stream": False,
            }).encode()

            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                return result["message"]["content"]
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            return FALLBACK_RESPONSE
```

```python
# engine/stt.py
import logging

logger = logging.getLogger(__name__)


class STTEngine:
    def __init__(self, model_path=None):
        self.model_path = model_path
        self._recognizer = None

    def is_available(self):
        try:
            import vosk
            return self.model_path is not None
        except ImportError:
            return False

    def _load_model(self):
        if self._recognizer is None and self.is_available():
            import vosk
            model = vosk.Model(self.model_path)
            self._recognizer = vosk.KaldiRecognizer(model, 16000)
        return self._recognizer

    def transcribe(self, audio_bytes):
        """Transcribe audio bytes (16kHz, 16-bit, mono PCM). Returns text or empty string."""
        recognizer = self._load_model()
        if recognizer is None:
            logger.warning("Vosk not available, cannot transcribe")
            return ""
        import json
        recognizer.AcceptWaveform(audio_bytes)
        result = json.loads(recognizer.FinalResult())
        return result.get("text", "")
```

```python
# engine/tts.py
import logging
import subprocess

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(self, voice="en-us-amy-medium", model_dir="/opt/voice-secretary/models/piper"):
        self.voice = voice
        self.model_dir = model_dir

    def is_available(self):
        try:
            result = subprocess.run(["piper", "--version"], capture_output=True, timeout=3)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def synthesize(self, text):
        """Convert text to audio bytes (WAV format). Returns bytes or None."""
        if not self.is_available():
            logger.warning("Piper not available, cannot synthesize")
            return None

        try:
            model_path = f"{self.model_dir}/voice-{self.voice}.onnx"
            result = subprocess.run(
                ["piper", "--model", model_path, "--output_raw"],
                input=text.encode(),
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout
            logger.error(f"Piper error: {result.stderr.decode()}")
            return None
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_engine_stubs.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add engine/ tests/test_engine_stubs.py
git commit -m "feat: engine wrappers for LLM (Ollama), STT (Vosk), and TTS (Piper)"
```

---

### Task 8: Update Home Status with Real Service Detection

**Files:**
- Modify: `voice-secretary/app/routes/api.py`
- Test: `voice-secretary/tests/test_api_status.py` (extend)

**Step 1: Write the additional failing test**

Add to `tests/test_api_status.py`:

```python
def test_api_status_ai_section_has_all_fields(client):
    response = client.get("/api/status")
    data = json.loads(response.data)
    ai = data["ai"]
    assert "vosk" in ai
    assert "ollama" in ai
    assert "piper" in ai
    # Values should be strings
    assert isinstance(ai["vosk"], str)
    assert isinstance(ai["ollama"], str)
    assert isinstance(ai["piper"], str)


def test_api_status_asterisk_section(client):
    response = client.get("/api/status")
    data = json.loads(response.data)
    ast = data["asterisk"]
    assert "status" in ast
    assert "active_calls" in ast
    assert isinstance(ast["active_calls"], int)
```

**Step 2: Run test to verify current tests still pass**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_api_status.py -v`
Expected: ALL PASSED (these tests should already pass with current implementation)

**Step 3: Update API status to actually check services**

Update `app/routes/api.py` to add real service detection:

```python
# Add to app/routes/api.py - replace the existing status function

def _check_ollama():
    """Check if Ollama is running."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return "running"
    except Exception:
        pass
    return "not_running"


def _check_asterisk():
    """Check if Asterisk is running."""
    try:
        result = subprocess.run(
            ["asterisk", "-rx", "core show version"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return "running"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "not_running"


def _check_vosk():
    """Check if Vosk model is available."""
    try:
        import vosk
        return "loaded"
    except ImportError:
        return "not_installed"


def _check_piper():
    """Check if Piper is available."""
    try:
        result = subprocess.run(
            ["piper", "--version"],
            capture_output=True, timeout=2
        )
        return "loaded" if result.returncode == 0 else "not_loaded"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "not_installed"
```

Then update the `status()` route to call these functions instead of returning hardcoded values.

**Step 4: Run all tests**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED

**Step 5: Commit**

```bash
git add app/routes/api.py tests/test_api_status.py
git commit -m "feat: home status now detects real service availability"
```

---

### Task 9: System Screen (Service Control + Log Viewer)

**Files:**
- Modify: `voice-secretary/app/routes/system.py`
- Modify: `voice-secretary/app/templates/system.html`
- Test: `voice-secretary/tests/test_system.py`

**Step 1: Write the failing test**

```python
# tests/test_system.py
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


def test_system_page_has_service_controls(client):
    response = client.get("/system")
    html = response.data.decode()
    assert "Asterisk" in html
    assert "Ollama" in html
    assert "Voice Secretary" in html


def test_system_page_has_health_info(client):
    response = client.get("/system")
    html = response.data.decode()
    assert "uptime" in html.lower() or "health" in html.lower() or "System" in html
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_system.py -v`
Expected: FAIL (current template is just a stub)

**Step 3: Update system route and template**

```python
# app/routes/system.py
import subprocess
from flask import Blueprint, render_template

bp = Blueprint("system_mgmt", __name__)

SERVICES = [
    {"name": "Asterisk PBX", "service": "asterisk"},
    {"name": "Ollama LLM", "service": "ollama"},
    {"name": "Voice Secretary Engine", "service": "voice-secretary-engine"},
    {"name": "Voice Secretary Web", "service": "voice-secretary-web"},
]


def _service_status(service_name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


@bp.route("/system")
def index():
    services = []
    for svc in SERVICES:
        status = _service_status(svc["service"])
        services.append({**svc, "status": status})
    return render_template("system.html", services=services)
```

```html
<!-- app/templates/system.html -->
{% extends "base.html" %}
{% block page_title %}System{% endblock %}
{% block content %}

<h2>Services</h2>
<figure>
<table>
    <thead>
        <tr>
            <th>Service</th>
            <th>Status</th>
        </tr>
    </thead>
    <tbody>
        {% for svc in services %}
        <tr>
            <td>{{ svc.name }}</td>
            <td>
                <span class="status-badge">
                    <span class="status-dot {{ 'ok' if svc.status == 'active' else 'error' if svc.status == 'failed' else 'idle' }}"></span>
                    {{ svc.status }}
                </span>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</figure>

<h2>System Health</h2>
<div class="card-grid"
     hx-get="/api/status"
     hx-trigger="load, every 10s"
     hx-swap="innerHTML"
     hx-target="#system-health">
    <div id="system-health">
        <article class="data-card">
            <h3>Loading...</h3>
        </article>
    </div>
</div>

<script>
document.addEventListener("htmx:beforeSwap", function(evt) {
    if (evt.detail.target.id === "system-health") {
        try {
            const data = JSON.parse(evt.detail.xhr.responseText);
            const s = data.system;
            const cpuText = s.cpu_temp !== null ? s.cpu_temp + "\u00b0C" : "N/A";
            evt.detail.serverResponse = `
                <article class="data-card">
                    <h3>CPU Temperature</h3>
                    <div class="value">${cpuText}</div>
                </article>
                <article class="data-card">
                    <h3>RAM Usage</h3>
                    <div class="value">${s.ram_used_mb} / ${s.ram_total_mb} MB</div>
                </article>
                <article class="data-card">
                    <h3>Disk Usage</h3>
                    <div class="value">${s.disk_used_pct}%</div>
                </article>
            `;
        } catch(e) {}
    }
});
</script>
{% endblock %}
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_system.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add app/routes/system.py app/templates/system.html tests/test_system.py
git commit -m "feat: system screen with service status and health monitoring"
```

---

### Task 10: Full Test Suite + Update Makefile for Image Build

**Step 1: Run full test suite**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED (~40+ tests)

**Step 2: Update Makefile with image build target**

Add to `Makefile`:

```makefile
image:
	cd pi-gen && bash build.sh

image-clean:
	rm -rf pi-gen/pi-gen pi-gen/pi-gen/deploy
```

**Step 3: Update requirements.txt with engine dependencies**

```
# requirements.txt
flask==3.1.*
flask-socketio==5.4.*
python-socketio[client]==5.12.*
eventlet==0.37.*
jinja2==3.1.*
cryptography==44.*
pytest==8.3.*
vosk==0.3.*
```

Note: `piper-tts` and `ollama` are system packages installed via pi-gen, not pip.

**Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "chore: Phase 2 complete - dashboard screens, engine wrappers, Pi image infrastructure"
```

---

## Phase 2 Summary

After completing all 10 tasks, you have:

- **Pi image build infrastructure** (pi-gen + Docker, custom stage with all dependencies)
- **SIP Configuration screen** (form with inbound/outbound trunk config, Asterisk config generation via Jinja2)
- **Persona editor** (company name, greeting, personality, unavailable message)
- **Knowledge Base CRUD** (rules table with add/toggle/delete, type/keywords/response/dates)
- **AI Settings screen** (STT/LLM/TTS model selection, timeout config)
- **Prompt builder** (assembles system prompt from persona + active knowledge rules, vacation detection)
- **Engine wrappers** (LLM/STT/TTS with graceful fallback when tools not installed)
- **System screen** (service status, health monitoring)
- **Real service detection** (status endpoint checks actual service availability)
- **systemd services** (auto-start on boot)
- **~40+ passing tests**

**Next steps:**
1. Build the Pi image: `make image` (requires Docker)
2. Flash to SD card with Pi Imager
3. Boot Pi, open dashboard at `http://voicesec.local:8080`
4. Configure SIP trunk, persona, knowledge rules via dashboard
5. Phase 3: Orchestrator (AudioSocket bridge, call flow, forwarding, message-taking)
