CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    notes TEXT
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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    scopes TEXT
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
