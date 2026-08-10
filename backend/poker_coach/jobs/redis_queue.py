"""Redis-backed analysis job queue with cooperative cross-process cancellation.

Key layout (prefix defaults to ``pkcoach:jobs``)::

    {prefix}:queue               LIST of pending job ids (LPUSH submit / BRPOP workers)
    {prefix}:job:{job_id}        HASH job metadata (status, scenarioJson, timeoutSeconds, ...)
    {prefix}:job:{job_id}:result STRING serialized AnalysisResult (terminal states)
    {prefix}:running             counter of claimed jobs (for capacity reporting)

Status lifecycle::

    queued --claim--> running --finish--> completed | failed | timeout
      |                              |
      +--cancel--> cancelled         +--cancel (worker poller)--> cancelled

Cancellation is cooperative: ``cancel`` sets ``cancelRequested`` and removes
the id from the queue; a worker that already claimed the job polls the flag
while computing and raises AnalysisCancelled. No business rule runs here.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from poker_coach.domain.models import ScenarioSpec
from poker_coach.persistence.sqlite_store import StoreNotFound


class RedisUnavailable(RuntimeError):
    """Raised when Redis was requested but the optional driver is absent."""


class RedisJobQueue:
    """A durable job queue for analysis runs, usable from any process."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client=None,
        prefix: str = "pkcoach:jobs",
    ):
        if client is None:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover - exercised in deployment
                raise RedisUnavailable(
                    "analysis jobs over Redis require the optional dependency 'redis'"
                ) from exc
            client = redis.Redis.from_url(url)
            client.ping()
        self._client = client
        self.prefix = prefix

    def submit(
        self,
        scenario: ScenarioSpec,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        job_id = uuid4().hex
        self._client.hset(
            self._job_key(job_id),
            mapping={
                "status": "queued",
                "scenarioJson": scenario.to_json(),
                "timeoutSeconds": json.dumps(timeout_seconds),
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
        analysis = json.loads(result_raw) if result_raw else None
        execution_ms = job.get("executionMs", "")
        error = job.get("error") or None
        return {
            "status": status,
            "executionMs": float(execution_ms) if execution_ms else None,
            "error": error,
            "analysis": analysis,
        }

    def cancel(self, job_id: str) -> str:
        """Request cancellation and return the status after the request."""
        job = self._hgetall(self._job_key(job_id))
        if not job:
            raise StoreNotFound(job_id)
        status = job.get("status", "")
        self._client.hset(self._job_key(job_id), "cancelRequested", "1")
        if status == "queued":
            # Nothing will run it: remove from the queue and settle terminal.
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

    def claim_next(
        self, block_seconds: float = 0.0
    ) -> tuple[str, ScenarioSpec, float | None] | None:
        """Claim one queued job (``block_seconds=0`` is non-blocking)."""
        if block_seconds and block_seconds > 0:
            item = self._client.brpop(self._queue_key(), timeout=block_seconds)
        else:
            item = self._client.rpop(self._queue_key())
        if not item:
            return None
        # brpop returns (key, value); rpop returns the value directly.
        job_id = self._decode(item[-1] if isinstance(item, (tuple, list)) else item)
        job = self._hgetall(self._job_key(job_id))
        if not job:
            return None
        if job.get("cancelRequested", "0") == "1":
            self._client.hset(self._job_key(job_id), "status", "cancelled")
            return None
        self._client.hset(self._job_key(job_id), "status", "running")
        self._client.incr(self._running_key())
        scenario = ScenarioSpec.from_json(job["scenarioJson"])
        timeout_raw = job.get("timeoutSeconds", "null")
        timeout = json.loads(timeout_raw) if timeout_raw else None
        return job_id, scenario, timeout

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        execution_ms: float | None = None,
        result=None,
    ) -> None:
        mapping: dict[str, str] = {"status": status, "error": error or ""}
        if execution_ms is not None:
            mapping["executionMs"] = repr(execution_ms)
        self._client.hset(self._job_key(job_id), mapping=mapping)
        if result is not None:
            self._client.set(self._result_key(job_id), result.to_json())
        self._client.decr(self._running_key())

    def pending_count(self) -> int:
        """Approximate number of queued plus running jobs."""
        running = self._client.get(self._running_key())
        return int(self._client.llen(self._queue_key())) + int(
            self._decode(running) or 0
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive teardown
            pass

    def _queue_key(self) -> str:
        return f"{self.prefix}:queue"

    def _job_key(self, job_id: str) -> str:
        return f"{self.prefix}:job:{job_id}"

    def _result_key(self, job_id: str) -> str:
        return f"{self.prefix}:job:{job_id}:result"

    def _running_key(self) -> str:
        return f"{self.prefix}:running"

    def _hgetall(self, key: str) -> dict[str, str]:
        """Read a hash with str keys and values regardless of client decode mode."""
        raw = self._client.hgetall(key)
        return {self._decode(k): self._decode(v) for k, v in raw.items()}

    @staticmethod
    def _decode(value: Any) -> Any:
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else value
