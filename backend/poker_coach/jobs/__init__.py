"""Async analysis jobs: in-process thread pool and Redis-backed queue.

The API submits jobs through a small backend contract (``submit`` /
``get`` / ``cancel`` / ``active_count``). Without configuration the
in-process backend is used; with ``POKER_COACH_REDIS_URL`` set, jobs are
queued in Redis and can be executed by a separate worker process so
cancellation works across processes.
"""

from .backends import InProcessJobBackend, RedisJobBackend
from .redis_queue import RedisJobQueue, RedisUnavailable
from .worker import AnalysisWorker

__all__ = [
    "AnalysisWorker",
    "InProcessJobBackend",
    "RedisJobBackend",
    "RedisJobQueue",
    "RedisUnavailable",
]
