"""Solve cache integration tests: hit/miss paths, worker caching, pre-solve."""

from __future__ import annotations

import json
from pathlib import Path

import fakeredis
import pytest

from poker_coach.domain.models import Street
from poker_coach.solver import (
    SidecarClient,
    SolveCache,
    SolverJobQueue,
    SolverSpot,
    SolverWorker,
    common_spots,
    parse_result,
    pre_solve,
    solve_hash,
    solve_with_cache,
)

FIXTURE = Path(__file__).parent / "fixtures" / "solve-output-spike1.json"


def make_spot(max_iterations: int = 50) -> SolverSpot:
    return SolverSpot(
        street=Street.FLOP,
        board=("Ks", "7h", "2h"),
        oop_range="AA:1",
        ip_range="KK:1",
        starting_pot=500,
        effective_stack=9750,
        max_iterations=max_iterations,
    )


def fixture_payload() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class CountingClient:
    def __init__(self):
        self.calls = 0
        self._result = parse_result(json.loads(fixture_payload()))

    def solve(self, spot, cancel_event=None):
        self.calls += 1
        return self._result


def test_solve_with_cache_hits_after_first_solve(tmp_path):
    client = CountingClient()
    cache = SolveCache(str(tmp_path / "solve-cache.sqlite3"))
    spot = make_spot()
    try:
        first = solve_with_cache(client, spot, cache)
        assert client.calls == 1
        second = solve_with_cache(client, spot, cache)
        assert client.calls == 1  # no second sidecar call
        assert second.metadata.exploitability_chips == pytest.approx(2.3484, abs=1e-3)
        assert first.root.actions == second.root.actions
    finally:
        cache.close()


def test_cache_key_differs_by_spot(tmp_path):
    cache = SolveCache(str(tmp_path / "solve-cache.sqlite3"))
    try:
        assert solve_hash(make_spot(50)) != solve_hash(make_spot(60))
        assert solve_hash(make_spot()) == solve_hash(make_spot())
    finally:
        cache.close()


def test_worker_serves_second_identical_job_from_cache(tmp_path):
    client = CountingClient()
    cache = SolveCache(str(tmp_path / "solve-cache.sqlite3"))
    server = fakeredis.FakeServer()
    queue = SolverJobQueue(client=fakeredis.FakeRedis(server=server))
    worker = SolverWorker(queue, client=client, cache=cache)
    try:
        first_job = queue.submit(make_spot())
        assert worker.process_one() == first_job
        assert queue.get(first_job)["status"] == "solved"
        second_job = queue.submit(make_spot())
        assert worker.process_one() == second_job
        assert queue.get(second_job)["status"] == "solved"
        assert client.calls == 1  # cached on the second job
    finally:
        cache.close()
        queue.close()


def test_pre_solve_populates_cache(tmp_path):
    client = CountingClient()
    cache = SolveCache(str(tmp_path / "solve-cache.sqlite3"))
    try:
        spots = common_spots()
        assert len(spots) == 3
        outcomes = pre_solve(client, cache, spots)
        assert all(status == "solved" for status in outcomes.values())
        assert client.calls == len(spots)
        # second run: all cache hits, no sidecar calls
        outcomes_again = pre_solve(client, cache, spots)
        assert all(status == "solved" for status in outcomes_again.values())
        assert client.calls == len(spots)
    finally:
        cache.close()
