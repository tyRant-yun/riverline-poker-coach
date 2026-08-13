"""Terminal, event-backed automatic review projections.

This module is intentionally a read-model boundary. It neither changes the
authoritative hand stream nor reruns settlement; later API work can hydrate
the explicit unavailable references through its own permission-aware seams.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from pydantic import ConfigDict, Field

from poker_coach.domain.models import DomainModel

from .contracts import (
    ActionTakenPayloadV1,
    BoardDealtPayloadV1,
    HandCompletedPayloadV1,
    HandEventV1,
    HandStartedPayloadV1,
)
from .event_store import HandEventStore
from .recovery import ProjectionIdentityV1, ProjectionRunner
from .replay import EventStreamError, validate_hand_event_stream


class ReviewProjectionError(ValueError):
    """Stable failure for an invalid review source stream or hero scope."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ReviewReferenceV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["available", "unavailable"]
    reference_id: str | None = None
    unavailable_reason: str | None = None


class ReviewReferencesV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    hand_lab: ReviewReferenceV1
    stats: ReviewReferenceV1
    formula: ReviewReferenceV1
    belief: ReviewReferenceV1


class HeroDecisionNodeV1(DomainModel):
    """A hero action with only facts visible strictly before that action."""

    model_config = ConfigDict(frozen=True)
    action_event_id: str = Field(min_length=1, max_length=128)
    action_sequence: int = Field(ge=1)
    street: str
    action: str
    visible_prefix_event_ids: tuple[str, ...]
    visible_board: tuple[str, ...]
    visible_action_count: int = Field(ge=0)


class AutomaticReviewV1(DomainModel):
    """Versioned review record generated only by a terminal HandCompleted event."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1
    session_id: str = Field(min_length=1, max_length=128)
    hand_id: str = Field(min_length=1, max_length=128)
    hero_seat: int = Field(ge=0, le=7)
    completion_event_id: str = Field(min_length=1, max_length=128)
    completion_sequence: int = Field(ge=1)
    hero_decisions: tuple[HeroDecisionNodeV1, ...]
    references: ReviewReferencesV1
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def project_automatic_review(
    events: Sequence[HandEventV1], *, session_id: str, hero_seat: int
) -> AutomaticReviewV1 | None:
    """Return a review only for a validated terminal stream.

    A non-terminal hand deliberately produces no record. Every node derives
    its public prefix from events before its hero action, so completion facts
    and later actions cannot leak into the node's evidence.
    """

    try:
        stream = validate_hand_event_stream(events)
    except EventStreamError as exc:
        raise ReviewProjectionError("invalid_event_stream", str(exc)) from exc
    completed = stream[-1].payload
    if not isinstance(completed, HandCompletedPayloadV1):
        return None
    started = stream[0].payload
    assert isinstance(started, HandStartedPayloadV1)
    if hero_seat not in started.active_seat_ids:
        raise ReviewProjectionError("invalid_hero_seat", "hero_seat must be a hand participant")

    decision_nodes: list[HeroDecisionNodeV1] = []
    for index, event in enumerate(stream):
        payload = event.payload
        if not isinstance(payload, ActionTakenPayloadV1) or payload.actor_seat != hero_seat:
            continue
        prefix = stream[:index]
        decision_nodes.append(
            HeroDecisionNodeV1(
                action_event_id=event.event_id,
                action_sequence=event.sequence,
                street=payload.street.value,
                action=payload.action.value,
                visible_prefix_event_ids=tuple(item.event_id for item in prefix),
                visible_board=tuple(
                    card
                    for item in prefix
                    if isinstance(item.payload, BoardDealtPayloadV1)
                    for card in item.payload.cards
                ),
                visible_action_count=sum(
                    isinstance(item.payload, ActionTakenPayloadV1) for item in prefix
                ),
            )
        )

    unavailable = ReviewReferenceV1(
        status="unavailable", unavailable_reason="not_materialized_by_review_projection"
    )
    references = ReviewReferencesV1(
        hand_lab=unavailable,
        stats=unavailable,
        formula=unavailable,
        belief=unavailable,
    )
    canonical = {
        "schemaVersion": 1,
        "sessionId": session_id,
        "handId": stream[0].hand_id,
        "heroSeat": hero_seat,
        "completionEventId": stream[-1].event_id,
        "completionSequence": stream[-1].sequence,
        "heroDecisions": [node.model_dump(by_alias=True, mode="json") for node in decision_nodes],
        "references": references.model_dump(by_alias=True, mode="json"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return AutomaticReviewV1(
        session_id=session_id,
        hand_id=stream[0].hand_id,
        hero_seat=hero_seat,
        completion_event_id=stream[-1].event_id,
        completion_sequence=stream[-1].sequence,
        hero_decisions=tuple(decision_nodes),
        references=references,
        fingerprint=fingerprint,
    )


class AutomaticReviewProjectionService:
    """Idempotently persists terminal review records from durable hand streams."""

    def __init__(self, event_store: HandEventStore, review_store: object):
        self._event_store = event_store
        self._review_store = review_store

    def apply_hand(
        self, *, session_id: str, hand_id: str, hero_seat: int
    ) -> AutomaticReviewV1 | None:
        events = tuple(raw.event for raw in self._event_store.read(hand_id))
        review = project_automatic_review(
            events, session_id=session_id, hero_seat=hero_seat
        )
        if review is None:
            return None
        ProjectionRunner(
            self._event_store,
            self._review_store.hand_projection_store,
            ProjectionIdentityV1(
                projection_name="automatic_review_hand_cursor", projection_version=1
            ),
            _cursor_projector,
        ).run(hand_id)
        return self._review_store.apply(review)


def _cursor_projector(
    snapshot: dict[str, object] | None, event: HandEventV1
) -> dict[str, object]:
    return {"eventIds": [*((snapshot or {}).get("eventIds", [])), event.event_id]}
