"""Solver worker: consumes solve jobs and runs the isolated sidecar.

One job at a time; cancellation is cooperative — a poller thread watches
the Redis cancel flag and kills the sidecar process through the client's
cancel event.
"""

from __future__ import annotations

import threading
import time

from .cache import SolveCache, solve_with_cache
from .client import SidecarClient, SolverCancelled
from .jobs import SolverJobQueue
from .types import SolverUnsupportedError

_CANCEL_POLL_SECONDS = 0.2


class SolverWorker:
    def __init__(
        self,
        queue: SolverJobQueue,
        client: SidecarClient | None = None,
        cache: SolveCache | None = None,
    ):
        self._queue = queue
        self._client = client or SidecarClient()
        self._cache = cache

    def process_one(self, block_seconds: float = 0.0) -> str | None:
        """Claim and run at most one job; return its id or None."""
        claimed = self._queue.claim_next(block_seconds=block_seconds)
        if claimed is None:
            return None
        job_id, spot = claimed
        cancel_event = threading.Event()
        poller = threading.Thread(
            target=self._poll_cancellation, args=(job_id, cancel_event), daemon=True
        )
        poller.start()
        started = time.perf_counter()
        try:
            if self._cache is not None:
                result = solve_with_cache(
                    self._client, spot, self._cache, cancel_event=cancel_event
                )
            else:
                result = self._client.solve(spot, cancel_event=cancel_event)
        except SolverCancelled as exc:
            self._queue.finish(job_id, status="cancelled", error=str(exc))
            return job_id
        except SolverUnsupportedError as exc:
            self._queue.finish(job_id, status="failed", error=str(exc))
            return job_id
        except Exception as exc:  # defensive worker boundary
            self._queue.finish(job_id, status="failed", error=str(exc))
            return job_id
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        self._queue.finish(
            job_id, status="solved", execution_ms=elapsed_ms, result=result
        )
        return job_id

    def run_forever(self, block_seconds: float = 1.0) -> None:
        while True:
            self.process_one(block_seconds=block_seconds)

    def _poll_cancellation(self, job_id: str, cancel_event: threading.Event) -> None:
        while not cancel_event.is_set():
            if self._queue.is_cancelled(job_id):
                cancel_event.set()
                return
            time.sleep(_CANCEL_POLL_SECONDS)
