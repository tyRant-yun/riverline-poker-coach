"""Add the durable append-only hand_events log.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "poker_coach"
    / "persistence"
    / "hand_events_schema.sql"
)


def upgrade() -> None:
    for statement in _SCHEMA.read_text(encoding="utf-8").split(";\n"):
        statement = statement.strip()
        if statement:
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hand_events")
