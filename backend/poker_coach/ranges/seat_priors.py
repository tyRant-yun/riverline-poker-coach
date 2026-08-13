"""Six-max unopened seat priors with explicit coverage and provenance.

This is an independent-marginal seed, not a joint distribution of opponents'
cards.  It consumes only caller-supplied visible blockers; it never reads a
deck, RNG seed, future board, or any other seat's private cards.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
from decimal import Decimal

from pydantic import Field, model_validator

from poker_coach.analysis.cards import RANK_VALUE, deck
from poker_coach.domain.models import Card, DomainModel, SeatPosition, Street, positions_for_table

from .belief import PolicySource, RangeBeliefCombo, RangeBeliefSnapshot, RangeUpdateMetadata, combo_key, snapshot_id_for


_VERSION = "heuristic_seed_v2"
_PROVIDER = "riverline.position_stack_heuristic"
_FINGERPRINT = sha256(b"riverline/seat-prior/heuristic_seed_v2/position-stack-independent-marginal").hexdigest()
_STACK_BUCKETS = (Decimal("20"), Decimal("40"), Decimal("60"), Decimal("80"), Decimal("100"), Decimal("150"), Decimal("200"))


class SeatPriorUnavailableReason(str, Enum):
    TABLE_SIZE_UNSUPPORTED = "table_size_unsupported"
    ANTE_UNSUPPORTED = "ante_unsupported"
    RAKE_UNSUPPORTED = "rake_unsupported"
    STACK_BUCKET_UNSUPPORTED = "stack_bucket_unsupported"
    NODE_UNSUPPORTED = "node_unsupported"
    SEAT_NOT_ACTIVE = "seat_not_active"


class SeatPriorQueryV1(DomainModel):
    """Public facts needed to obtain one preflop unopened prior."""

    table_size: int = Field(ge=2, le=8)
    active_seat_ids: tuple[int, ...] = Field(min_length=2, max_length=8)
    button_seat: int = Field(ge=0, le=7)
    small_blind: int = Field(gt=0)
    big_blind: int = Field(gt=0)
    starting_stacks: dict[int, int]
    ante: int = Field(default=0, ge=0)
    rake_bps: int = Field(default=0, ge=0)
    street: Street = Street.PREFLOP
    after_sequence: int = Field(default=0, ge=0)
    visible_blockers: tuple[Card, ...] = ()

    @model_validator(mode="after")
    def validate_public_table_facts(self) -> "SeatPriorQueryV1":
        active = self.active_seat_ids
        if active != tuple(sorted(set(active))):
            raise ValueError("active_seat_ids must be unique and sorted stable table seat IDs")
        if self.button_seat not in active:
            raise ValueError("button_seat must be an active stable table seat")
        if set(self.starting_stacks) != set(active):
            raise ValueError("starting_stacks must contain exactly active stable table seats")
        if self.big_blind <= self.small_blind:
            raise ValueError("big_blind must exceed small_blind")
        if any(stack <= 0 for stack in self.starting_stacks.values()):
            raise ValueError("active stacks must be positive")
        if len(self.visible_blockers) != len(set(self.visible_blockers)):
            raise ValueError("visible_blockers must be unique")
        if any(card not in deck() for card in self.visible_blockers):
            raise ValueError("visible_blockers must be valid cards")
        return self


class SeatPriorCoverageV1(DomainModel):
    table_size: int
    effective_stack_bucket: str
    ante_signature: str
    rake_signature: str
    street: Street
    node: str
    approximate: bool = False
    approximation_reason: str | None = None
    independent_marginal_only: bool = True


class SeatPriorProvenanceV1(DomainModel):
    provider: str
    version: str
    artifact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_level: str
    confidence: Decimal = Field(ge=0, le=1)
    source_description: str


class SeatPriorResultV1(DomainModel):
    seat_id: int
    position: SeatPosition | None = None
    available: bool
    coverage: SeatPriorCoverageV1
    provenance: SeatPriorProvenanceV1 | None = None
    snapshot: RangeBeliefSnapshot | None = None
    unavailable_reason: SeatPriorUnavailableReason | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> "SeatPriorResultV1":
        if self.available != (self.snapshot is not None and self.provenance is not None):
            raise ValueError("available results require snapshot and provenance")
        if self.available == (self.unavailable_reason is not None):
            raise ValueError("unavailable_reason must appear exactly on unavailable results")
        return self


class SeatPriorProvider:
    """Minimal query seam for the later public-event belief consumer."""

    def get_prior(self, query: SeatPriorQueryV1, seat_id: int) -> SeatPriorResultV1:
        position = _position_for(query, seat_id)
        coverage = _coverage(query)
        unavailable = _unavailable_reason(query, seat_id)
        if unavailable is not None:
            return SeatPriorResultV1(
                seat_id=seat_id, position=position, available=False, coverage=coverage,
                unavailable_reason=unavailable,
            )
        snapshot = _cached_snapshot(seat_id, position, query.visible_blockers)
        return SeatPriorResultV1(
            seat_id=seat_id, position=position, available=True, coverage=coverage, snapshot=snapshot,
            provenance=SeatPriorProvenanceV1(provider=_PROVIDER, version=_VERSION,
                artifact_fingerprint=_FINGERPRINT, trust_level="heuristic", confidence=Decimal("0.25"),
                source_description="First-party position/stack independent-marginal heuristic seed; not solver, GTO, or verified strategy data."),
        )


def default_seat_prior_provider() -> SeatPriorProvider:
    return SeatPriorProvider()


def _position_for(query: SeatPriorQueryV1, seat_id: int) -> SeatPosition | None:
    if seat_id not in query.active_seat_ids:
        return None
    button_index = query.active_seat_ids.index(query.button_seat)
    seat_index = query.active_seat_ids.index(seat_id)
    return positions_for_table(len(query.active_seat_ids))[(seat_index - button_index) % len(query.active_seat_ids)]


def _coverage(query: SeatPriorQueryV1) -> SeatPriorCoverageV1:
    effective = min(Decimal(query.starting_stacks[seat]) / query.big_blind for seat in query.active_seat_ids)
    bucket = min(_STACK_BUCKETS, key=lambda candidate: (abs(candidate - effective), candidate))
    exact = effective == bucket
    return SeatPriorCoverageV1(table_size=len(query.active_seat_ids), effective_stack_bucket=f"{bucket}bb",
        ante_signature=f"ante:{query.ante}", rake_signature=f"rake_bps:{query.rake_bps}",
        street=query.street, node="preflop/unopened", approximate=not exact,
        approximation_reason=None if exact else f"nearest_stack_bucket:{bucket}bb")


def _unavailable_reason(query: SeatPriorQueryV1, seat_id: int) -> SeatPriorUnavailableReason | None:
    if seat_id not in query.active_seat_ids:
        return SeatPriorUnavailableReason.SEAT_NOT_ACTIVE
    if query.table_size != 6 or len(query.active_seat_ids) != 6:
        return SeatPriorUnavailableReason.TABLE_SIZE_UNSUPPORTED
    if query.ante:
        return SeatPriorUnavailableReason.ANTE_UNSUPPORTED
    if query.rake_bps:
        return SeatPriorUnavailableReason.RAKE_UNSUPPORTED
    if query.street is not Street.PREFLOP or query.after_sequence != 0:
        return SeatPriorUnavailableReason.NODE_UNSUPPORTED
    return None


def _position_weighted_combos(visible_blockers: tuple[Card, ...], position: SeatPosition | None) -> dict[str, Decimal]:
    """Deterministic first-party seed; all 1326 legal combos remain represented.

    Earlier positions modestly concentrate mass on stronger starts.  This is a
    disclosed usability heuristic, not a strategy chart or a GTO claim.
    """
    position_tilt = {
        SeatPosition.UTG: 2, SeatPosition.MP: 1, SeatPosition.HJ: 0,
        SeatPosition.CUTOFF: -1, SeatPosition.BUTTON: -2,
        SeatPosition.SMALL_BLIND: 1, SeatPosition.BIG_BLIND: 0,
    }.get(position, 0)
    result: dict[str, Decimal] = {}
    for cards in combinations(deck(visible_blockers), 2):
        key = combo_key(cards)
        first, second = cards
        score = RANK_VALUE[first[0]] + RANK_VALUE[second[0]]
        if first[0] == second[0]:
            score += 8
        elif first[1] == second[1]:
            score += 2
        # Values stay safely inside RangeBeliefCombo reach's [0, 1] contract.
        result[key] = Decimal(18 + score + position_tilt * (score - 14) / 5) / Decimal("50")
    return {key: max(Decimal("0.02"), min(Decimal("0.98"), weight)) for key, weight in result.items()}


@lru_cache(maxsize=128)
def _cached_snapshot(seat_id: int, position: SeatPosition | None, visible_blockers: tuple[Card, ...]) -> RangeBeliefSnapshot:
    """Reuse immutable seed snapshots across a hand's decision refreshes."""
    weights = _position_weighted_combos(visible_blockers, position)
    total = sum(weights.values(), Decimal("0"))
    probabilities = _normalized_probabilities(weights)
    return RangeBeliefSnapshot(
        snapshot_id=snapshot_id_for(seat_id, Street.PREFLOP, 0), seat_id=seat_id,
        street=Street.PREFLOP, after_sequence=0, source=PolicySource.HEURISTIC,
        confidence="heuristic", prior_mass=total, retained_mass=total,
        combos={key: RangeBeliefCombo(combo=key, reach=weights[key], probability=probabilities[key]) for key in weights},
        update=RangeUpdateMetadata(action_type="prior", action_label="unopened", node="preflop/unopened",
            policy_source=PolicySource.HEURISTIC, policy_version=_VERSION,
            assumptions=("6-max NLHE cash", "first-party position/stack heuristic", "no ante / no rake", "unopened preflop", "independent marginal; not a joint opponent distribution")),
    )


def _normalized_probabilities(weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """Produce deterministic probabilities whose Decimal sum is exactly one."""
    combos = tuple(sorted(weights))
    total = sum(weights.values(), Decimal("0"))
    probabilities = {combo: weights[combo] / total for combo in combos[:-1]}
    probabilities[combos[-1]] = Decimal("1") - sum(probabilities.values(), Decimal("0"))
    return probabilities
