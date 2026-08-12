CREATE TABLE IF NOT EXISTS projection_checkpoints (
    projection_name TEXT NOT NULL,
    projection_version INTEGER NOT NULL CHECK (projection_version >= 1),
    stream_id TEXT NOT NULL,
    last_sequence INTEGER NOT NULL CHECK (last_sequence >= 1),
    last_event_id TEXT NOT NULL,
    CONSTRAINT pk_projection_checkpoints PRIMARY KEY
        (projection_name, projection_version, stream_id)
);

CREATE TABLE IF NOT EXISTS projection_snapshots (
    projection_name TEXT NOT NULL,
    projection_version INTEGER NOT NULL CHECK (projection_version >= 1),
    stream_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    CONSTRAINT pk_projection_snapshots PRIMARY KEY
        (projection_name, projection_version, stream_id)
);
