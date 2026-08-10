"""Solver job queue and worker tests (in-memory fakeredis, offline)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import fakeredis
import pytest

from poker_coach.domain.models import Street
from poker_coach.persistence.sqlite_store import StoreNotFound
from poker_coach.solver import (
    SidecarClient,
    SolverCancelled,
    SolverJobQueue,
    SolverSpot,
    SolverUnsupportedError,
    SolverWorker,
)

FIXTURE = Path(__file__).parent / "fixtures" / "solve-output-spike1.json"


def make_spot() -> SolverSpot:
    return SolverSpot(
        street=Street.FLOP,
        board=("Ks", "7h", "2h"),
        oop_range="AA:1",
        ip_range="KK:1",
        starting_pot=500,
        effective_stack=9750,
        max_iterations=50,
    )


@pytest.fixture()
def queue():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server)
    q = SolverJobQueue(client=client)
    yield q
    q.close()


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_submit_get_claim_finish_roundtrip(queue):
    job_id = queue.submit(make_spot())
    assert queue.get(job_id)["status"] == "queued"

    claimed = queue.claim_next()
    assert claimed is not None
    claimed_id, spot = claimed
    assert claimed_id == job_id
    assert spot.board == ("Ks", "7h", "2h")
    assert queue.get(job_id)["status"] == "running"

    result = queue.get(job_id)
    assert result["status"] == "running"
    with pytest.raises(StoreNotFound):
        queue.get("does-not-exist")


def test_cancel_queued_job_never_claimed(queue):
    job_id = queue.submit(make_spot())
    assert queue.cancel(job_id) == "cancelled"
    assert queue.get(job_id)["status"] == "cancelled"
    assert queue.claim_next() is None


def test_worker_solves_and_stores_result(queue):
    client = SidecarClient(runner=lambda config_json: json.dumps(fixture_payload()))
    worker = SolverWorker(queue, client=client)
    job_id = queue.submit(make_spot())
    assert worker.process_one() == job_id
    job = queue.get(job_id)
    assert job["status"] == "solved"
    assert job["result"] is not None
    assert job["result"].metadata.solver == "postflop-solver"
    assert job["executionMs"] is not None


def test_worker_failure_records_error(queue):
    def failing_runner(config_json: str) -> str:
        raise SolverUnsupportedError("sidecar exploded")

    worker = SolverWorker(queue, client=SidecarClient(runner=failing_runner))
    job_id = queue.submit(make_spot())
    worker.process_one()
    job = queue.get(job_id)
    assert job["status"] == "failed"
    assert "exploded" in job["error"]


def test_cancel_running_job_is_cooperative(queue):
    class BlockingClient:
        def solve(self, spot, cancel_event=None):
            while not cancel_event.is_set():
                time.sleep(0.01)
            raise SolverCancelled("cancelled by test")

    worker = SolverWorker(queue, client=BlockingClient())
    job_id = queue.submit(make_spot())

    worker_thread = threading.Thread(target=worker.process_one)
    worker_thread.start()
    # wait until the worker claims the job, then cancel it
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if queue.get(job_id)["status"] == "running":
            break
        time.sleep(0.01)
    assert queue.cancel(job_id) == "cancellation_requested"
    worker_thread.join(timeout=10)
    assert queue.get(job_id)["status"] == "cancelled"


def test_submit_rejects_out_of_quota_spot():
    with pytest.raises(Exception):
        SolverSpot(
            street=Street.FLOP,
            board=("Ks", "7h", "2h"),
            oop_range="AA:1",
            ip_range="KK:1",
            starting_pot=500,
            effective_stack=9750,
            max_iterations=10_000_000,
        )
