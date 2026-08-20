"""Public-event, independent-marginal Range Belief consumer.

Only public HandEvent V1 payloads are accepted.  The caller supplies the
observer-visible hole cards as blockers; private-card events, RNG, deck state,
and future stream events are deliberately outside this seam.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from threading import Lock

from pydantic import Field, model_validator

from poker_coach.domain.models import Card, DomainModel, Street
from poker_coach.simulator.contracts import (
    ActionTakenPayloadV1, AmountSemanticsV1, BoardDealtPayloadV1, HandEventV1,
    HandStartedPayloadV1, HoleCardsRecordedPayloadV1, SimulatorActionV1,
)

from .belief import RangeBeliefCombo, RangeBeliefSnapshot, RangeUpdateMetadata, combo_overlaps, snapshot_id_for
from .likelihood import PublicActionContext, change_reason, likelihood, size_bucket, spr_bucket
from .seat_priors import SeatPriorQueryV1, SeatPriorResultV1, SeatPriorUnavailableReason, default_seat_prior_provider

_VERSION = "heuristic_likelihood_v2"
_FINGERPRINT = sha256(b"riverline/public-event-belief/heuristic_likelihood_v2/public-size-street-position-spr-hand-features").hexdigest()
_BLOCKER_CACHE_MAX = 48
_BLOCKER_CACHE: OrderedDict[
    tuple[int, tuple[Card, ...], int, Street],
    tuple[RangeBeliefSnapshot, RangeBeliefSnapshot],
] = OrderedDict()
_BLOCKER_CACHE_LOCK = Lock()


class SeatBeliefUnavailableReason(str, Enum):
    EMPTY_STREAM = "empty_stream"
    INVALID_STREAM = "invalid_stream"
    PRIVATE_EVENT_FORBIDDEN = "private_event_forbidden"
    PRIOR_UNAVAILABLE = "prior_unavailable"
    OFF_TREE_UNSUPPORTED = "off_tree_unsupported"


class SeatBeliefProvenanceV1(DomainModel):
    provider: str = "riverline.heuristic_likelihood"
    version: str = _VERSION
    artifact_fingerprint: str = _FINGERPRINT
    trust_level: str = "heuristic"
    confidence: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    independent_marginal_only: bool = True


class SeatBeliefResultV1(DomainModel):
    seat_id: int
    after_sequence: int
    available: bool
    prior: RangeBeliefSnapshot | None = None
    current: RangeBeliefSnapshot | None = None
    provenance: SeatBeliefProvenanceV1 | None = None
    inactive: bool = False
    approximate: bool = False
    approximation_reason: str | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "SeatBeliefResultV1":
        if self.available != (self.prior is not None and self.current is not None and self.provenance is not None):
            raise ValueError("available result requires prior, current, and provenance")
        if self.available == (self.unavailable_reason is not None):
            raise ValueError("unavailable reason must appear exactly on unavailable results")
        return self


class PublicEventBeliefConsumer:
    """Replay a bounded public prefix into per-seat independent beliefs."""

    def beliefs_at(
        self, events: tuple[HandEventV1, ...], *, observer_visible_cards: tuple[Card, ...] = (), after_sequence: int | None = None,
    ) -> dict[int, SeatBeliefResultV1]:
        if not events or not isinstance(events[0].payload, HandStartedPayloadV1):
            return {}
        target = events[-1].sequence if after_sequence is None else after_sequence
        prefix = tuple(event for event in events if event.sequence <= target)
        if not prefix or prefix[0].sequence != 1 or any(event.sequence != index + 1 for index, event in enumerate(prefix)):
            return _unavailable_all(events[0].payload, target, SeatBeliefUnavailableReason.INVALID_STREAM)
        if any(isinstance(event.payload, HoleCardsRecordedPayloadV1) for event in prefix):
            return _unavailable_all(events[0].payload, target, SeatBeliefUnavailableReason.PRIVATE_EVENT_FORBIDDEN)
        started = prefix[0].payload
        assert isinstance(started, HandStartedPayloadV1)
        public_cards = tuple(card for event in prefix if isinstance(event.payload, BoardDealtPayloadV1) for card in event.payload.cards)
        query = SeatPriorQueryV1(table_size=started.table_size, active_seat_ids=started.active_seat_ids,
            button_seat=started.button_seat, small_blind=started.small_blind, big_blind=started.big_blind,
            starting_stacks={seat: started.starting_stacks[seat] for seat in started.active_seat_ids},
            ante=started.ante, rake_bps=started.rake_bps, visible_blockers=(*observer_visible_cards, *public_cards))
        provider = default_seat_prior_provider()
        # Seed before replaying public boards.  Coverage depends on public table
        # facts, not on blockers, so this avoids constructing a discarded second
        # 1326-combo prior on every decision.
        initial_query = query.model_copy(update={"visible_blockers": observer_visible_cards})
        priors: dict[int, SeatPriorResultV1] = {seat: provider.get_prior(initial_query, seat) for seat in started.active_seat_ids}
        if any(not result.available for result in priors.values()):
            return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=False,
                unavailable_reason=f"{SeatBeliefUnavailableReason.PRIOR_UNAVAILABLE.value}:{priors[seat].unavailable_reason.value}") for seat in priors}
        initial_priors = priors
        snapshots = {seat: result.snapshot for seat, result in initial_priors.items()}
        assert all(snapshots.values())
        prior_snapshots = dict(snapshots)
        inactive_seats: set[int] = set()
        board: list[Card] = []
        street_contributions = {seat: 0 for seat in started.active_seat_ids}
        stacks = dict(started.starting_stacks)
        pot = started.ante * len(started.active_seat_ids)
        for seat, prior in priors.items():
            forced = started.ante
            if prior.position is not None and prior.position.value == "small_blind":
                forced += started.small_blind
                street_contributions[seat] = started.small_blind
            elif prior.position is not None and prior.position.value == "big_blind":
                forced += started.big_blind
                street_contributions[seat] = started.big_blind
            stacks[seat] = max(0, stacks[seat] - forced)
            pot += forced - started.ante
        for event in prefix[1:]:
            payload = event.payload
            if isinstance(payload, BoardDealtPayloadV1):
                board.extend(payload.cards)
                street_contributions = {seat: 0 for seat in started.active_seat_ids}
                snapshots = {seat: _apply_blockers(snapshot, payload.cards, event.sequence, payload.street) for seat, snapshot in snapshots.items()}
            elif isinstance(payload, ActionTakenPayloadV1):
                if payload.action not in {SimulatorActionV1.FOLD, SimulatorActionV1.CALL, SimulatorActionV1.RAISE, SimulatorActionV1.CHECK, SimulatorActionV1.BET}:
                    return _unavailable_all(started, target, SeatBeliefUnavailableReason.OFF_TREE_UNSUPPORTED)
                position = priors[payload.actor_seat].position
                context = PublicActionContext(
                    board=tuple(board), pot_before=pot,
                    stack_before=stacks[payload.actor_seat],
                    position=position.value.lower() if position is not None else "unknown",
                )
                if payload.action is SimulatorActionV1.FOLD:
                    inactive_seats.add(payload.actor_seat)
                    snapshots[payload.actor_seat] = _mark_inactive(
                        snapshots[payload.actor_seat], payload, event.sequence, context
                    )
                else:
                    snapshots[payload.actor_seat] = _apply_action(
                        snapshots[payload.actor_seat], payload, event.sequence, context
                    )
                pot = _advance_public_state(payload, pot, stacks, street_contributions)
        return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=True, prior=prior_snapshots[seat],
            current=snapshots[seat], provenance=SeatBeliefProvenanceV1(), inactive=seat in inactive_seats,
            approximate=True, approximation_reason=priors[seat].coverage.approximation_reason or "bounded_public_likelihood_v2") for seat in snapshots}


def _apply_action(
    snapshot: RangeBeliefSnapshot,
    action: ActionTakenPayloadV1,
    sequence: int,
    context: PublicActionContext,
) -> RangeBeliefSnapshot:
    weighted = {
        key: combo.reach * likelihood(key, action.action, action.street, action.amount, context)
        for key, combo in snapshot.combos.items()
    }
    mass = sum(weighted.values(), Decimal("0"))
    combos = _normalized_combos(weighted, mass)
    reason = change_reason(action.action, action.street, action.amount, context)
    return RangeBeliefSnapshot.model_construct(snapshot_id=snapshot_id_for(snapshot.seat_id, action.street, sequence), seat_id=snapshot.seat_id,
        street=action.street, after_sequence=sequence, source=snapshot.source, confidence="heuristic",
        prior_mass=snapshot.retained_mass, retained_mass=mass, combos=combos, parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type=action.action.value, action_label=reason,
            observed_size=action.amount, mapped_size=action.amount, policy_source=snapshot.source,
            node=f"public-event/{reason}", policy_version=_VERSION,
            assumptions=(
                "bounded heuristic likelihood", "actor-only update",
                f"size_bucket:{size_bucket(action.action, action.amount, context.pot_before)}",
                f"street:{action.street.value}", f"position:{context.position}",
                f"spr_bucket:{spr_bucket(context.spr)}", "hand_features:made-hand/draw-aware",
                "not solver/GTO, player profile, or joint distribution",
            )))


def _mark_inactive(
    snapshot: RangeBeliefSnapshot,
    action: ActionTakenPayloadV1,
    sequence: int,
    context: PublicActionContext,
) -> RangeBeliefSnapshot:
    """A fold updates the final marginal and removes the seat from future action."""
    folded = _apply_action(snapshot, action, sequence, context)
    return folded.model_copy(
        update={
            "update": folded.update.model_copy(
                update={
                    "assumptions": (
                        *folded.update.assumptions,
                        "folded seat is inactive; final public-action belief remains replayable",
                    )
                }
            )
        }
    )


def _apply_blockers(snapshot: RangeBeliefSnapshot, cards: tuple[Card, ...], sequence: int, street: Street) -> RangeBeliefSnapshot:
    cache_key = (id(snapshot), cards, sequence, street)
    with _BLOCKER_CACHE_LOCK:
        cached = _BLOCKER_CACHE.get(cache_key)
        if cached is not None and cached[0] is snapshot:
            _BLOCKER_CACHE.move_to_end(cache_key)
            return cached[1]
    kept = {key: combo for key, combo in snapshot.combos.items() if not combo_overlaps(key, set(cards))}
    mass = sum((combo.reach for combo in kept.values()), Decimal("0"))
    combos = _normalized_combos({key: combo.reach for key, combo in kept.items()}, mass)
    result = RangeBeliefSnapshot.model_construct(snapshot_id=snapshot_id_for(snapshot.seat_id, street, sequence), seat_id=snapshot.seat_id,
        street=street, after_sequence=sequence, source=snapshot.source, confidence=snapshot.confidence,
        prior_mass=snapshot.retained_mass, retained_mass=mass, combos=combos, parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type="public_board", policy_source=snapshot.source, node="public-event/board", policy_version=_VERSION))
    with _BLOCKER_CACHE_LOCK:
        _BLOCKER_CACHE[cache_key] = (snapshot, result)
        _BLOCKER_CACHE.move_to_end(cache_key)
        while len(_BLOCKER_CACHE) > _BLOCKER_CACHE_MAX:
            _BLOCKER_CACHE.popitem(last=False)
    return result


def _normalized_combos(weights: dict[str, Decimal], mass: Decimal) -> dict[str, RangeBeliefCombo]:
    keys = tuple(sorted(weights))
    probabilities = {key: weights[key] / mass for key in keys[:-1]}
    probabilities[keys[-1]] = Decimal("1") - sum(probabilities.values(), Decimal("0"))
    return {
        key: RangeBeliefCombo.model_construct(
            combo=key, reach=weights[key], probability=probabilities[key]
        )
        for key in keys
    }


def _advance_public_state(
    action: ActionTakenPayloadV1,
    pot: int,
    stacks: dict[int, int],
    street_contributions: dict[int, int],
) -> int:
    amount = action.amount or 0
    if action.amount_semantics is AmountSemanticsV1.TO:
        contribution = max(0, amount - street_contributions[action.actor_seat])
    elif action.amount_semantics in {AmountSemanticsV1.BY, AmountSemanticsV1.COST}:
        contribution = amount
    else:
        contribution = 0
    contribution = min(contribution, stacks[action.actor_seat])
    stacks[action.actor_seat] -= contribution
    street_contributions[action.actor_seat] += contribution
    return pot + contribution


def _unavailable_all(started: object, target: int, reason: SeatBeliefUnavailableReason) -> dict[int, SeatBeliefResultV1]:
    seats = started.active_seat_ids if isinstance(started, HandStartedPayloadV1) else ()
    return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=False, unavailable_reason=reason.value) for seat in seats}
