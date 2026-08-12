CREATE TABLE IF NOT EXISTS game_sessions (
    session_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    session_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT pk_game_sessions PRIMARY KEY (session_id)
);
