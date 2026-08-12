"""Thin event replay and projection spike over the PokerKit rule adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from poker_coach.domain.models import (
    ActionType,
    AmountType,
    ScenarioSpec,
    Street,
    positions_for_table,
)
from poker_coach.rules import PokerKitAdapter

from .contracts import (
    ActionTakenPayloadV1,
    BoardDealtPayloadV1,
    HandCompletedPayloadV1,
    HandEventV1,
    HandStartedPayloadV1,
    HandStateProjectionV1,
    HandStatisticsProjectionV1,
    HoleCardsRecordedPayloadV1,
    ReplayedHandV1,
    SeatStatisticsV1,
    SimulatorActionV1,
)


class EventStreamError(ValueError):
    """Stable validation failure for an append-only hand stream."""

    def __init__(self, code: str, message: str, sequence: int | None = None):
        self.code = code
        self.sequence = sequence
        prefix = f"event {sequence}: " if sequence is not None else ""
        super().__init__(f"{prefix}{message}")


def validate_hand_event_stream(events: Sequence[HandEventV1]) -> tuple[HandEventV1, ...]:
    """Return a validated immutable stream or reject its first inconsistency."""

    validated = tuple(events)
    if not validated:
        raise EventStreamError("empty_stream", "a hand stream requires at least one event")
    hand_id = validated[0].hand_id
    event_ids: set[str] = set()
    previous_timestamp = None
    for expected_sequence, event in enumerate(validated, start=1):
        if event.sequence != expected_sequence:
            raise EventStreamError(
                "out_of_order",
                f"expected sequence {expected_sequence}, got {event.sequence}",
                event.sequence,
            )
        if event.hand_id != hand_id:
            raise EventStreamError(
                "mixed_hand", "all events must share one hand_id", event.sequence
            )
        if event.event_id in event_ids:
            raise EventStreamError(
                "duplicate_event", f"duplicate event_id {event.event_id}", event.sequence
            )
        event_ids.add(event.event_id)
        if previous_timestamp is not None and event.timestamp < previous_timestamp:
            raise EventStreamError(
                "timestamp_regression",
                "timestamps must not move backwards within a hand",
                event.sequence,
            )
        previous_timestamp = event.timestamp

    started = validated[0].payload
    if not isinstance(started, HandStartedPayloadV1):
        raise EventStreamError("missing_start", "sequence 1 must be hand_started", 1)
    if started.rake_bps != 0:
        raise EventStreamError(
            "rake_not_supported", "F0 replay supports no-rake hands only", 1
        )
    if any(isinstance(event.payload, HandStartedPayloadV1) for event in validated[1:]):
        raise EventStreamError("duplicate_start", "hand_started may appear only once")

    completed_indexes = [
        index
        for index, event in enumerate(validated)
        if isinstance(event.payload, HandCompletedPayloadV1)
    ]
    if len(completed_indexes) > 1:
        raise EventStreamError("duplicate_completion", "hand_completed may appear only once")
    if completed_indexes and completed_indexes[0] != len(validated) - 1:
        event = validated[completed_indexes[0]]
        raise EventStreamError(
            "event_after_completion", "hand_completed must be the final event", event.sequence
        )

    known_cards: set[str] = set()
    recorded_seats: set[int] = set()
    expected_board_streets = iter((Street.FLOP, Street.TURN, Street.RIVER))
    next_board_street = next(expected_board_streets, None)
    for event in validated[1:]:
        payload = event.payload
        seat_id = getattr(payload, "seat_id", getattr(payload, "actor_seat", None))
        if seat_id is not None and seat_id >= started.table_size:
            raise EventStreamError(
                "invalid_seat", f"seat {seat_id} is not occupied", event.sequence
            )
        if seat_id is not None and seat_id not in started.active_seat_ids:
            raise EventStreamError(
                "inactive_seat", f"seat {seat_id} is not a hand participant", event.sequence
            )
        if isinstance(payload, HoleCardsRecordedPayloadV1):
            if payload.seat_id in recorded_seats:
                raise EventStreamError(
                    "duplicate_hole_cards",
                    f"seat {payload.seat_id} already has recorded cards",
                    event.sequence,
                )
            recorded_seats.add(payload.seat_id)
            if known_cards.intersection(payload.cards):
                raise EventStreamError(
                    "duplicate_card", "a recorded card is already known", event.sequence
                )
            known_cards.update(payload.cards)
        elif isinstance(payload, BoardDealtPayloadV1):
            if payload.street is not next_board_street:
                expected = None if next_board_street is None else next_board_street.value
                raise EventStreamError(
                    "board_order",
                    f"expected board street {expected}, got {payload.street.value}",
                    event.sequence,
                )
            if known_cards.intersection(payload.cards):
                raise EventStreamError(
                    "duplicate_card", "a board card is already known", event.sequence
                )
            known_cards.update(payload.cards)
            next_board_street = next(expected_board_streets, None)
        elif isinstance(payload, HandCompletedPayloadV1):
            if any(seat not in started.active_seat_ids for seat in payload.winner_seats):
                raise EventStreamError(
                    "invalid_winner", "winner seat is not a hand participant", event.sequence
                )
    return validated


def append_hand_event(
    events: Sequence[HandEventV1], event: HandEventV1
) -> tuple[HandEventV1, ...]:
    """Append without mutating or replacing any existing event."""

    return validate_hand_event_stream((*events, event))


def scenario_from_events(events: Sequence[HandEventV1]) -> ScenarioSpec:
    """Adapt one validated event stream to the existing PokerKit boundary."""

    stream = validate_hand_event_stream(events)
    started = stream[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    active_seats = started.active_seat_ids
    participant_count = len(active_seats)
    position_order = positions_for_table(participant_count)
    button_index = active_seats.index(started.button_seat)
    seats = [
        {
            "seatId": seat_id,
            "startingStack": started.starting_stacks[seat_id],
            "position": position_order[
                (active_seats.index(seat_id) - button_index) % participant_count
            ].value,
        }
        for seat_id in active_seats
    ]
    known_hole_cards: dict[int, tuple[str, str]] = {}
    board: list[str] = []
    action_history: list[dict[str, object]] = []
    action_type_map = {
        SimulatorActionV1.FOLD: ActionType.FOLD,
        SimulatorActionV1.CHECK: ActionType.CHECK,
        SimulatorActionV1.CALL: ActionType.CALL,
        SimulatorActionV1.BET: ActionType.BET,
        SimulatorActionV1.RAISE: ActionType.RAISE_TO,
    }
    deal_type_map = {
        Street.FLOP: ActionType.DEAL_FLOP,
        Street.TURN: ActionType.DEAL_TURN,
        Street.RIVER: ActionType.DEAL_RIVER,
    }
    for event in stream[1:]:
        payload = event.payload
        if isinstance(payload, HoleCardsRecordedPayloadV1):
            known_hole_cards[payload.seat_id] = payload.cards
        elif isinstance(payload, ActionTakenPayloadV1):
            item: dict[str, object] = {
                "actionId": event.event_id,
                "sequence": len(action_history) + 1,
                "street": payload.street.value,
                "actorSeat": payload.actor_seat,
                "actionType": action_type_map[payload.action].value,
            }
            if payload.amount is not None:
                item["amount"] = payload.amount
                item["amountType"] = payload.amount_semantics.value
            action_history.append(item)
        elif isinstance(payload, BoardDealtPayloadV1):
            board.extend(payload.cards)
            action_history.append(
                {
                    "actionId": event.event_id,
                    "sequence": len(action_history) + 1,
                    "street": payload.street.value,
                    "actorSeat": started.button_seat,
                    "actionType": deal_type_map[payload.street].value,
                }
            )

    visible_street = {
        0: Street.PREFLOP,
        3: Street.FLOP,
        4: Street.TURN,
        5: Street.RIVER,
    }[len(board)]
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": participant_count,
            "smallBlind": started.small_blind,
            "bigBlind": started.big_blind,
            "ante": started.ante,
            "buttonSeat": started.button_seat,
            "heroSeat": started.button_seat,
            "seats": seats,
            "knownHoleCardsBySeat": known_hole_cards,
            "board": board,
            "actionHistory": action_history,
            "decisionPoint": {
                "street": visible_street.value,
                "actorSeat": started.button_seat,
                "afterSequence": len(action_history),
            },
            "assumptions": {},
            "source": "imported",
            "tags": ["simulator-event-v1"],
        }
    )


def replay_hand(
    events: Sequence[HandEventV1], *, adapter: PokerKitAdapter | None = None
) -> ReplayedHandV1:
    """Rebuild authoritative state and read projections from only the events."""

    stream = validate_hand_event_stream(events)
    scenario = scenario_from_events(stream)
    result = (adapter or PokerKitAdapter()).replay(scenario)
    completion = next(
        (
            event.payload
            for event in stream
            if isinstance(event.payload, HandCompletedPayloadV1)
        ),
        None,
    )
    if completion is not None and (
        tuple(result.settlement.winner_seats) != tuple(completion.winner_seats)
        or result.settlement.payouts != completion.payouts
    ):
        raise EventStreamError(
            "completion_mismatch",
            "hand_completed winners/payouts disagree with PokerKit replay",
            stream[-1].sequence,
        )

    fingerprint_input = json.dumps(
        {
            "finalState": result.final_state.to_dict(),
            "settlement": result.settlement.to_dict(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    state = HandStateProjectionV1(
        hand_id=stream[0].hand_id,
        applied_sequence=stream[-1].sequence,
        rules_engine=result.rules_engine,
        rules_engine_version=result.rules_engine_version,
        street=result.final_state.street,
        board=result.final_state.board,
        pot=result.final_state.pot,
        stacks=result.final_state.stacks,
        street_commitments=result.final_state.bets,
        folded_seats=result.final_state.folded_seats,
        hand_in_progress=result.final_state.hand_in_progress,
        winner_seats=result.settlement.winner_seats,
        payouts=result.settlement.payouts,
        fingerprint=hashlib.sha256(fingerprint_input).hexdigest(),
    )
    statistics = _project_statistics(stream)
    return ReplayedHandV1(state=state, statistics=statistics)


def _project_statistics(events: Sequence[HandEventV1]) -> HandStatisticsProjectionV1:
    started = events[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    mutable = {
        seat: {"vpip": False, "pfr": False, "three_bet": False, "action_count": 0}
        for seat in started.active_seat_ids
    }
    preflop_raise_count = 0
    for event in events:
        payload = event.payload
        if not isinstance(payload, ActionTakenPayloadV1):
            continue
        stats = mutable[payload.actor_seat]
        stats["action_count"] += 1
        if payload.street is not Street.PREFLOP:
            continue
        if payload.action in {
            SimulatorActionV1.CALL,
            SimulatorActionV1.BET,
            SimulatorActionV1.RAISE,
        }:
            stats["vpip"] = True
        if payload.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
            preflop_raise_count += 1
            stats["pfr"] = True
            if preflop_raise_count == 2:
                stats["three_bet"] = True
    return HandStatisticsProjectionV1(
        hand_id=events[0].hand_id,
        applied_sequence=events[-1].sequence,
        by_seat={seat: SeatStatisticsV1(**values) for seat, values in mutable.items()},
    )
