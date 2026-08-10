"""Redis-backed solver job queue (mirrors poker_coach.jobs semantics).

Key layout (prefix defaults to ``pkcoach:solverjobs``)::

    {prefix}:queue             LIST of pending job ids
    {prefix}:job:{job_id}      HASH: status, spotJson, cancelRequested, ...
    {prefix}:job:{job_id}:result   STRING serialized SolveResult

Lifecycle: queued --claim--> running --finish--> solved | failed | cancelled
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from poker_coach.persistence.sqlite_store import StoreNotFound

from .types import SolverSpot, SolveResult


class SolverQueueUnavailable(RuntimeError):
    """Raised when Redis was requested but the optional driver is absent."""


class SolverJobQueue:
    def __init__(self, url: str | None = None, *, client=None, prefix: str = "pkcoach:solverjobs"):
        if client is None:
            try:
                import redis
            except ImportError as exc:
                raise SolverQueueUnavailable(
                    "solver jobs over Redis require the optional dependency 'redis'"
                ) from exc
            client = redis.Redis.from_url(url)
            client.ping()
        self._client = client
        self.prefix = prefix

    def _queue_key(self) -> str:
        return f"{self.prefix}:queue"

    def _job_key(self, job_id: str) -> str:
        return f"{self.prefix}:job:{job_id}"

    def _result_key(self, job_id: str) -> str:
        return f"{self.prefix}:job:{job_id}:result"

    def submit(self, spot: SolverSpot) -> str:
        job_id = uuid4().hex
        self._client.hset(
            self._job_key(job_id),
            mapping={
                "status": "queued",
                "spotJson": spot.to_json(),
                "cancelRequested": "0",
                "createdAt": str(time.time()),
                "error": "",
                "executionMs": "",
            },
        )
        self._client.lpush(self._queue_key(), job_id)
        return job_id

    def get(self, job_id: str) -> dict[str, Any]:
        job = self._hgetall(self._job_key(job_id))
        if not job:
            raise StoreNotFound(job_id)
        status = job.get("status", "")
        result_raw = self._client.get(self._result_key(job_id))
        result = SolveResult.model_validate_json(result_raw) if result_raw else None
        execution_ms = job.get("executionMs", "") or None
        error = job.get("error", "") or None
        return {
            "status": status,
            "executionMs": float(execution_ms) if execution_ms else None,
            "error": error,
            "result": result,
        }

    def cancel(self, job_id: str) -> str:
        """Request cancellation; returns the job's status after the request."""
        job = self._hgetall(self._job_key(job_id))
        if not job:
            raise StoreNotFound(job_id)
        status = job.get("status", "")
        self._client.hset(self._job_key(job_id), "cancelRequested", "1")
        if status == "queued":
            self._client.lrem(self._queue_key(), 0, job_id)
            self._client.hset(self._job_key(job_id), "status", "cancelled")
            return "cancelled"
        if status == "running":
            self._client.hset(self._job_key(job_id), "status", "cancellation_requested")
            return "cancellation_requested"
        return status

    def is_cancelled(self, job_id: str) -> bool:
        value = self._client.hget(self._job_key(job_id), "cancelRequested")
        return self._decode(value) == "1"

    def claim_next(self, block_seconds: float = 0.0) -> tuple[str, SolverSpot] | None:
        if block_seconds and block_seconds > 0:
            item = self._client.brpop(self._queue_key(), timeout=block_seconds)
        else:
            item = self._client.rpop(self._queue_key())
        if not item:
            return None
        job_id = self._decode(item[-1] if isinstance(item, (tuple, list)) else item)
        job = self._hgetall(self._job_key(job_id))
        if not job:
            return None
        if job.get("cancelRequested", "0") == "1":
            self._client.hset(self._job_key(job_id), "status", "cancelled")
            return None
        self._client.hset(self._job_key(job_id), "status", "running")
        return job_id, SolverSpot.model_validate_json(job["spotJson"])

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        execution_ms: float | None = None,
        result: SolveResult | None = None,
    ) -> None:
        mapping = {"status": status, "error": error or ""}
        if execution_ms is not None:
            mapping["executionMs"] = repr(execution_ms)
        self._client.hset(self._job_key(job_id), mapping=mapping)
        if result is not None:
            self._client.set(self._result_key(job_id), result.to_json())

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _hgetall(self, key: str) -> dict[str, str]:
        raw = self._client.hgetall(key)
        return {self._decode(k): self._decode(v) for k, v in raw.items()}

    @staticmethod
    def _decode(value: Any) -> Any:
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else value
