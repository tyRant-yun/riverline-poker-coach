"""Six-max unopened seat priors with explicit coverage and provenance.

This is an independent-marginal seed, not a joint distribution of opponents'
cards.  It consumes only caller-supplied visible blockers; it never reads a
deck, RNG seed, future board, or any other seat's private cards.
"""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from itertools import combinations
from decimal import Decimal

from pydantic import Field, model_validator

from poker_coach.analysis.cards import deck
from poker_coach.domain.models import Card, DomainModel, SeatPosition, Street, positions_for_table

from .belief import PolicySource, RangeBeliefCombo, RangeBeliefSnapshot, RangeUpdateMetadata, combo_key, snapshot_id_for


_VERSION = "heuristic_seed_v1"
_PROVIDER = "riverline.heuristic_seed"
_FINGERPRINT = sha256(b"riverline/seat-prior/heuristic_seed_v1/uniform-independent-marginal").hexdigest()
_STACK_LOW_BB = Decimal("80")
_STACK_HIGH_BB = Decimal("120")


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
        combos = _uniform_combos(query.visible_blockers)
        total = Decimal(len(combos))
        probabilities = _normalized_uniform_probabilities(combos)
        snapshot = RangeBeliefSnapshot(
            snapshot_id=snapshot_id_for(seat_id, Street.PREFLOP, 0), seat_id=seat_id,
            street=Street.PREFLOP, after_sequence=0, source=PolicySource.HEURISTIC,
            confidence="heuristic", prior_mass=total, retained_mass=total,
            combos={key: RangeBeliefCombo(combo=key, reach=Decimal("1"), probability=probabilities[key]) for key in combos},
            update=RangeUpdateMetadata(action_type="prior", action_label="unopened", node=coverage.node,
                policy_source=PolicySource.HEURISTIC, policy_version=_VERSION,
                assumptions=("6-max NLHE cash", "80-120BB effective", "no ante / no rake", "unopened preflop", "independent marginal; not a joint opponent distribution")),
        )
        return SeatPriorResultV1(
            seat_id=seat_id, position=position, available=True, coverage=coverage, snapshot=snapshot,
            provenance=SeatPriorProvenanceV1(provider=_PROVIDER, version=_VERSION,
                artifact_fingerprint=_FINGERPRINT, trust_level="heuristic", confidence=Decimal("0.25"),
                source_description="First-party uniform independent-marginal heuristic seed; not solver, GTO, or verified strategy data."),
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
    return SeatPriorCoverageV1(table_size=len(query.active_seat_ids), effective_stack_bucket="80-120bb",
        ante_signature=f"ante:{query.ante}", rake_signature=f"rake_bps:{query.rake_bps}",
        street=query.street, node="preflop/unopened")


def _unavailable_reason(query: SeatPriorQueryV1, seat_id: int) -> SeatPriorUnavailableReason | None:
    if seat_id not in query.active_seat_ids:
        return SeatPriorUnavailableReason.SEAT_NOT_ACTIVE
    if query.table_size != 6 or len(query.active_seat_ids) != 6:
        return SeatPriorUnavailableReason.TABLE_SIZE_UNSUPPORTED
    if query.ante:
        return SeatPriorUnavailableReason.ANTE_UNSUPPORTED
    if query.rake_bps:
        return SeatPriorUnavailableReason.RAKE_UNSUPPORTED
    if any(not (_STACK_LOW_BB <= Decimal(stack) / query.big_blind <= _STACK_HIGH_BB) for stack in query.starting_stacks.values()):
        return SeatPriorUnavailableReason.STACK_BUCKET_UNSUPPORTED
    if query.street is not Street.PREFLOP or query.after_sequence != 0:
        return SeatPriorUnavailableReason.NODE_UNSUPPORTED
    return None


def _uniform_combos(visible_blockers: tuple[Card, ...]) -> tuple[str, ...]:
    return tuple(sorted(combo_key(cards) for cards in combinations(deck(visible_blockers), 2)))


def _normalized_uniform_probabilities(combos: tuple[str, ...]) -> dict[str, Decimal]:
    """Produce deterministic uniform weights whose Decimal sum is exactly one."""
    base = Decimal("1") / Decimal(len(combos))
    probabilities = {combo: base for combo in combos[:-1]}
    probabilities[combos[-1]] = Decimal("1") - sum(probabilities.values(), Decimal("0"))
    return probabilities
