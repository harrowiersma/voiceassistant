CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    greeting TEXT NOT NULL DEFAULT 'Hello, how may I help you?',
    personality TEXT NOT NULL DEFAULT 'Professional and friendly.',
    unavailable_message TEXT NOT NULL DEFAULT 'They are not available right now.',
    calendar_type TEXT DEFAULT 'none',
    calendar_config TEXT,
    inbound_number TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    aliases TEXT,
    persona_id INTEGER NOT NULL REFERENCES personas(id),
    forward_number TEXT,
    calendar_type TEXT DEFAULT 'none',
    calendar_config TEXT,
    email TEXT,
    internal_extension TEXT,
    is_owner BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    caller_number TEXT,
    caller_name TEXT,
    duration_seconds INTEGER,
    reason TEXT,
    transcript TEXT,
    action_taken TEXT,
    forwarded_to TEXT,
    availability_status TEXT,
    email_sent BOOLEAN DEFAULT FALSE,
    calendar_created BOOLEAN DEFAULT FALSE,
    callback_time TIMESTAMP,
    notes TEXT,
    persona_id INTEGER REFERENCES personas(id)
);

CREATE TABLE IF NOT EXISTS knowledge_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,
    trigger_keywords TEXT,
    response TEXT NOT NULL,
    active_from TIMESTAMP,
    active_until TIMESTAMP,
    priority INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    tts_wav_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    persona_id INTEGER REFERENCES personas(id)
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT NOT NULL,
    person_id INTEGER NOT NULL DEFAULT 0,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    scopes TEXT,
    PRIMARY KEY (provider, person_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blocked_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    block_type TEXT NOT NULL DEFAULT 'exact',
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
