from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from statistics import median, quantiles
from time import perf_counter_ns

from poker_coach.domain.models import Street
from poker_coach.ranges.event_beliefs import PublicEventBeliefConsumer
from poker_coach.simulator.contracts import (
    ActionTakenPayloadV1,
    AmountSemanticsV1,
    BoardDealtPayloadV1,
    ContractProvenanceV1,
    EventSourceV1,
    HandEventV1,
    HandCompletedPayloadV1,
    HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1,
    SimulatorActionV1,
)
from poker_coach.simulator.table_insights import _compressed_belief, _public_stream


def _event(sequence: int, payload: object) -> HandEventV1:
    return HandEventV1(
        event_id=f"e{sequence}",
        hand_id="range-v2",
        sequence=sequence,
        timestamp=datetime(2026, 8, 20, tzinfo=timezone.utc),
        source=EventSourceV1.FIXTURE,
        provenance=ContractProvenanceV1(
            producer="range-v2-test", producer_version="1", correlation_id="range-v2"
        ),
        payload=payload,
    )


def _started(*, rng_seed: int = 1, stack: int = 10_000) -> HandStartedPayloadV1:
    return HandStartedPayloadV1(
        table_size=6,
        button_seat=0,
        small_blind=50,
        big_blind=100,
        starting_stacks={seat: stack for seat in range(6)},
        active_seat_ids=(0, 1, 2, 3, 4, 5),
        rng_seed=rng_seed,
    )


def _bet(*, amount: int, street: Street = Street.FLOP) -> ActionTakenPayloadV1:
    return ActionTakenPayloadV1(
        street=street,
        actor_seat=3,
        action=SimulatorActionV1.BET,
        amount=amount,
        amount_semantics=AmountSemanticsV1.BY,
    )


def _postflop_belief(*, amount: int = 300, stack: int = 10_000):
    events = (
        _event(1, _started(stack=stack)),
        _event(2, BoardDealtPayloadV1(street=Street.FLOP, cards=("Kh", "7h", "2c"))),
        _event(3, _bet(amount=amount)),
    )
    return PublicEventBeliefConsumer().beliefs_at(
        events, observer_visible_cards=("As", "Qd")
    )[3]


def _multiplier(belief: object, combo: str) -> Decimal:
    prior = belief.prior.combos[combo].probability
    current = belief.current.combos[combo].probability
    return current / prior


def test_v2_public_action_uses_size_street_position_spr_and_board_features():
    small = _postflop_belief(amount=50)
    large = _postflop_belief(amount=400)

    assert _multiplier(large, "KsKd") > _multiplier(small, "KsKd")
    assert _multiplier(large, "AhQh") > _multiplier(large, "AcQs")
    assert _multiplier(large, "KsKd") > _multiplier(large, "9s8d")

    update = large.current.update
    assert update.action_label == "public_action:flop:bet:overbet:utg:deep"
    assert {
        "size_bucket:overbet",
        "street:flop",
        "position:utg",
        "spr_bucket:deep",
        "hand_features:made-hand/draw-aware",
    }.issubset(set(update.assumptions))


def test_v2_summary_is_additive_stable_and_never_exposes_combo_detail():
    belief = _postflop_belief(amount=400)
    summary = _compressed_belief(belief, "range-v2")

    assert summary["changeReason"] == "public_action:flop:bet:overbet:utg:deep"
    assert summary["dataVersion"] == "heuristic_likelihood_v2"
    assert summary["confidence"] == "heuristic"
    assert 0 < summary["confidenceScore"] < 1
    assert summary["rangeWidthCombos"] > 0
    assert len(summary["topClasses"]) == 6
    assert len(summary["matrix169"]) <= 169
    serialized = str(summary)
    assert "KsKd" not in serialized
    assert "AhQh" not in serialized


def test_v2_same_public_prefix_ignores_rng_private_terminal_and_future_events():
    prefix = (
        _event(1, _started(rng_seed=1)),
        _event(2, BoardDealtPayloadV1(street=Street.FLOP, cards=("Kh", "7h", "2c"))),
        _event(3, _bet(amount=300)),
    )
    alternate_rng = (prefix[0].model_copy(update={"payload": _started(rng_seed=999)}), *prefix[1:])
    poison = (
        *prefix,
        _event(4, HandCompletedPayloadV1(winner_seats=(3,), payouts={3: 1_200})),
        _event(5, HoleCardsRecordedPayloadV1(seat_id=3, cards=("Kd", "Ks"))),
        _event(6, BoardDealtPayloadV1(street=Street.TURN, cards=("Jh",))),
    )
    consumer = PublicEventBeliefConsumer()

    baseline = consumer.beliefs_at(prefix, observer_visible_cards=("As", "Qd"))[3]
    rng_changed = consumer.beliefs_at(alternate_rng, observer_visible_cards=("As", "Qd"))[3]
    future_ignored = consumer.beliefs_at(
        poison, observer_visible_cards=("As", "Qd"), after_sequence=3
    )[3]
    filtered = consumer.beliefs_at(
        _public_stream(poison)[:3], observer_visible_cards=("As", "Qd")
    )[3]
    rejected = consumer.beliefs_at(poison, observer_visible_cards=("As", "Qd"))

    assert baseline.current.to_json() == rng_changed.current.to_json()
    assert baseline.current.to_json() == future_ignored.current.to_json()
    assert baseline.current.to_json() == filtered.current.to_json()
    assert all(
        not belief.available and belief.unavailable_reason == "private_event_forbidden"
        for belief in rejected.values()
    )


def test_v2_six_max_current_decision_latency_gate():
    events = (
        _event(1, _started()),
        _event(2, BoardDealtPayloadV1(street=Street.FLOP, cards=("Kh", "7h", "2c"))),
        _event(3, _bet(amount=300)),
    )
    consumer = PublicEventBeliefConsumer()
    visible = ("As", "Qd")

    for _ in range(10):
        consumer.beliefs_at(events, observer_visible_cards=visible)
    samples_ms = []
    for _ in range(100):
        started = perf_counter_ns()
        result = consumer.beliefs_at(events, observer_visible_cards=visible)
        summaries = [
            _compressed_belief(belief, "range-v2")
            for seat, belief in result.items()
            if seat != 0
        ]
        samples_ms.append((perf_counter_ns() - started) / 1_000_000)
        assert len(result) == 6
        assert all(seat.current is not None for seat in result.values())
        assert all("matrix169" in summary for summary in summaries)

    p50 = median(samples_ms)
    p95 = quantiles(samples_ms, n=100, method="inclusive")[94]
    print(
        "range_v2_latency scope=6-seat-update+5-opponent-169-projection "
        f"warmup=10 samples=100 p50={p50:.3f}ms p95={p95:.3f}ms"
    )
    assert p50 < 25
    assert p95 < 50
