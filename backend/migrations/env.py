"""Alembic environment: runs migrations against POKER_COACH_DATABASE_URL.

The schema is plain SQL (no SQLAlchemy models), so migrations execute the
checked-in ``postgres_schema.sql`` statements directly.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from os import getenv
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = getenv("POKER_COACH_DATABASE_URL") or config.get_main_option("sqlalchemy.url") or ""
if not url:
    raise RuntimeError(
        "POKER_COACH_DATABASE_URL must be set to run migrations"
    )
config.set_main_option("sqlalchemy.url", url)

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    # psycopg3 driver: alembic's sqlalchemy.url must use the +psycopg scheme.
    engine = create_engine(
        url.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
