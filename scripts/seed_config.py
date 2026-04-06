#!/usr/bin/env python3
"""Seed the Voice Secretary database from a .env file.

Reads environment variables (or .env file) and populates the SQLite config table.
Run this on first boot to pre-configure the system without using the dashboard.

Usage:
    python scripts/seed_config.py                    # reads .env in project root
    python scripts/seed_config.py /path/to/.env      # reads specific .env file
    ENV_FILE=/path/.env python scripts/seed_config.py # via environment variable
"""
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from db.init_db import init_db, DEFAULT_DB_PATH
from app.helpers import set_config


# Mapping: ENV_VAR -> (config_key, category)
CONFIG_MAP = {
    # SIP
    "SIP_INBOUND_SERVER": ("sip.inbound_server", "sip"),
    "SIP_INBOUND_PORT": ("sip.inbound_port", "sip"),
    "SIP_INBOUND_USERNAME": ("sip.inbound_username", "sip"),
    "SIP_INBOUND_PASSWORD": ("sip.inbound_password", "sip"),
    "SIP_OUTBOUND_SERVER": ("sip.outbound_server", "sip"),
    "SIP_OUTBOUND_PORT": ("sip.outbound_port", "sip"),
    "SIP_OUTBOUND_USERNAME": ("sip.outbound_username", "sip"),
    "SIP_OUTBOUND_PASSWORD": ("sip.outbound_password", "sip"),
    "SIP_STUN_SERVER": ("sip.stun_server", "sip"),
    "SIP_FORWARD_NUMBER": ("sip.forward_number", "sip"),
    "SIP_EXTENSION_1_NAME": ("sip.extension_1_name", "sip"),
    "SIP_EXTENSION_1_PASSWORD": ("sip.extension_1_password", "sip"),
    "SIP_EXTENSION_2_NAME": ("sip.extension_2_name", "sip"),
    "SIP_EXTENSION_2_PASSWORD": ("sip.extension_2_password", "sip"),
    "SIP_EXTENSION_3_NAME": ("sip.extension_3_name", "sip"),
    "SIP_EXTENSION_3_PASSWORD": ("sip.extension_3_password", "sip"),
    # Persona
    "PERSONA_COMPANY_NAME": ("persona.company_name", "persona"),
    "PERSONA_GREETING": ("persona.greeting", "persona"),
    "PERSONA_PERSONALITY": ("persona.personality", "persona"),
    "PERSONA_UNAVAILABLE_MESSAGE": ("persona.unavailable_message", "persona"),
    # MS Graph
    "GRAPH_CLIENT_ID": ("graph.client_id", "graph"),
    "GRAPH_CLIENT_SECRET": ("graph.client_secret", "graph"),
    "GRAPH_TENANT_ID": ("graph.tenant_id", "graph"),
    # SMTP
    "SMTP_SERVER": ("actions.smtp_server", "actions"),
    "SMTP_PORT": ("actions.smtp_port", "actions"),
    "SMTP_USERNAME": ("actions.smtp_username", "actions"),
    "SMTP_PASSWORD": ("actions.smtp_password", "actions"),
    "EMAIL_FROM": ("actions.email_from", "actions"),
    "EMAIL_TO": ("actions.email_to", "actions"),
    "NOTIFY_ON": ("actions.notify_on", "actions"),
    # Secret code word
    "SECRET_CODE_WORD": ("security.code_word", "security"),
    # Availability
    "AVAILABILITY_MANUAL_OVERRIDE": ("availability.manual_override", "availability"),
    "AVAILABILITY_BUSINESS_HOURS_START": ("availability.business_hours_start", "availability"),
    "AVAILABILITY_BUSINESS_HOURS_END": ("availability.business_hours_end", "availability"),
    "AVAILABILITY_ACTION_AVAILABLE": ("availability.action_available", "availability"),
    "AVAILABILITY_ACTION_BUSY": ("availability.action_busy", "availability"),
    "AVAILABILITY_ACTION_DND": ("availability.action_dnd", "availability"),
    "AVAILABILITY_ACTION_AWAY": ("availability.action_away", "availability"),
    # AI
    "AI_STT_MODEL": ("ai.stt_model", "ai"),
    "AI_LLM_MODEL": ("ai.llm_model", "ai"),
    "AI_TTS_VOICE": ("ai.tts_voice", "ai"),
    "AI_RESPONSE_TIMEOUT": ("ai.response_timeout", "ai"),
    "AI_MAX_CALL_DURATION": ("ai.max_call_duration", "ai"),
}


def load_env_file(env_path):
    """Parse a .env file into a dict. Handles comments and quoted values."""
    values = {}
    if not os.path.exists(env_path):
        return values
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Remove surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[key] = value
    return values


def seed_config(db_path=None, env_path=None):
    """Seed the database config table from environment variables."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    # Initialize DB (creates tables + default admin + default persona)
    init_db(db_path)

    # Load .env file
    if env_path is None:
        env_path = os.environ.get("ENV_FILE", os.path.join(PROJECT_ROOT, ".env"))
    env_values = load_env_file(env_path)

    # Merge: env file values, overridden by actual environment variables
    for env_key in CONFIG_MAP:
        value = os.environ.get(env_key, env_values.get(env_key, ""))
        if value:  # Only set non-empty values
            config_key, category = CONFIG_MAP[env_key]
            set_config(config_key, value, category, db_path)
            print(f"  {config_key} = {'***' if 'password' in config_key.lower() or 'secret' in config_key.lower() else value}")

    print(f"\nConfig seeded into {db_path}")
    print(f"Values loaded from {env_path}")


if __name__ == "__main__":
    env_file = sys.argv[1] if len(sys.argv) > 1 else None
    print("Voice Secretary — Seeding configuration from .env\n")
    seed_config(env_path=env_file)
    print("\nDone! Start the dashboard with: make run")
