"""Solve-result cache: deterministic spots are solved at most once."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .types import SolverSpot, SolveResult


def solve_hash(spot: SolverSpot) -> str:
    """Canonical spot fingerprint: board/ranges/pot/stack/tree/rake/accuracy."""
    canonical = json.dumps(
        spot.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SolveCache:
    """SQLite-backed cache keyed by ``solve_hash`` (local default storage)."""

    def __init__(self, db_path: str):
        self._connection = sqlite3.connect(db_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS solve_cache (
                solve_hash TEXT PRIMARY KEY,
                spot_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                solver_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def get(self, spot: SolverSpot) -> SolveResult | None:
        row = self._connection.execute(
            "SELECT result_json FROM solve_cache WHERE solve_hash = ?",
            (solve_hash(spot),),
        ).fetchone()
        if row is None:
            return None
        return SolveResult.model_validate_json(row[0])

    def put(self, spot: SolverSpot, result: SolveResult) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO solve_cache
                (solve_hash, spot_json, result_json, solver_version, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                solve_hash(spot),
                spot.to_json(),
                result.to_json(),
                result.metadata.version,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


def solve_with_cache(
    client,
    spot: SolverSpot,
    cache: SolveCache,
    *,
    cancel_event=None,
) -> SolveResult:
    """Solve through the cache: deterministic spots are solved at most once."""
    cached = cache.get(spot)
    if cached is not None:
        return cached
    result = client.solve(spot, cancel_event=cancel_event)
    cache.put(spot, result)
    return result
