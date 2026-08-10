CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    raw_scenario_json TEXT NOT NULL,
    scenario_json TEXT NOT NULL,
    scenario_hash TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    favorite BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_revisions (
    revision_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL,
    raw_scenario_json TEXT NOT NULL,
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
    random_seed BIGINT,
    execution_ms DOUBLE PRECISION,
    status TEXT NOT NULL,
    error_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_row_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT,
    source_level TEXT NOT NULL,
    source_version TEXT NOT NULL,
    description TEXT NOT NULL,
    UNIQUE (analysis_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS range_versions (
    range_id TEXT NOT NULL,
    range_version TEXT NOT NULL,
    range_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (range_id, range_version)
);

CREATE TABLE IF NOT EXISTS strategy_artifacts (
    artifact_id TEXT NOT NULL,
    artifact_version TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    source_level TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, artifact_version)
);

CREATE TABLE IF NOT EXISTS learning_profiles (
    profile_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teaching_sessions (
    session_id TEXT PRIMARY KEY,
    profile_id TEXT REFERENCES learning_profiles(profile_id) ON DELETE CASCADE,
    scenario_id TEXT REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    analysis_id TEXT REFERENCES analysis_runs(analysis_id) ON DELETE CASCADE,
    teacher_version TEXT NOT NULL,
    prompt_version TEXT,
    depth TEXT NOT NULL,
    user_question TEXT,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teaching_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES teaching_sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concept_progress (
    profile_id TEXT NOT NULL REFERENCES learning_profiles(profile_id) ON DELETE CASCADE,
    concept_tag TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, concept_tag)
);

CREATE TABLE IF NOT EXISTS mistake_records (
    record_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES learning_profiles(profile_id) ON DELETE CASCADE,
    scenario_id TEXT REFERENCES scenarios(scenario_id) ON DELETE SET NULL,
    analysis_id TEXT REFERENCES analysis_runs(analysis_id) ON DELETE SET NULL,
    mistake_tag TEXT NOT NULL,
    street TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_questions (
    question_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES learning_profiles(profile_id) ON DELETE CASCADE,
    source_scenario_id TEXT REFERENCES scenarios(scenario_id) ON DELETE SET NULL,
    source_analysis_id TEXT REFERENCES analysis_runs(analysis_id) ON DELETE SET NULL,
    question_json TEXT NOT NULL,
    expected_action TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_attempts (
    attempt_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES practice_questions(question_id) ON DELETE CASCADE,
    selected_action TEXT NOT NULL,
    correct BOOLEAN NOT NULL,
    rationale TEXT,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scenarios_updated_at ON scenarios(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_scenario ON analysis_runs(scenario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_items_analysis ON evidence_items(analysis_id, evidence_id);
CREATE INDEX IF NOT EXISTS idx_teaching_sessions_profile ON teaching_sessions(profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_practice_questions_profile ON practice_questions(profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_practice_attempts_question ON practice_attempts(question_id, created_at DESC);
