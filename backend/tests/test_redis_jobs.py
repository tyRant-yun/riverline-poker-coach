"""Redis job queue and worker tests (in-memory fakeredis, no daemon needed).

The queue semantics are tested directly; the in-process worker is driven
one job at a time so no background thread leaks between tests.
"""

from __future__ import annotations

import time

import fakeredis
import pytest

from poker_coach.domain.models import ScenarioSpec
from poker_coach.jobs import AnalysisWorker, InProcessJobBackend, RedisJobBackend, RedisJobQueue
from poker_coach.persistence.sqlite_store import StoreNotFound


def scenario_at_flop() -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 1,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10_000, "position": "button"},
                {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
            ],
            "heroHoleCards": ["As", "Kd"],
            "villainHoleCards": ["Qh", "Jc"],
            "board": ["2c", "7d", "Jh"],
            "actionHistory": [
                {
                    "actionId": "call",
                    "sequence": 1,
                    "street": "preflop",
                    "actorSeat": 0,
                    "actionType": "call",
                    "amount": 50,
                    "amountType": "cost",
                },
                {
                    "actionId": "check",
                    "sequence": 2,
                    "street": "preflop",
                    "actorSeat": 1,
                    "actionType": "check",
                },
                {
                    "actionId": "flop",
                    "sequence": 3,
                    "street": "flop",
                    "actorSeat": 0,
                    "actionType": "deal_flop",
                },
            ],
            "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
            "assumptions": {},
        }
    )


@pytest.fixture()
def queue():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server)
    redis_queue = RedisJobQueue(client=client)
    yield redis_queue
    redis_queue.close()


def test_submit_get_roundtrip_before_claim(queue):
    job_id = queue.submit(scenario_at_flop(), timeout_seconds=30.0)

    job = queue.get(job_id)
    assert job["status"] == "queued"
    assert job["analysis"] is None
    assert queue.pending_count() == 1


def test_claim_runs_and_finishes_completed(queue):
    worker = AnalysisWorker(queue)
    job_id = queue.submit(scenario_at_flop(), timeout_seconds=30.0)

    assert worker.process_one() == job_id

    job = queue.get(job_id)
    assert job["status"] == "completed"
    assert job["executionMs"] > 0
    assert job["error"] is None
    assert job["analysis"]["evidence"]["items"]
    assert queue.pending_count() == 0


def test_cancel_queued_job_settles_cancelled_without_worker(queue):
    job_id = queue.submit(scenario_at_flop(), timeout_seconds=30.0)

    assert queue.cancel(job_id) == "cancelled"
    assert queue.get(job_id)["status"] == "cancelled"
    # The worker must not see the cancelled job.
    assert queue.claim_next() is None
    assert queue.pending_count() == 0


def test_cancel_running_job_is_cooperative(queue):
    scenario = ScenarioSpec.model_validate(
        {
            **scenario_at_flop().model_dump(),
            "board": [],
            "action_history": [],
            "decision_point": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
            "assumptions": {
                "equityAlgorithm": "monte_carlo",
                "simulationTrials": 1_000_000,
                "randomSeed": 42,
            },
        }
    )
    worker = AnalysisWorker(queue)
    job_id = queue.submit(scenario, timeout_seconds=120.0)

    # Claim it, then cancel from "another process" while it computes.
    assert queue.claim_next() is not None
    assert queue.get(job_id)["status"] == "running"
    assert queue.cancel(job_id) == "cancellation_requested"

    # The worker observes the flag via its poller thread and aborts.
    worker._execute(job_id, scenario, timeout_seconds=120.0)

    assert queue.get(job_id)["status"] == "cancelled"
    assert "cancel" in (queue.get(job_id)["error"] or "").lower()


def test_get_unknown_job_raises_store_not_found(queue):
    with pytest.raises(StoreNotFound):
        queue.get("missing-job")


def test_redis_backend_delegates_submit_get_cancel(queue):
    backend = RedisJobBackend(queue)
    job_id = backend.submit(scenario_at_flop(), timeout_seconds=30.0)

    assert backend.get(job_id)["status"] == "queued"
    assert backend.cancel(job_id) == "cancelled"
    assert backend.get(job_id)["status"] == "cancelled"


def test_in_process_backend_roundtrip_and_cancel():
    from concurrent.futures import ThreadPoolExecutor

    from poker_coach.rules import PokerKitAdapter

    backend = InProcessJobBackend(PokerKitAdapter(), ThreadPoolExecutor(max_workers=1))
    job_id = backend.submit(scenario_at_flop(), timeout_seconds=30.0)

    final = None
    for _ in range(100):
        final = backend.get(job_id)
        if final["status"] in {"completed", "failed", "cancelled", "timeout"}:
            break
        time.sleep(0.01)
    assert final is not None
    assert final["status"] == "completed"
    assert final["analysis"]["evidence"]["items"]
