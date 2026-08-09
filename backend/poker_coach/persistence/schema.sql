PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    scenario_json TEXT NOT NULL,
    scenario_hash TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    favorite INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL,
    scenario_json TEXT NOT NULL,
    scenario_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (scenario_id, revision_no)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL,
    raw_scenario_json TEXT NOT NULL,
    normalized_scenario_json TEXT NOT NULL,
    evidence_json TEXT,
    output_json TEXT,
    rules_engine_version TEXT,
    analysis_version TEXT,
    agent_version TEXT,
    prompt_version TEXT,
    random_seed INTEGER,
    execution_ms REAL,
    status TEXT NOT NULL,
    error_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scenarios_updated_at ON scenarios(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_scenario ON analysis_runs(scenario_id, created_at DESC);
