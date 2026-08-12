CREATE TABLE IF NOT EXISTS hand_events (
    event_id TEXT NOT NULL,
    hand_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    schema_version INTEGER NOT NULL,
    source TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    raw_event_json TEXT NOT NULL,
    CONSTRAINT pk_hand_events PRIMARY KEY (event_id),
    CONSTRAINT uq_hand_events_hand_sequence UNIQUE (hand_id, sequence)
);
