"""Add projection recovery and transactional outbox tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_SCHEMAS = (
    Path(__file__).resolve().parents[2]
    / "poker_coach"
    / "persistence"
    / "projection_schema.sql",
    Path(__file__).resolve().parents[2]
    / "poker_coach"
    / "persistence"
    / "outbox_schema.sql",
)


def upgrade() -> None:
    for schema in _SCHEMAS:
        for statement in schema.read_text(encoding="utf-8").split(";\n"):
            statement = statement.strip()
            if statement:
                op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS outbox_messages")
    op.execute("DROP TABLE IF EXISTS projection_snapshots")
    op.execute("DROP TABLE IF EXISTS projection_checkpoints")
