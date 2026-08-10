from pathlib import Path
import re

from poker_coach.persistence import PostgresStore


class FakeCursor:
    def __init__(self, statements):
        self.statements = statements
        self.description = []

    def execute(self, query, params=()):
        self.statements.append((query, tuple(params)))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.statements = []

    def cursor(self):
        return FakeCursor(self.statements)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def test_postgres_schema_uses_postgres_identity_and_no_sqlite_pragmas():
    schema = (Path(__file__).resolve().parents[1] / "poker_coach/persistence/postgres_schema.sql").read_text(
        encoding="utf-8"
    )
    assert "GENERATED ALWAYS AS IDENTITY" in schema
    assert "AUTOINCREMENT" not in schema
    assert "PRAGMA" not in schema
    assert "CREATE TABLE IF NOT EXISTS practice_attempts" in schema


def test_postgres_schema_covers_the_sqlite_logical_tables():
    persistence_dir = Path(__file__).resolve().parents[1] / "poker_coach/persistence"
    sqlite_schema = (persistence_dir / "schema.sql").read_text(encoding="utf-8")
    postgres_schema = (persistence_dir / "postgres_schema.sql").read_text(encoding="utf-8")
    table_names = lambda schema: set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema))

    assert table_names(sqlite_schema) <= table_names(postgres_schema)


def test_postgres_store_initializes_through_injected_dbapi_connection():
    connection = FakeConnection()
    store = PostgresStore("postgresql://test", connection=connection)

    assert len(connection.statements) > 2
    assert any("CREATE TABLE IF NOT EXISTS scenarios" in query for query, _ in connection.statements)
    migration_queries = [
        query for query, _ in connection.statements if "INSERT INTO schema_migrations" in query
    ]
    assert len(migration_queries) == 4
    assert all("ON CONFLICT (version) DO NOTHING" in query for query in migration_queries)
    store.close()
