"""Job backends behind the API's submit/get/cancel contract.

``InProcessJobBackend`` preserves the original thread-pool behavior used
when Redis is not configured; ``RedisJobBackend`` delegates to
``RedisJobQueue`` so workers can run in other processes.
"""

from __future__ import annotations

import time
from threading import Event
from uuid import uuid4

from poker_coach.analysis import AnalysisCancelled, AnalysisTimeout, analyze_scenario
from poker_coach.domain.models import ScenarioSpec
from poker_coach.persistence.sqlite_store import StoreNotFound


class InProcessJobBackend:
    """Thread-pool fallback backend; jobs live only in this process."""

    def __init__(
        self,
        adapter,
        executor,
        max_jobs: int = 64,
        default_timeout: float = 120.0,
    ):
        self._adapter = adapter
        self._executor = executor
        self._max_jobs = max_jobs
        self._default_timeout = default_timeout
        self._jobs: dict[str, dict] = {}

    def submit(
        self,
        scenario: ScenarioSpec,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        job_id = uuid4().hex
        cancel_event = Event()
        self._jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "cancel_event": cancel_event,
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

        def run_job() -> None:
            job = self._jobs[job_id]
            job["status"] = "running"
            started = time.perf_counter()
            try:
                result = analyze_scenario(
                    scenario,
                    adapter=self._adapter,
                    cancel_event=cancel_event,
                    timeout_seconds=(
                        timeout_seconds
                        if timeout_seconds is not None
                        else self._default_timeout
                    ),
                )
                job["result"] = result
                job["execution_ms"] = round((time.perf_counter() - started) * 1000, 3)
                job["status"] = "completed"
            except AnalysisCancelled as exc:
                job["error"] = str(exc)
                job["status"] = "cancelled"
            except AnalysisTimeout as exc:
                job["error"] = str(exc)
                job["status"] = "timeout"
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                job["error"] = str(exc)
                job["status"] = "failed"

        self._executor.submit(run_job)
        return job_id

    def get(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            raise StoreNotFound(job_id)
        result = job.get("result")
        return {
            "status": job["status"],
            "executionMs": job.get("execution_ms"),
            "error": job.get("error"),
            "analysis": result.to_dict() if result is not None else None,
        }

    def cancel(self, job_id: str) -> str:
        job = self._jobs.get(job_id)
        if job is None:
            raise StoreNotFound(job_id)
        if job["status"] in {"queued", "running"}:
            job["cancel_event"].set()
            job["status"] = "cancellation_requested"
        return job["status"]

    def active_count(self) -> int:
        for stale_id, stale_job in list(self._jobs.items()):
            if stale_job["status"] in {"completed", "failed", "cancelled", "timeout"}:
                self._jobs.pop(stale_id, None)
        return len(self._jobs)


class RedisJobBackend:
    """Backend that persists job state in Redis for cross-process workers."""

    def __init__(self, queue):
        self._queue = queue

    def submit(
        self,
        scenario: ScenarioSpec,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        return self._queue.submit(scenario, timeout_seconds=timeout_seconds)

    def get(self, job_id: str) -> dict:
        return self._queue.get(job_id)

    def cancel(self, job_id: str) -> str:
        return self._queue.cancel(job_id)

    def active_count(self) -> int:
        return self._queue.pending_count()
