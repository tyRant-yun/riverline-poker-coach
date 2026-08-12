"""Permission-safe observation projection for bot and agent ports."""

from __future__ import annotations

from collections.abc import Sequence

from poker_coach.domain.models import ActionType
from poker_coach.rules import PokerKitAdapter

from .contracts import (
    ActionTakenPayloadV1,
    AmountSemanticsV1,
    HandEventV1,
    HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1,
    LegalActionV1,
    ObservationV1,
    PublicActionV1,
    SimulatorActionV1,
)
from .replay import EventStreamError, scenario_from_events, validate_hand_event_stream


def build_observation(
    events: Sequence[HandEventV1],
    *,
    observer_seat: int,
    after_sequence: int,
    adapter: PokerKitAdapter | None = None,
) -> ObservationV1:
    """Project one decision without exposing another seat's private cards."""

    stream = validate_hand_event_stream(events)
    if after_sequence < 1 or after_sequence > len(stream):
        raise EventStreamError(
            "invalid_observation_sequence",
            f"after_sequence must be between 1 and {len(stream)}",
            after_sequence,
        )
    prefix = validate_hand_event_stream(stream[:after_sequence])
    started = prefix[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    if observer_seat < 0 or observer_seat >= started.table_size:
        raise EventStreamError(
            "invalid_observer", f"seat {observer_seat} is not occupied", after_sequence
        )
    own_cards = next(
        (
            event.payload.cards
            for event in prefix
            if isinstance(event.payload, HoleCardsRecordedPayloadV1)
            and event.payload.seat_id == observer_seat
        ),
        None,
    )
    if own_cards is None:
        raise EventStreamError(
            "missing_observer_cards",
            f"no private cards are recorded for observer seat {observer_seat}",
            after_sequence,
        )

    scenario = scenario_from_events(prefix)
    state = (adapter or PokerKitAdapter()).replay(scenario).final_state
    if state.actor_seat != observer_seat:
        raise EventStreamError(
            "observer_not_actor",
            f"seat {observer_seat} cannot act; current actor is {state.actor_seat}",
            after_sequence,
        )
    public_actions = tuple(
        PublicActionV1(
            sequence=event.sequence,
            street=event.payload.street,
            actor_seat=event.payload.actor_seat,
            action=event.payload.action,
            amount=event.payload.amount,
            amount_semantics=event.payload.amount_semantics,
        )
        for event in prefix
        if isinstance(event.payload, ActionTakenPayloadV1)
    )
    legal_actions = _project_legal_actions(state, observer_seat)
    occupied = set(range(started.table_size))
    folded = set(state.folded_seats)
    return ObservationV1(
        hand_id=prefix[0].hand_id,
        sequence=after_sequence,
        observer_seat=observer_seat,
        table_size=started.table_size,
        button_seat=started.button_seat,
        street=state.street,
        own_hole_cards=own_cards,
        board=state.board,
        pot=state.pot,
        stacks=state.stacks,
        street_commitments=state.bets,
        active_seats=tuple(sorted(occupied - folded)),
        folded_seats=tuple(sorted(folded)),
        public_actions=public_actions,
        legal_actions=legal_actions,
    )


def _project_legal_actions(state, observer_seat: int) -> tuple[LegalActionV1, ...]:
    projected: list[LegalActionV1] = []
    for action in state.legal_actions.actions:
        if action is ActionType.ALL_IN:
            # All-in is the inclusive maximum of bet/raise, not a sixth action.
            continue
        if action is ActionType.FOLD:
            projected.append(
                LegalActionV1(
                    action=SimulatorActionV1.FOLD,
                    amount_semantics=AmountSemanticsV1.NONE,
                )
            )
        elif action is ActionType.CHECK:
            projected.append(
                LegalActionV1(
                    action=SimulatorActionV1.CHECK,
                    amount_semantics=AmountSemanticsV1.NONE,
                )
            )
        elif action is ActionType.CALL:
            amount = state.legal_actions.call_amount
            if amount is None:
                raise EventStreamError("legal_action_projection", "call cost is missing")
            projected.append(
                LegalActionV1(
                    action=SimulatorActionV1.CALL,
                    amount_semantics=AmountSemanticsV1.COST,
                    min_amount=amount,
                    max_amount=amount,
                )
            )
        elif action in {ActionType.BET, ActionType.RAISE_TO}:
            minimum = state.legal_actions.min_raise_to
            maximum = state.legal_actions.max_raise_to
            if minimum is None or maximum is None:
                raise EventStreamError("legal_action_projection", "raise bounds are missing")
            if action is ActionType.BET:
                already_committed = state.bets[observer_seat]
                projected.append(
                    LegalActionV1(
                        action=SimulatorActionV1.BET,
                        amount_semantics=AmountSemanticsV1.BY,
                        min_amount=minimum - already_committed,
                        max_amount=maximum - already_committed,
                    )
                )
            else:
                projected.append(
                    LegalActionV1(
                        action=SimulatorActionV1.RAISE,
                        amount_semantics=AmountSemanticsV1.TO,
                        min_amount=minimum,
                        max_amount=maximum,
                    )
                )
    return tuple(projected)
