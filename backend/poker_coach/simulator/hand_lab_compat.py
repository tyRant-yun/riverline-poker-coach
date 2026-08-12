"""Versioned compatibility adapter between authoritative hands and Hand Lab.

This module deliberately translates facts; it does not calculate a legal
action, chips, settlement, equity, or a new rules state.  PokerKit remains
the authority for both the source replay and the re-validation performed by
the existing ScenarioSpec boundary.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Literal

from pydantic import Field

from poker_coach.domain.models import (
    ActionEvent,
    ActionType,
    AmountType,
    ScenarioSpec,
    Street,
    positions_for_table,
)
from poker_coach.rules import PokerKitAdapter, ReplayError

from .contracts import (
    ActionTakenPayloadV1,
    BoardDealtPayloadV1,
    HandEventV1,
    HandCompletedPayloadV1,
    HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1,
    ObservationV1,
    ReplayedHandV1,
    SimulatorContractV1,
    SimulatorActionV1,
)
from .orchestrator import PlayerActionCommandV1
from .replay import replay_hand, scenario_from_events, validate_hand_event_stream


class HandLabCompatibilityError(ValueError):
    """An honest, stable reason why an event hand cannot enter Hand Lab."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class HandLabScenarioV1(SimulatorContractV1):
    """A ScenarioSpec plus topology/visibility facts ScenarioSpec cannot hold.

    ``scenario.table_size`` is intentionally the number of current hand
    participants: that is the ring that the legacy ScenarioSpec/PokerKit
    adapter can replay.  ``authoritative_table_size`` remains the physical
    session-table capacity, so a sparse 6-max hand is never presented as a
    three- or four-seat table at the authoritative boundary.
    """

    compatibility_version: Literal[1] = 1
    hand_id: str = Field(min_length=1, max_length=128)
    applied_sequence: int = Field(ge=1)
    authoritative_table_size: int = Field(ge=2, le=8)
    active_seat_ids: tuple[int, ...]
    participant_count: int = Field(ge=2, le=8)
    visible_hole_card_seat_ids: tuple[int, ...] = ()
    degradation_reasons: tuple[str, ...] = ()
    scenario: ScenarioSpec


def scenario_from_authoritative_events(
    events: Sequence[HandEventV1],
    *,
    hero_seat: int,
    authorized_hole_card_seat_ids: Collection[int] = (),
    replayed_hand: ReplayedHandV1 | None = None,
    adapter: PokerKitAdapter | None = None,
) -> HandLabScenarioV1:
    """Project one authoritative event prefix into legacy Hand Lab input.

    Callers must pass the seats whose cards their server-side reveal policy
    authorizes.  No opponent card is inferred from a completion event or from
    the authoritative replay.  A spectator therefore gets an empty set by
    default, while a player may explicitly pass only that player's own seat.
    """

    stream = validate_hand_event_stream(events)
    started = stream[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    active_seats = started.active_seat_ids
    if hero_seat not in active_seats:
        raise HandLabCompatibilityError(
            "invalid_hero_seat", "hero_seat must be a current hand participant"
        )

    authorized = tuple(sorted(set(authorized_hole_card_seat_ids)))
    if not set(authorized).issubset(active_seats):
        raise HandLabCompatibilityError(
            "invalid_hole_card_visibility",
            "authorized hole-card seats must be current hand participants",
        )

    rules_adapter = adapter or PokerKitAdapter()
    authoritative = replayed_hand or replay_hand(stream, adapter=rules_adapter)
    if authoritative.state.hand_id != stream[0].hand_id:
        raise HandLabCompatibilityError(
            "replay_state_mismatch", "replay state belongs to a different hand"
        )
    if authoritative.state.applied_sequence != stream[-1].sequence:
        raise HandLabCompatibilityError(
            "replay_state_mismatch", "replay state does not cover the event prefix"
        )

    recorded_hole_cards = {
        event.payload.seat_id: event.payload.cards
        for event in stream
        if isinstance(event.payload, HoleCardsRecordedPayloadV1)
    }
    known_hole_cards = {
        seat_id: recorded_hole_cards[seat_id]
        for seat_id in authorized
        if seat_id in recorded_hole_cards
    }
    degradation_reasons: list[str] = []
    if hero_seat not in known_hole_cards:
        if hero_seat in recorded_hole_cards:
            degradation_reasons.append("hero_hole_cards_not_authorized")
        else:
            degradation_reasons.append("hero_hole_cards_not_recorded")

    # A terminal fold can be replayed without private cards.  A completed
    # multi-player showdown cannot: accepting it with a hidden contender's
    # cards would make the compatibility adapter silently assert a result it
    # cannot evidence.  Events contain folds as facts, so this check does not
    # recreate any game rules in the UI layer.
    completed = any(
        isinstance(event.payload, HandCompletedPayloadV1) for event in stream
    )
    folded_seats = {
        event.payload.actor_seat
        for event in stream
        if isinstance(event.payload, ActionTakenPayloadV1)
        and event.payload.action is SimulatorActionV1.FOLD
    }
    showdown_seats = set(active_seats) - folded_seats
    if completed and len(showdown_seats) > 1:
        missing_showdown_cards = showdown_seats - set(known_hole_cards)
        if missing_showdown_cards:
            raise HandLabCompatibilityError(
                "insufficient_visible_facts",
                "completed showdown requires authorized recorded cards for every live seat",
            )

    participant_count = len(active_seats)
    positions = positions_for_table(participant_count)
    button_index = active_seats.index(started.button_seat)
    seats = [
        {
            "seatId": seat_id,
            "startingStack": started.starting_stacks[seat_id],
            "position": positions[(index - button_index) % participant_count].value,
        }
        for index, seat_id in enumerate(active_seats)
    ]
    board: list[str] = []
    actions: list[dict[str, object]] = []
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
        if isinstance(payload, ActionTakenPayloadV1):
            item: dict[str, object] = {
                "actionId": event.event_id,
                "sequence": len(actions) + 1,
                "street": payload.street.value,
                "actorSeat": payload.actor_seat,
                "actionType": action_type_map[payload.action].value,
            }
            if payload.amount is not None:
                item["amount"] = payload.amount
                item["amountType"] = payload.amount_semantics.value
            actions.append(item)
        elif isinstance(payload, BoardDealtPayloadV1):
            board.extend(payload.cards)
            actions.append(
                {
                    "actionId": event.event_id,
                    "sequence": len(actions) + 1,
                    "street": payload.street.value,
                    "actorSeat": started.button_seat,
                    "actionType": deal_type_map[payload.street].value,
                }
            )

    # HandStateProjectionV1 intentionally has no current actor: it is a
    # compact, public projection.  Ask PokerKit for that fact through the
    # pre-existing trusted replay adapter instead of reconstructing turns here.
    trusted_state = rules_adapter.replay(scenario_from_events(stream)).final_state
    state = authoritative.state
    decision_actor = trusted_state.actor_seat if trusted_state.actor_seat is not None else hero_seat
    scenario = ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": participant_count,
            "smallBlind": started.small_blind,
            "bigBlind": started.big_blind,
            "ante": started.ante,
            "buttonSeat": started.button_seat,
            "heroSeat": hero_seat,
            "seats": seats,
            "knownHoleCardsBySeat": known_hole_cards,
            "board": board,
            "actionHistory": actions,
            "decisionPoint": {
                "street": state.street.value,
                "actorSeat": decision_actor,
                "afterSequence": len(actions),
            },
            "assumptions": {},
            "source": "imported",
            "tags": ["simulator-event-v1", "hand-lab-compat-v1"],
        }
    )

    # The legacy boundary remains an adapter over PokerKit.  If the caller's
    # visibility is too narrow to reproduce a completed showdown, do not
    # manufacture a complete ScenarioSpec; return a stable honest error.
    try:
        visible_result = rules_adapter.replay(scenario)
    except ReplayError as exc:
        raise HandLabCompatibilityError(
            "insufficient_visible_facts",
            "authorized cards cannot replay this hand in Hand Lab",
        ) from exc
    if (
        visible_result.final_state.street != state.street
        or visible_result.final_state.board != state.board
        or visible_result.final_state.pot != state.pot
        or visible_result.final_state.stacks != state.stacks
        or visible_result.final_state.hand_in_progress != state.hand_in_progress
        or visible_result.settlement.winner_seats != state.winner_seats
        or visible_result.settlement.payouts != state.payouts
    ):
        raise HandLabCompatibilityError(
            "insufficient_visible_facts",
            "authorized cards cannot reproduce the authoritative replay state",
        )

    return HandLabScenarioV1(
        hand_id=stream[0].hand_id,
        applied_sequence=stream[-1].sequence,
        authoritative_table_size=started.table_size,
        active_seat_ids=active_seats,
        participant_count=participant_count,
        visible_hole_card_seat_ids=tuple(sorted(known_hole_cards)),
        degradation_reasons=tuple(degradation_reasons),
        scenario=scenario,
    )


def player_action_command_from_hand_lab(
    *,
    session_id: str,
    hand_id: str,
    command_id: str,
    expected_sequence: int,
    action: ActionEvent,
    observation: ObservationV1 | None = None,
) -> PlayerActionCommandV1:
    """Translate an existing Hand Lab action intent without validating rules.

    Only the five action kinds already supported by Hand Lab are accepted.
    The GameOrchestrator still obtains legal actions and amount bounds from
    PokerKit before it appends anything to the authoritative stream.
    """

    supported = {
        ActionType.FOLD: (SimulatorActionV1.FOLD, AmountType.NONE),
        ActionType.CHECK: (SimulatorActionV1.CHECK, AmountType.NONE),
        ActionType.CALL: (SimulatorActionV1.CALL, AmountType.COST),
        ActionType.BET: (SimulatorActionV1.BET, AmountType.BY),
        ActionType.RAISE_TO: (SimulatorActionV1.RAISE, AmountType.TO),
    }
    if action.action_type is ActionType.ALL_IN:
        if observation is None or observation.observer_seat != action.actor_seat:
            raise HandLabCompatibilityError(
                "all_in_requires_authoritative_observation",
                "all_in needs the acting seat's authoritative legal-action observation",
            )
        commitment = observation.street_commitments[action.actor_seat]
        candidates = []
        for legal in observation.legal_actions:
            if legal.action not in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
                continue
            if legal.max_amount is None:
                continue
            legacy_all_in_to = (
                legal.max_amount + commitment
                if legal.action is SimulatorActionV1.BET
                else legal.max_amount
            )
            if action.amount == legacy_all_in_to:
                candidates.append(legal)
        if len(candidates) != 1:
            raise HandLabCompatibilityError(
                "all_in_not_authoritative_endpoint",
                "all_in amount must match exactly one authoritative bet/raise maximum",
            )
        legal = candidates[0]
        return PlayerActionCommandV1(
            session_id=session_id,
            hand_id=hand_id,
            command_id=command_id,
            expected_sequence=expected_sequence,
            actor_seat=action.actor_seat,
            action=legal.action,
            amount=legal.max_amount,
            amount_semantics=legal.amount_semantics,
        )

    mapped = supported.get(action.action_type)
    if mapped is None:
        raise HandLabCompatibilityError(
            "unsupported_hand_lab_action",
            f"{action.action_type.value} is not a supported Hand Lab player action",
        )
    simulator_action, amount_type = mapped
    if action.amount_type is not amount_type:
        raise HandLabCompatibilityError(
            "amount_semantics_mismatch",
            f"{action.action_type.value} must retain amount_type={amount_type.value}",
        )
    return PlayerActionCommandV1(
        session_id=session_id,
        hand_id=hand_id,
        command_id=command_id,
        expected_sequence=expected_sequence,
        actor_seat=action.actor_seat,
        action=simulator_action,
        amount=action.amount,
        amount_semantics=amount_type.value,
    )
