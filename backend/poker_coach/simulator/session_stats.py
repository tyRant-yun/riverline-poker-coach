"""Disposable session/seat statistics derived from authoritative hand events."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from pydantic import ConfigDict, Field

from poker_coach.domain.models import DomainModel, Street

from .contracts import (
    ActionTakenPayloadV1,
    HandCompletedPayloadV1,
    HandEventV1,
    HandStartedPayloadV1,
    SimulatorActionV1,
)
from .event_store import HandEventStore
from .recovery import ProjectionIdentityV1, ProjectionRunner
from .replay import validate_hand_event_stream


class SeatStatsV1(DomainModel):
    """Aggregates for one stable table seat within a Game Session.

    ``hands_dealt`` counts only ``activeSeatIds`` participants. ``hands_played``
    counts hands in which the seat produced at least one recorded player action.
    VPIP/PFR opportunities are each dealt hand; 3-bet opportunities are the
    seat's first recorded preflop action after another seat's open raise.
    """

    model_config = ConfigDict(frozen=True)
    hands_dealt: int = Field(ge=0)
    hands_played: int = Field(ge=0)
    vpip_opportunities: int = Field(ge=0)
    vpip_actions: int = Field(ge=0)
    vpip_rate: float = Field(ge=0, le=1)
    pfr_opportunities: int = Field(ge=0)
    pfr_actions: int = Field(ge=0)
    pfr_rate: float = Field(ge=0, le=1)
    three_bet_opportunities: int = Field(ge=0)
    three_bet_actions: int = Field(ge=0)
    three_bet_rate: float = Field(ge=0, le=1)
    fold_count: int = Field(ge=0)
    check_count: int = Field(ge=0)
    call_count: int = Field(ge=0)
    bet_count: int = Field(ge=0)
    raise_count: int = Field(ge=0)
    won_hand_count: int = Field(ge=0)

    @classmethod
    def from_counts(cls, **counts: int) -> "SeatStatsV1":
        def rate(actions: int, opportunities: int) -> float:
            return 0.0 if opportunities == 0 else actions / opportunities

        return cls(
            **counts,
            vpip_rate=rate(counts["vpip_actions"], counts["vpip_opportunities"]),
            pfr_rate=rate(counts["pfr_actions"], counts["pfr_opportunities"]),
            three_bet_rate=rate(
                counts["three_bet_actions"], counts["three_bet_opportunities"]
            ),
        )


class SessionStatsV1(DomainModel):
    """Versioned, disposable read model for a session's stable table seats."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = Field(default=1, frozen=True)
    session_id: str = Field(min_length=1, max_length=128)
    by_seat: dict[int, SeatStatsV1]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


_COUNT_FIELDS = (
    "hands_dealt", "hands_played", "vpip_opportunities", "vpip_actions",
    "pfr_opportunities", "pfr_actions", "three_bet_opportunities",
    "three_bet_actions", "fold_count", "check_count", "call_count",
    "bet_count", "raise_count", "won_hand_count",
)


def empty_session_stats(session_id: str) -> SessionStatsV1:
    return _session_stats(session_id, {})


def _session_stats(session_id: str, counts_by_seat: dict[int, dict[str, int]]) -> SessionStatsV1:
    by_seat = {
        seat: SeatStatsV1.from_counts(**{field: counts[field] for field in _COUNT_FIELDS})
        for seat, counts in sorted(counts_by_seat.items())
    }
    payload = {"schemaVersion": 1, "sessionId": session_id, "bySeat": {str(seat): value.model_dump(by_alias=True, mode="json") for seat, value in by_seat.items()}}
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return SessionStatsV1(session_id=session_id, by_seat=by_seat, fingerprint=fingerprint)


def project_hand_stats(events: Sequence[HandEventV1], *, session_id: str) -> SessionStatsV1:
    """Build one hand's session-shaped contribution after V1 stream validation."""

    stream = validate_hand_event_stream(events)
    started = stream[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    counts: dict[int, dict[str, int]] = {
        seat: defaultdict(int) for seat in started.active_seat_ids
    }
    for seat in started.active_seat_ids:
        counts[seat]["hands_dealt"] = 1
        counts[seat]["vpip_opportunities"] = 1
        counts[seat]["pfr_opportunities"] = 1

    acted: set[int] = set()
    voluntary: set[int] = set()
    raised: set[int] = set()
    three_bet_opportunity: set[int] = set()
    three_bet: set[int] = set()
    open_raiser: int | None = None
    for event in stream:
        payload = event.payload
        if isinstance(payload, HandCompletedPayloadV1):
            for seat in payload.winner_seats:
                if seat in counts:
                    counts[seat]["won_hand_count"] += 1
            continue
        if not isinstance(payload, ActionTakenPayloadV1):
            continue
        if payload.actor_seat not in counts:
            raise ValueError("action references a non-participant seat")
        acted.add(payload.actor_seat)
        counts[payload.actor_seat][f"{payload.action.value}_count"] += 1
        if payload.street is not Street.PREFLOP:
            continue
        if payload.action in {SimulatorActionV1.CALL, SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
            voluntary.add(payload.actor_seat)
        if payload.action not in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
            continue
        if open_raiser is None:
            open_raiser = payload.actor_seat
            raised.add(payload.actor_seat)
        elif payload.actor_seat != open_raiser and payload.actor_seat not in three_bet:
            # The first re-raise facing the first open is the only 3-bet counted.
            three_bet.add(payload.actor_seat)
            raised.add(payload.actor_seat)
        else:
            raised.add(payload.actor_seat)
        if open_raiser is not None and payload.actor_seat != open_raiser:
            three_bet_opportunity.add(payload.actor_seat)
        # A first post-open non-raise action is also a 3-bet opportunity.
        # (The raise branch above records the same set entry idempotently.)
    if open_raiser is not None:
        seen_after_open: set[int] = set()
        for event in stream:
            payload = event.payload
            if not isinstance(payload, ActionTakenPayloadV1) or payload.street is not Street.PREFLOP:
                continue
            if payload.actor_seat == open_raiser:
                continue
            if payload.actor_seat in seen_after_open:
                continue
            # Only events after the opening raise create an opportunity.
            opener_event = next(
                item for item in stream
                if isinstance(item.payload, ActionTakenPayloadV1)
                and item.payload.street is Street.PREFLOP
                and item.payload.actor_seat == open_raiser
                and item.payload.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}
            )
            if event.sequence > opener_event.sequence:
                three_bet_opportunity.add(payload.actor_seat)
                seen_after_open.add(payload.actor_seat)
    for seat in acted:
        counts[seat]["hands_played"] = 1
    for seat in voluntary:
        counts[seat]["vpip_actions"] = 1
    for seat in raised:
        counts[seat]["pfr_actions"] = 1
    for seat in three_bet_opportunity:
        counts[seat]["three_bet_opportunities"] = 1
    for seat in three_bet:
        counts[seat]["three_bet_actions"] = 1
    return _session_stats(session_id, counts)


class SessionStatsProjectionService:
    """Incrementally applies validated hand contributions from the event-store seam."""

    def __init__(self, event_store: HandEventStore, stats_store: object):
        self._event_store = event_store
        self._stats_store = stats_store

    def apply_hand(self, *, session_id: str, hand_id: str) -> SessionStatsV1:
        # This per-hand cursor is deliberately separate from the aggregate's
        # hand-level idempotency key. It reuses the F1-04 transactional
        # snapshot/checkpoint seam for durable event consumption and restart.
        ProjectionRunner(
            self._event_store,
            self._stats_store.hand_projection_store,
            ProjectionIdentityV1(
                projection_name="session_stats_hand_cursor", projection_version=1
            ),
            _hand_cursor_projector,
        ).run(hand_id)
        events = tuple(raw.event for raw in self._event_store.read(hand_id))
        contribution = project_hand_stats(events, session_id=session_id)
        return self._stats_store.apply_hand(session_id, hand_id, contribution)

    def rebuild(self, *, session_id: str, hand_ids: Sequence[str]) -> SessionStatsV1:
        self._stats_store.discard(session_id)
        result = empty_session_stats(session_id)
        identity = ProjectionIdentityV1(
            projection_name="session_stats_hand_cursor", projection_version=1
        )
        for hand_id in hand_ids:
            self._stats_store.hand_projection_store.discard(identity, hand_id)
            result = self.apply_hand(session_id=session_id, hand_id=hand_id)
        return result


def _hand_cursor_projector(
    snapshot: dict[str, object] | None, event: HandEventV1
) -> dict[str, object]:
    """Minimal F1-04 projector payload: a cache of the consumed event IDs."""

    return {"eventIds": [*((snapshot or {}).get("eventIds", [])), event.event_id]}
