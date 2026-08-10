"""Baseline migration: the initial schema from postgres_schema.sql.

Revision ID: 0001
Revises:
Create Date: 2026-08-10
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "poker_coach"
    / "persistence"
    / "postgres_schema.sql"
)

_TABLES_IN_DEPENDENCY_ORDER = (
    "mistake_records",
    "concept_progress",
    "practice_attempts",
    "practice_questions",
    "teaching_messages",
    "teaching_sessions",
    "evidence_items",
    "analysis_runs",
    "range_versions",
    "scenario_revisions",
    "strategy_artifacts",
    "learning_profiles",
    "scenarios",
    "schema_migrations",
)


def upgrade() -> None:
    statements = _SCHEMA.read_text(encoding="utf-8").split(";\n")
    for statement in statements:
        statement = statement.strip()
        if statement:
            op.execute(statement)


def downgrade() -> None:
    for table in _TABLES_IN_DEPENDENCY_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
