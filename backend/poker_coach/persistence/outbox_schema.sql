CREATE TABLE IF NOT EXISTS outbox_messages (
    message_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'dispatched')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    available_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
    claimed_by TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    CONSTRAINT pk_outbox_messages PRIMARY KEY (message_id),
    CONSTRAINT uq_outbox_messages_idempotency_key UNIQUE (idempotency_key)
);
