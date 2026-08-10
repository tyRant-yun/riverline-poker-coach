"""Cooperative analysis worker for the Redis job queue.

Runs one job at a time. Usable as an in-process daemon thread inside the
API process (``create_app`` with ``POKER_COACH_REDIS_URL``) or as a
standalone process (``python -m poker_coach.jobs``). Cancellation is
cooperative: a daemon thread polls the Redis ``cancelRequested`` flag and
sets the analysis cancel event, which the equity engine observes between
trials.
"""

from __future__ import annotations

import threading
import time

from poker_coach.analysis import AnalysisCancelled, AnalysisTimeout, analyze_scenario
from poker_coach.rules import PokerKitAdapter


class AnalysisWorker:
    """Consumes jobs from a RedisJobQueue and settles their results."""

    def __init__(
        self,
        queue,
        adapter: PokerKitAdapter | None = None,
        default_timeout: float = 120.0,
    ):
        self.queue = queue
        self.adapter = adapter or PokerKitAdapter()
        self.default_timeout = default_timeout

    def process_one(self, block_seconds: float = 0.0) -> str | None:
        """Claim and run at most one job; return its id or None."""
        claimed = self.queue.claim_next(block_seconds=block_seconds)
        if claimed is None:
            return None
        job_id, scenario, timeout_seconds = claimed
        return self._execute(
            job_id,
            scenario,
            timeout_seconds=(
                timeout_seconds
                if timeout_seconds is not None
                else self.default_timeout
            ),
        )

    def _execute(
        self,
        job_id: str,
        scenario,
        *,
        timeout_seconds: float,
    ) -> str:
        """Run one already-claimed job with cooperative cancellation."""
        cancel_event = threading.Event()
        poller = threading.Thread(
            target=self._poll_cancellation,
            args=(job_id, cancel_event),
            daemon=True,
        )
        poller.start()
        started = time.perf_counter()
        try:
            result = analyze_scenario(
                scenario,
                adapter=self.adapter,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
            )
        except AnalysisCancelled as exc:
            self.queue.finish(job_id, status="cancelled", error=str(exc))
            return job_id
        except AnalysisTimeout as exc:
            self.queue.finish(job_id, status="timeout", error=str(exc))
            return job_id
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            self.queue.finish(job_id, status="failed", error=str(exc))
            return job_id
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        self.queue.finish(
            job_id, status="completed", execution_ms=elapsed_ms, result=result
        )
        return job_id

    def run_forever(self, block_seconds: float = 1.0) -> None:
        """Blocking worker loop; intended for a dedicated worker process."""
        while True:
            self.process_one(block_seconds=block_seconds)

    def _poll_cancellation(self, job_id: str, cancel_event: threading.Event) -> None:
        while not cancel_event.is_set():
            if self.queue.is_cancelled(job_id):
                cancel_event.set()
                return
            time.sleep(0.2)
