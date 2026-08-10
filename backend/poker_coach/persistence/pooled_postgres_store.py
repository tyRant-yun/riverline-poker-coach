"""Connection-pooled variant of PostgresStore for production deployments.

Every transaction or read checks out a connection from a
``psycopg_pool.ConnectionPool`` instead of pinning one connection for the
lifetime of the store, so one API process can serve many concurrent
requests without exhausting PostgreSQL connections. All public store
methods are inherited from PostgresStore; only the connection primitives
are overridden.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable

from .postgres_store import PostgresStore, _row_to_dict


class PooledPostgresStore(PostgresStore):
    """PostgresStore whose database access goes through a connection pool."""

    def __init__(
        self,
        dsn: str,
        *,
        pool=None,
        min_size: int = 1,
        max_size: int = 8,
    ):
        self.dsn = dsn
        self._owns_connection = False
        self._connection = None
        if pool is None:
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:  # pragma: no cover - exercised in deployment
                from .postgres_store import PostgresUnavailable

                raise PostgresUnavailable(
                    "PostgreSQL pooling requires the optional dependency 'psycopg-pool'"
                ) from exc
            pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=False)
            pool.open(wait=True)
        self._pool = pool
        self._initialize()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def _transaction(self):
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                yield cursor

    def _fetchone(
        self, query: str, params: Iterable[Any] = ()
    ) -> dict[str, Any] | None:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
                return _row_to_dict(cursor, row)

    def _fetchall(self, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                return [_row_to_dict(cursor, row) for row in cursor.fetchall()]
