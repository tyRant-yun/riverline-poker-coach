"""Public-event, independent-marginal Range Belief consumer.

Only public HandEvent V1 payloads are accepted.  The caller supplies the
observer-visible hole cards as blockers; private-card events, RNG, deck state,
and future stream events are deliberately outside this seam.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from hashlib import sha256

from pydantic import Field, model_validator

from poker_coach.domain.models import Card, DomainModel, Street
from poker_coach.simulator.contracts import (
    ActionTakenPayloadV1, BoardDealtPayloadV1, HandEventV1, HandStartedPayloadV1,
    HoleCardsRecordedPayloadV1, SimulatorActionV1,
)

from .belief import RangeBeliefCombo, RangeBeliefSnapshot, RangeUpdateMetadata, combo_overlaps, snapshot_id_for
from .seat_priors import SeatPriorQueryV1, SeatPriorResultV1, SeatPriorUnavailableReason, default_seat_prior_provider

_VERSION = "heuristic_likelihood_v1"
_FINGERPRINT = sha256(b"riverline/public-event-belief/heuristic_likelihood_v1/preflop-action-category").hexdigest()


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
        for event in prefix[1:]:
            payload = event.payload
            if isinstance(payload, BoardDealtPayloadV1):
                snapshots = {seat: _apply_blockers(snapshot, payload.cards, event.sequence, payload.street) for seat, snapshot in snapshots.items()}
            elif isinstance(payload, ActionTakenPayloadV1):
                if payload.action not in {SimulatorActionV1.FOLD, SimulatorActionV1.CALL, SimulatorActionV1.RAISE, SimulatorActionV1.CHECK, SimulatorActionV1.BET}:
                    return _unavailable_all(started, target, SeatBeliefUnavailableReason.OFF_TREE_UNSUPPORTED)
                if payload.action is SimulatorActionV1.FOLD:
                    inactive_seats.add(payload.actor_seat)
                    snapshots[payload.actor_seat] = _mark_inactive(snapshots[payload.actor_seat], payload, event.sequence)
                else:
                    snapshots[payload.actor_seat] = _apply_action(snapshots[payload.actor_seat], payload, event.sequence, priors[payload.actor_seat].position)
        return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=True, prior=prior_snapshots[seat],
            current=snapshots[seat], provenance=SeatBeliefProvenanceV1(), inactive=seat in inactive_seats,
            approximate=priors[seat].coverage.approximate, approximation_reason=priors[seat].coverage.approximation_reason) for seat in snapshots}


def _apply_action(snapshot: RangeBeliefSnapshot, action: ActionTakenPayloadV1, sequence: int, position: object) -> RangeBeliefSnapshot:
    weighted = {key: combo.reach * _likelihood(key, action.action, action.amount, action.street, position) for key, combo in snapshot.combos.items()}
    mass = sum(weighted.values(), Decimal("0"))
    combos = _normalized_combos(weighted, mass)
    return RangeBeliefSnapshot(snapshot_id=snapshot_id_for(snapshot.seat_id, action.street, sequence), seat_id=snapshot.seat_id,
        street=action.street, after_sequence=sequence, source=snapshot.source, confidence="heuristic",
        prior_mass=snapshot.retained_mass, retained_mass=mass, combos=combos, parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type=action.action.value, action_label="公开行动启发式更新", observed_size=action.amount, mapped_size=action.amount, policy_source=snapshot.source,
            node="public-event/preflop-or-public-street", policy_version=_VERSION,
            assumptions=("bounded heuristic likelihood", "actor-only update", "not solver/GTO or joint distribution")))


def _mark_inactive(snapshot: RangeBeliefSnapshot, action: ActionTakenPayloadV1, sequence: int) -> RangeBeliefSnapshot:
    """Folding removes the seat from action, not from its historical belief."""
    return RangeBeliefSnapshot(
        snapshot_id=snapshot_id_for(snapshot.seat_id, action.street, sequence), seat_id=snapshot.seat_id,
        street=action.street, after_sequence=sequence, source=snapshot.source, confidence=snapshot.confidence,
        prior_mass=snapshot.retained_mass, retained_mass=snapshot.retained_mass, combos=snapshot.combos,
        parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type=action.action.value, action_label="公开行动：弃牌（座位已停用）",
            policy_source=snapshot.source, node="public-event/fold", policy_version=_VERSION,
            assumptions=("folded seats are inactive; historical belief is retained for replay only",)),
    )


def _apply_blockers(snapshot: RangeBeliefSnapshot, cards: tuple[Card, ...], sequence: int, street: Street) -> RangeBeliefSnapshot:
    kept = {key: combo for key, combo in snapshot.combos.items() if not combo_overlaps(key, set(cards))}
    mass = sum((combo.reach for combo in kept.values()), Decimal("0"))
    combos = _normalized_combos({key: combo.reach for key, combo in kept.items()}, mass)
    return RangeBeliefSnapshot(snapshot_id=snapshot_id_for(snapshot.seat_id, street, sequence), seat_id=snapshot.seat_id,
        street=street, after_sequence=sequence, source=snapshot.source, confidence=snapshot.confidence,
        prior_mass=snapshot.retained_mass, retained_mass=mass, combos=combos, parent_snapshot_id=snapshot.snapshot_id,
        update=RangeUpdateMetadata(action_type="public_board", policy_source=snapshot.source, node="public-event/board", policy_version=_VERSION))


def _likelihood(combo: str, action: SimulatorActionV1, amount: int | None, street: Street, position: object) -> Decimal:
    high = combo[0] in "AKQJ" or combo[2] in "AKQJ" or combo[0] == combo[2]
    size_tilt = Decimal("0.10") if amount is not None and amount >= 200 else Decimal("0")
    positional_tilt = Decimal("0.03") if str(position) in {"utg", "mp"} else Decimal("0")
    if action in {SimulatorActionV1.RAISE, SimulatorActionV1.BET}:
        return Decimal("0.80") + size_tilt + positional_tilt if high else Decimal("0.25") - size_tilt / 2
    if action is SimulatorActionV1.CALL:
        return Decimal("0.65") if high else Decimal("0.45") + (Decimal("0.03") if street is not Street.PREFLOP else Decimal("0"))
    if action is SimulatorActionV1.FOLD:
        return Decimal("0.20") if high else Decimal("0.80")
    return Decimal("1")


def _normalized_combos(weights: dict[str, Decimal], mass: Decimal) -> dict[str, RangeBeliefCombo]:
    keys = tuple(sorted(weights))
    probabilities = {key: weights[key] / mass for key in keys[:-1]}
    probabilities[keys[-1]] = Decimal("1") - sum(probabilities.values(), Decimal("0"))
    return {key: RangeBeliefCombo(combo=key, reach=weights[key], probability=probabilities[key]) for key in keys}


def _unavailable_all(started: object, target: int, reason: SeatBeliefUnavailableReason) -> dict[int, SeatBeliefResultV1]:
    seats = started.active_seat_ids if isinstance(started, HandStartedPayloadV1) else ()
    return {seat: SeatBeliefResultV1(seat_id=seat, after_sequence=target, available=False, unavailable_reason=reason.value) for seat in seats}
