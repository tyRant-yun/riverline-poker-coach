"""PokerKit-backed command seam for one durable authoritative hand."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from poker_coach.domain.models import DomainModel, ScenarioSpec, positions_for_table
from poker_coach.rules import PokerKitAdapter

from .contracts import (
    ActionTakenPayloadV1,
    AmountSemanticsV1,
    BoardDealtPayloadV1,
    ContractProvenanceV1,
    EventSourceV1,
    HandCompletedPayloadV1,
    HandEventV1,
    HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1,
    ReplayedHandV1,
    SimulatorActionV1,
)
from .event_store import ExpectedSequenceConflict, HandEventStore, RawHandEventV1
from .observation import build_observation
from .replay import replay_hand, scenario_from_events
from .session import GameSession, SessionLifecycleError


class OpenHandCommandV1(DomainModel):
    """Versioned system command that materializes an active hand's opening facts."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    session_id: str = Field(min_length=1, max_length=96)
    hand_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    expected_sequence: Annotated[StrictInt, Field(ge=0)]
    actor: Literal["game_orchestrator"] = "game_orchestrator"
    rng_seed: Annotated[StrictInt, Field(ge=0)]


class GameCommandError(ValueError):
    """Stable project-owned rejection for a hand command."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PlayerActionCommandV1(DomainModel):
    """Versioned player intent; amounts use the frozen LegalActionV1 semantics."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    session_id: str = Field(min_length=1, max_length=96)
    hand_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    expected_sequence: Annotated[StrictInt, Field(ge=1)]
    actor_seat: Annotated[StrictInt, Field(ge=0, le=7)]
    action: SimulatorActionV1
    amount: Annotated[StrictInt, Field(ge=0)] | None = None
    amount_semantics: AmountSemanticsV1 = AmountSemanticsV1.NONE

    @model_validator(mode="after")
    def validate_amount_semantics(self) -> PlayerActionCommandV1:
        ActionTakenPayloadV1(
            street="preflop",
            actor_seat=self.actor_seat,
            action=self.action,
            amount=self.amount,
            amount_semantics=self.amount_semantics,
        )
        return self


class GameCommandResultV1(DomainModel):
    """Observable result of one accepted or idempotently reconciled command."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    session: GameSession
    appended_events: tuple[HandEventV1, ...]
    replayed_hand: ReplayedHandV1
    idempotent: bool = False


class GameOrchestrator:
    """Rebuild, validate through PokerKit, then atomically append hand facts."""

    producer = "riverline-game-orchestrator"
    producer_version = "1.0.0"

    def __init__(
        self,
        event_store: HandEventStore,
        *,
        adapter: PokerKitAdapter | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._event_store = event_store
        self._adapter = adapter or PokerKitAdapter()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def open_hand(
        self, session: GameSession, command: OpenHandCommandV1
    ) -> GameCommandResultV1:
        active = session.active_hand
        if active is None:
            raise SessionLifecycleError("no_active_hand", "session has no active hand")
        if command.session_id != session.session_id:
            raise SessionLifecycleError(
                "session_ownership_mismatch", "command session ID does not match the session"
            )
        if command.hand_id != active.hand_id:
            raise SessionLifecycleError(
                "hand_ownership_mismatch", "command hand ID is not the session's active hand"
            )

        durable = tuple(item.event for item in self._event_store.read(command.hand_id))
        if durable:
            self._validate_opening_facts(session, durable)
            caused = tuple(
                event
                for event in durable
                if event.provenance.causation_id == command.command_id
            )
            if not caused:
                raise ExpectedSequenceConflict(
                    hand_id=command.hand_id,
                    expected_sequence=command.expected_sequence,
                    actual_sequence=durable[-1].sequence,
                )
            started = next(
                (
                    event
                    for event in caused
                    if isinstance(event.payload, HandStartedPayloadV1)
                ),
                None,
            )
            if (
                started is None
                or started.sequence != command.expected_sequence + 1
                or started.payload.rng_seed != command.rng_seed
            ):
                raise GameCommandError(
                    "command_id_conflict",
                    "command_id is already durable with a different opening intent",
                )
            replayed = replay_hand(durable, adapter=self._adapter)
            successor = session
            if not replayed.state.hand_in_progress:
                successor = session.complete_active_hand(
                    hand_id=command.hand_id,
                    ending_stacks=replayed.state.stacks,
                )
            return GameCommandResultV1(
                session=successor,
                appended_events=(),
                replayed_hand=replayed,
                idempotent=True,
            )

        scenario = _opening_scenario(session)
        deal = self._adapter.deal_seeded(scenario, rng_seed=command.rng_seed)
        payloads = [
            HandStartedPayloadV1(
                ruleset=session.configuration.ruleset,
                table_size=len(active.seats),
                button_seat=active.button_seat,
                small_blind=session.configuration.small_blind,
                big_blind=session.configuration.big_blind,
                ante=session.configuration.ante,
                rake_bps=session.configuration.rake_bps,
                starting_stacks={
                    seat.seat_id: seat.starting_stack for seat in active.seats
                },
                rng_seed=command.rng_seed,
            ),
            *(
                HoleCardsRecordedPayloadV1(
                    seat_id=seat_id,
                    cards=deal.hole_cards_by_seat[seat_id],
                )
                for seat_id in sorted(deal.hole_cards_by_seat)
            ),
        ]
        events = self._events_for(
            hand_id=command.hand_id,
            session_id=command.session_id,
            command_id=command.command_id,
            expected_sequence=command.expected_sequence,
            payloads=payloads,
        )
        replayed = replay_hand(events, adapter=self._adapter)
        try:
            self._event_store.append(
                hand_id=command.hand_id,
                expected_sequence=command.expected_sequence,
                events=tuple(RawHandEventV1.from_event(event) for event in events),
            )
        except ExpectedSequenceConflict as conflict:
            latest = tuple(
                item.event for item in self._event_store.read(command.hand_id)
            )
            committed_start = next(
                (
                    item
                    for item in latest
                    if item.provenance.causation_id == command.command_id
                    and isinstance(item.payload, HandStartedPayloadV1)
                ),
                None,
            )
            if (
                committed_start is None
                or committed_start.sequence != command.expected_sequence + 1
                or committed_start.payload.rng_seed != command.rng_seed
            ):
                raise GameCommandError(
                    "append_conflict",
                    f"durable head advanced to {conflict.actual_sequence}; command was not retried",
                ) from conflict
            self._validate_opening_facts(session, latest)
            reconciled = replay_hand(latest, adapter=self._adapter)
            return GameCommandResultV1(
                session=session,
                appended_events=(),
                replayed_hand=reconciled,
                idempotent=True,
            )
        return GameCommandResultV1(
            session=session,
            appended_events=events,
            replayed_hand=replayed,
        )

    def execute(
        self, session: GameSession, command: PlayerActionCommandV1
    ) -> GameCommandResultV1:
        if command.session_id != session.session_id:
            raise SessionLifecycleError(
                "session_ownership_mismatch", "command session ID does not match the session"
            )
        active = session.active_hand
        owns_active = active is not None and command.hand_id == active.hand_id
        owns_completed = command.hand_id in session.completed_hand_ids
        if not owns_active and not owns_completed:
            raise SessionLifecycleError(
                "hand_ownership_mismatch", "command hand ID does not belong to the session"
            )

        durable = tuple(item.event for item in self._event_store.read(command.hand_id))
        if not durable:
            raise GameCommandError(
                "hand_not_opened", "no durable opening facts exist for this hand"
            )
        if active is not None:
            self._validate_opening_facts(session, durable)
        caused = tuple(
            event
            for event in durable
            if event.provenance.causation_id == command.command_id
        )
        if caused:
            action_event = next(
                (
                    event
                    for event in caused
                    if isinstance(event.payload, ActionTakenPayloadV1)
                ),
                None,
            )
            expected_payload = (
                command.actor_seat,
                command.action,
                command.amount,
                command.amount_semantics,
                command.expected_sequence + 1,
            )
            actual_payload = (
                None
                if action_event is None
                else (
                    action_event.payload.actor_seat,
                    action_event.payload.action,
                    action_event.payload.amount,
                    action_event.payload.amount_semantics,
                    action_event.sequence,
                )
            )
            if actual_payload != expected_payload:
                raise GameCommandError(
                    "command_id_conflict",
                    "command_id is already durable with a different intent",
                )
            replayed = replay_hand(durable, adapter=self._adapter)
            successor = session
            if not replayed.state.hand_in_progress and active is not None:
                successor = session.complete_active_hand(
                    hand_id=command.hand_id,
                    ending_stacks=replayed.state.stacks,
                )
            return GameCommandResultV1(
                session=successor,
                appended_events=(),
                replayed_hand=replayed,
                idempotent=True,
            )
        if any(isinstance(event.payload, HandCompletedPayloadV1) for event in durable):
            raise GameCommandError(
                "hand_completed", "hand has completed; no further action is legal"
            )
        if active is None:
            raise GameCommandError(
                "hand_completed", "hand has completed; no further action is legal"
            )
        actual_sequence = durable[-1].sequence if durable else 0
        if actual_sequence != command.expected_sequence:
            raise ExpectedSequenceConflict(
                hand_id=command.hand_id,
                expected_sequence=command.expected_sequence,
                actual_sequence=actual_sequence,
            )
        authoritative = self._adapter.replay(scenario_from_events(durable)).final_state
        if authoritative.actor_seat != command.actor_seat:
            raise GameCommandError(
                "wrong_actor",
                f"expected actor seat {authoritative.actor_seat}, received seat {command.actor_seat}",
            )
        observation = build_observation(
            durable,
            observer_seat=command.actor_seat,
            after_sequence=actual_sequence,
            adapter=self._adapter,
        )
        legal = next(
            (
                candidate
                for candidate in observation.legal_actions
                if candidate.action is command.action
            ),
            None,
        )
        if legal is None:
            raise GameCommandError(
                "action_not_legal",
                f"{command.action.value} is not legal in the current PokerKit state",
            )
        if not legal.accepts(action=command.action, amount=command.amount):
            raise GameCommandError(
                "amount_out_of_bounds",
                f"{command.action.value} amount is outside PokerKit's legal bounds",
            )

        action_payload = ActionTakenPayloadV1(
            street=observation.street,
            actor_seat=command.actor_seat,
            action=command.action,
            amount=command.amount,
            amount_semantics=command.amount_semantics,
        )
        payloads: list[object] = [action_payload]
        event = self._events_for(
            hand_id=command.hand_id,
            session_id=command.session_id,
            command_id=command.command_id,
            expected_sequence=command.expected_sequence,
            payloads=payloads,
            after_timestamp=durable[-1].timestamp,
        )
        candidate = (*durable, *event)
        rule_result = self._adapter.replay(scenario_from_events(candidate))
        started = durable[0].payload
        assert isinstance(started, HandStartedPayloadV1)
        seeded_deal = None
        while (
            rule_result.final_state.hand_in_progress
            and rule_result.final_state.actor_seat is None
            and len(rule_result.final_state.board) < 5
        ):
            if seeded_deal is None:
                seeded_deal = self._adapter.deal_seeded(
                    scenario_from_events(durable), rng_seed=started.rng_seed
                )
            board_length = len(rule_result.final_state.board)
            street, start, end = {
                0: ("flop", 0, 3),
                3: ("turn", 3, 4),
                4: ("river", 4, 5),
            }[board_length]
            payloads.append(
                BoardDealtPayloadV1(
                    street=street,
                    cards=seeded_deal.board[start:end],
                )
            )
            event = self._events_for(
                hand_id=command.hand_id,
                session_id=command.session_id,
                command_id=command.command_id,
                expected_sequence=command.expected_sequence,
                payloads=payloads,
                after_timestamp=durable[-1].timestamp,
            )
            candidate = (*durable, *event)
            rule_result = self._adapter.replay(scenario_from_events(candidate))

        replayed = replay_hand(candidate, adapter=self._adapter)
        successor = session
        if not replayed.state.hand_in_progress:
            event = self._events_for(
                hand_id=command.hand_id,
                session_id=command.session_id,
                command_id=command.command_id,
                expected_sequence=command.expected_sequence,
                payloads=(
                    *payloads,
                    HandCompletedPayloadV1(
                        winner_seats=replayed.state.winner_seats,
                        payouts=replayed.state.payouts,
                    ),
                ),
                after_timestamp=durable[-1].timestamp,
            )
            replayed = replay_hand((*durable, *event), adapter=self._adapter)
            successor = session.complete_active_hand(
                hand_id=command.hand_id,
                ending_stacks=replayed.state.stacks,
            )
        try:
            self._event_store.append(
                hand_id=command.hand_id,
                expected_sequence=command.expected_sequence,
                events=tuple(RawHandEventV1.from_event(item) for item in event),
            )
        except ExpectedSequenceConflict as conflict:
            latest = tuple(
                item.event for item in self._event_store.read(command.hand_id)
            )
            committed_action = next(
                (
                    item
                    for item in latest
                    if item.provenance.causation_id == command.command_id
                    and isinstance(item.payload, ActionTakenPayloadV1)
                ),
                None,
            )
            if committed_action is None or (
                committed_action.payload.actor_seat,
                committed_action.payload.action,
                committed_action.payload.amount,
                committed_action.payload.amount_semantics,
                committed_action.sequence,
            ) != (
                command.actor_seat,
                command.action,
                command.amount,
                command.amount_semantics,
                command.expected_sequence + 1,
            ):
                raise GameCommandError(
                    "append_conflict",
                    f"durable head advanced to {conflict.actual_sequence}; command was not retried",
                ) from conflict
            reconciled = replay_hand(latest, adapter=self._adapter)
            reconciled_session = session
            if not reconciled.state.hand_in_progress:
                reconciled_session = session.complete_active_hand(
                    hand_id=command.hand_id,
                    ending_stacks=reconciled.state.stacks,
                )
            return GameCommandResultV1(
                session=reconciled_session,
                appended_events=(),
                replayed_hand=reconciled,
                idempotent=True,
            )
        return GameCommandResultV1(
            session=successor,
            appended_events=event,
            replayed_hand=replayed,
        )

    def _validate_opening_facts(
        self, session: GameSession, durable: Sequence[HandEventV1]
    ) -> None:
        active = session.active_hand
        assert active is not None
        started = durable[0].payload
        expected = (
            session.configuration.ruleset,
            len(active.seats),
            active.button_seat,
            session.configuration.small_blind,
            session.configuration.big_blind,
            session.configuration.ante,
            session.configuration.rake_bps,
            {seat.seat_id: seat.starting_stack for seat in active.seats},
            session.session_id,
        )
        actual = (
            None
            if not isinstance(started, HandStartedPayloadV1)
            else (
                started.ruleset,
                started.table_size,
                started.button_seat,
                started.small_blind,
                started.big_blind,
                started.ante,
                started.rake_bps,
                started.starting_stacks,
                durable[0].provenance.correlation_id,
            )
        )
        if actual != expected:
            raise GameCommandError(
                "opening_facts_mismatch",
                "durable hand opening facts do not match the active session hand",
            )

    def _events_for(
        self,
        *,
        hand_id: str,
        session_id: str,
        command_id: str,
        expected_sequence: int,
        payloads: Sequence[object],
        after_timestamp: datetime | None = None,
    ) -> tuple[HandEventV1, ...]:
        base_timestamp = self._clock()
        if base_timestamp.tzinfo is None or base_timestamp.utcoffset() is None:
            raise ValueError("orchestrator clock must return a timezone-aware datetime")
        if after_timestamp is not None:
            base_timestamp = max(
                base_timestamp, after_timestamp + timedelta(microseconds=1)
            )
        events: list[HandEventV1] = []
        for offset, payload in enumerate(payloads, start=1):
            sequence = expected_sequence + offset
            identity = f"{hand_id}|{command_id}|{offset}|{getattr(payload, 'kind')}"
            events.append(
                HandEventV1(
                    event_id=f"evt-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}",
                    hand_id=hand_id,
                    sequence=sequence,
                    timestamp=base_timestamp + timedelta(microseconds=offset - 1),
                    source=EventSourceV1.GAME_ORCHESTRATOR,
                    provenance=ContractProvenanceV1(
                        producer=self.producer,
                        producer_version=self.producer_version,
                        correlation_id=session_id,
                        causation_id=command_id,
                    ),
                    payload=payload,
                )
            )
        return tuple(events)


def _opening_scenario(session: GameSession) -> ScenarioSpec:
    active = session.active_hand
    assert active is not None
    seat_ids = tuple(seat.seat_id for seat in active.seats)
    if seat_ids != tuple(range(len(seat_ids))):
        raise SessionLifecycleError(
            "unsupported_active_topology",
            "HandEventV1 requires contiguous active seats in F1-03",
        )
    positions = positions_for_table(len(active.seats))
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": len(active.seats),
            "smallBlind": session.configuration.small_blind,
            "bigBlind": session.configuration.big_blind,
            "ante": session.configuration.ante,
            "buttonSeat": active.button_seat,
            "heroSeat": active.button_seat,
            "seats": [
                {
                    "seatId": seat.seat_id,
                    "startingStack": seat.starting_stack,
                    "position": positions[
                        (seat.seat_id - active.button_seat) % len(active.seats)
                    ].value,
                }
                for seat in active.seats
            ],
            "knownHoleCardsBySeat": {},
            "board": [],
            "actionHistory": [],
            "decisionPoint": {
                "street": "preflop",
                "actorSeat": active.button_seat,
                "afterSequence": 0,
            },
            "assumptions": {},
            "source": "imported",
            "tags": ["simulator-orchestrator-v1"],
        }
    )


__all__ = [
    "GameCommandResultV1",
    "GameCommandError",
    "GameOrchestrator",
    "OpenHandCommandV1",
    "PlayerActionCommandV1",
]
