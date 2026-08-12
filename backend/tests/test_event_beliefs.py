from datetime import datetime, timezone
from decimal import Decimal

from poker_coach.ranges.event_beliefs import PublicEventBeliefConsumer
from poker_coach.simulator.contracts import (ActionTakenPayloadV1, AmountSemanticsV1, BoardDealtPayloadV1, ContractProvenanceV1, EventSourceV1, HandEventV1, HandStartedPayloadV1, HoleCardsRecordedPayloadV1, SimulatorActionV1)
from poker_coach.domain.models import Street


def _event(sequence, payload):
    return HandEventV1(event_id=f"e{sequence}", hand_id="h", sequence=sequence, timestamp=datetime.now(timezone.utc), source=EventSourceV1.FIXTURE, provenance=ContractProvenanceV1(producer="test", producer_version="1", correlation_id="c"), payload=payload)


def _stream(*payloads, active=(0, 1, 2, 3, 4, 5), button=0, table_size=6):
    started = HandStartedPayloadV1(table_size=table_size, button_seat=button, small_blind=50, big_blind=100, starting_stacks={i: 10000 for i in range(table_size)}, active_seat_ids=active, rng_seed=1)
    return tuple(_event(i + 1, payload) for i, payload in enumerate((started, *payloads)))


def _action(seat, action):
    semantics = {SimulatorActionV1.FOLD: AmountSemanticsV1.NONE, SimulatorActionV1.CHECK: AmountSemanticsV1.NONE,
                 SimulatorActionV1.CALL: AmountSemanticsV1.COST, SimulatorActionV1.RAISE: AmountSemanticsV1.TO,
                 SimulatorActionV1.BET: AmountSemanticsV1.BY}[action]
    return ActionTakenPayloadV1(street=Street.PREFLOP, actor_seat=seat, action=action, amount=None if semantics is AmountSemanticsV1.NONE else 100, amount_semantics=semantics)


def test_actor_only_update_and_historical_prefix_is_deterministic():
    events = _stream(_action(2, SimulatorActionV1.RAISE), _action(3, SimulatorActionV1.CALL))
    consumer = PublicEventBeliefConsumer()
    at_one = consumer.beliefs_at(events, after_sequence=2)
    full = consumer.beliefs_at(events)
    assert at_one[2].current.retained_mass != at_one[2].prior.retained_mass
    assert at_one[3].current.retained_mass == at_one[3].prior.retained_mass
    assert at_one[2].to_json() == consumer.beliefs_at(events, after_sequence=2)[2].to_json()
    assert full[2].current.to_json() == at_one[2].current.to_json()


def test_board_filters_every_seat_and_normalizes_with_hero_blockers():
    events = _stream(BoardDealtPayloadV1(street=Street.FLOP, cards=("As", "Kd", "2c")))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events, observer_visible_cards=("Qh", "Qs"))
    for belief in beliefs.values():
        assert len(belief.current.combos) == 1081
        assert sum(combo.probability for combo in belief.current.combos.values()) == Decimal("1")
        assert all(card not in key for key in belief.current.combos for card in ("As", "Kd", "2c", "Qh", "Qs"))


def test_private_event_is_rejected_and_no_private_data_is_returned():
    events = _stream(HoleCardsRecordedPayloadV1(seat_id=4, cards=("As", "Kd")))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events)
    assert all(not belief.available and belief.unavailable_reason == "private_event_forbidden" for belief in beliefs.values())


def test_fold_call_raise_check_are_supported_and_sparse_seats_work():
    events = _stream(_action(2, SimulatorActionV1.FOLD), _action(3, SimulatorActionV1.CALL), _action(4, SimulatorActionV1.RAISE), _action(5, SimulatorActionV1.CHECK))
    beliefs = PublicEventBeliefConsumer().beliefs_at(events)
    assert all(belief.available for belief in beliefs.values())
    assert beliefs[4].current.retained_mass != beliefs[4].prior.retained_mass
    sparse = _stream(active=(0, 2, 3, 5, 6, 7), button=5, table_size=8)
    unavailable = PublicEventBeliefConsumer().beliefs_at(sparse)
    assert all(belief.unavailable_reason.startswith("prior_unavailable:table_size_unsupported") for belief in unavailable.values())
