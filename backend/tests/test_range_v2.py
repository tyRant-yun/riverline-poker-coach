from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from statistics import median, quantiles
from time import perf_counter_ns

import pytest

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
    return _public_action(
        street=street,
        actor=3,
        action=SimulatorActionV1.BET,
        amount=amount,
    )


def _public_action(
    *,
    street: Street,
    actor: int,
    action: SimulatorActionV1,
    amount: int | None = None,
) -> ActionTakenPayloadV1:
    semantics = {
        SimulatorActionV1.FOLD: AmountSemanticsV1.NONE,
        SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
        SimulatorActionV1.CALL: AmountSemanticsV1.COST,
        SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
        SimulatorActionV1.BET: AmountSemanticsV1.BY,
    }[action]
    return ActionTakenPayloadV1(
        street=street,
        actor_seat=actor,
        action=action,
        amount=amount,
        amount_semantics=semantics,
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


def test_v2_reraise_to_uses_incremental_chips_for_bucket_and_likelihood():
    events = (
        _event(1, _started()),
        _event(2, _public_action(street=Street.PREFLOP, actor=3, action=SimulatorActionV1.RAISE, amount=500)),
        _event(3, _public_action(street=Street.PREFLOP, actor=4, action=SimulatorActionV1.CALL, amount=500)),
        _event(4, _public_action(street=Street.PREFLOP, actor=5, action=SimulatorActionV1.CALL, amount=500)),
        _event(5, _public_action(street=Street.PREFLOP, actor=0, action=SimulatorActionV1.CALL, amount=350)),
        _event(6, _public_action(street=Street.PREFLOP, actor=3, action=SimulatorActionV1.RAISE, amount=1_200)),
    )

    belief = PublicEventBeliefConsumer().beliefs_at(events)[3]
    update = belief.current.update
    assert update.observed_size == Decimal("1200")
    assert update.mapped_size == Decimal("700")
    assert update.action_label == "public_action:preflop:raise:small:utg:medium"
    assert "size_bucket:small" in update.assumptions

    reference = (
        _event(1, _started()),
        _event(2, _public_action(street=Street.PREFLOP, actor=4, action=SimulatorActionV1.CALL, amount=600)),
        _event(3, _public_action(street=Street.PREFLOP, actor=5, action=SimulatorActionV1.CALL, amount=600)),
        _event(4, _public_action(street=Street.PREFLOP, actor=0, action=SimulatorActionV1.CALL, amount=650)),
        _event(5, _public_action(street=Street.PREFLOP, actor=3, action=SimulatorActionV1.RAISE, amount=700)),
    )
    consumer = PublicEventBeliefConsumer()
    before_reraise = consumer.beliefs_at(events, after_sequence=5)[3].current
    before_reference = consumer.beliefs_at(reference, after_sequence=4)[3].current
    after_reference = consumer.beliefs_at(reference)[3].current
    actual_factor = (
        belief.current.combos["AsAh"].reach
        / before_reraise.combos["AsAh"].reach
    )
    reference_factor = (
        after_reference.combos["AsAh"].reach
        / before_reference.combos["AsAh"].reach
    )
    assert abs(actual_factor - reference_factor) < Decimal("1e-24")


@pytest.mark.parametrize(
    "action",
    (SimulatorActionV1.CALL, SimulatorActionV1.BET, SimulatorActionV1.RAISE),
)
def test_v2_river_busted_draw_has_no_future_card_likelihood_bonus(
    action: SimulatorActionV1,
):
    events = (
        _event(1, _started()),
        _event(2, BoardDealtPayloadV1(street=Street.FLOP, cards=("Kh", "7h", "2c"))),
        _event(3, BoardDealtPayloadV1(street=Street.TURN, cards=("Jh",))),
        _event(4, BoardDealtPayloadV1(street=Street.RIVER, cards=("3d",))),
        _event(5, _public_action(street=Street.RIVER, actor=3, action=action, amount=200)),
    )

    belief = PublicEventBeliefConsumer().beliefs_at(
        events, observer_visible_cards=("Qc", "Td")
    )[3]
    assert abs(
        _multiplier(belief, "Ah9s") - _multiplier(belief, "As9s")
    ) < Decimal("1e-24")


def test_v2_six_max_current_decision_latency_gate():
    events = (
        _event(1, _started()),
        _event(2, _public_action(street=Street.PREFLOP, actor=3, action=SimulatorActionV1.RAISE, amount=300)),
        _event(3, _public_action(street=Street.PREFLOP, actor=4, action=SimulatorActionV1.CALL, amount=300)),
        _event(4, _public_action(street=Street.PREFLOP, actor=5, action=SimulatorActionV1.CALL, amount=300)),
        _event(5, _public_action(street=Street.PREFLOP, actor=0, action=SimulatorActionV1.CALL, amount=300)),
        _event(6, _public_action(street=Street.PREFLOP, actor=1, action=SimulatorActionV1.CALL, amount=250)),
        _event(7, _public_action(street=Street.PREFLOP, actor=2, action=SimulatorActionV1.CALL, amount=200)),
        _event(8, BoardDealtPayloadV1(street=Street.FLOP, cards=("Kh", "7h", "2c"))),
        _event(9, _public_action(street=Street.FLOP, actor=1, action=SimulatorActionV1.CHECK)),
        _event(10, _public_action(street=Street.FLOP, actor=2, action=SimulatorActionV1.CHECK)),
        _event(11, _public_action(street=Street.FLOP, actor=3, action=SimulatorActionV1.BET, amount=600)),
        _event(12, _public_action(street=Street.FLOP, actor=4, action=SimulatorActionV1.CALL, amount=600)),
        _event(13, _public_action(street=Street.FLOP, actor=5, action=SimulatorActionV1.FOLD)),
        _event(14, BoardDealtPayloadV1(street=Street.TURN, cards=("Jh",))),
        _event(15, _public_action(street=Street.TURN, actor=3, action=SimulatorActionV1.CHECK)),
        _event(16, _public_action(street=Street.TURN, actor=4, action=SimulatorActionV1.BET, amount=1_500)),
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
        "range_v2_latency scope=16-event-preflop-flop-turn-replay+5-opponent-169-projection "
        f"warmup=10 samples=100 p50={p50:.3f}ms p95={p95:.3f}ms"
    )
    assert p50 < 25
    assert p95 < 50
