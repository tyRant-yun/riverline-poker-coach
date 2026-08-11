"""Combo-level range belief domain models.

The inference state is always concrete two-card combos (``AsKs``, ``AhKh``,
...). The 169 matrix is never the engine's underlying state: it is a
derived view (see ``ranges/aggregation.py``).

Key invariant: reach weights and conditional probabilities are distinct
concepts. ``reach`` is the relative mass a combo carries along the observed
action sequence; ``probability`` is the normalized belief (sum ≈ 1) given
the player has reached the current node.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import Field, StrictInt, model_validator

from poker_coach.analysis.cards import RANK_VALUE, SUITS
from poker_coach.domain.models import Card, DomainModel, SeatNumber, Street

# Reach and probability live in [0, 1] but intentionally do NOT reuse the
# domain ``Weight`` type: Weight rejects floats and caps at 8 decimals, while
# solver-derived likelihoods are floats with up to ~11 significant digits.
ReachWeight = Annotated[Decimal, Field(ge=0, le=1)]
Probability = Annotated[Decimal, Field(ge=0, le=1)]

_PROBABILITY_TOLERANCE = Decimal("0.0000000001")


def combo_key(cards: tuple[Card, Card]) -> str:
    """Canonical combo key: high rank first, then descending suit order.

    Mirrors the solver sidecar's combo spelling (``5c4c``, ``2d2c``,
    ``Ac4c``) so solver node keys match prior expansion keys directly.
    """
    first, second = sorted(
        cards,
        key=lambda card: (RANK_VALUE[card[0]], SUITS.index(card[1])),
        reverse=True,
    )
    return f"{first}{second}"


def cards_from_key(combo: str) -> tuple[Card, Card]:
    return combo[:2], combo[2:]  # type: ignore[return-value]


def combo_overlaps(combo: str, dead_cards: set[Card]) -> bool:
    return bool(dead_cards.intersection(cards_from_key(combo)))


class PolicySource(str, Enum):
    """Where a range update's action frequencies come from.

    ``solver`` and ``fixture`` are implemented in this stage; the remaining
    values are reserved for later stages (V2 preflop dataset, population
    models, player-specific models).
    """

    SOLVER = "solver"
    FIXTURE = "fixture"
    PREFLOP_POLICY = "preflop_policy"
    POPULATION = "population"
    HEURISTIC = "heuristic"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class RangeBeliefError(ValueError):
    """Base error for range-belief operations; carries a stable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class NoPriorRangeError(RangeBeliefError):
    def __init__(self, message: str = "no prior range is available for this seat"):
        super().__init__("no_prior_range", message)


class NoPolicyError(RangeBeliefError):
    def __init__(self, message: str = "no grounded action policy is available for this node"):
        super().__init__("no_policy", message)


class PolicySequenceMismatchError(RangeBeliefError):
    def __init__(self, message: str):
        super().__init__("policy_sequence_mismatch", message)


class UnsupportedActionError(RangeBeliefError):
    def __init__(self, message: str):
        super().__init__("unsupported_action", message)


class ZeroProbabilityActionError(RangeBeliefError):
    def __init__(self, message: str):
        super().__init__("zero_probability_action", message)


class InvalidPolicyError(RangeBeliefError):
    def __init__(self, message: str):
        super().__init__("invalid_policy", message)


class RangeBeliefCombo(DomainModel):
    """Reach weight and conditional probability of one concrete combo."""

    combo: str = Field(min_length=4, max_length=4)
    reach: ReachWeight
    probability: Probability


class RangeUpdateMetadata(DomainModel):
    """What transition produced a snapshot (action, deal, or prior)."""

    action_type: str
    action_label: str | None = None
    observed_size: Annotated[Decimal, Field(ge=0)] | None = None
    mapped_size: Annotated[Decimal, Field(ge=0)] | None = None
    off_tree: bool = False
    policy_source: PolicySource | None = None
    node: str | None = None


class RangeBeliefSnapshot(DomainModel):
    """Belief state at one point of the action sequence for one seat.

    ``prior_mass`` is the reach mass entering this transition (after
    dead-card filtering); ``retained_mass`` is the mass surviving it. The
    ratio retained/prior is the share of prior reach the node keeps.
    """

    snapshot_id: str = Field(min_length=1, max_length=128)
    seat_id: SeatNumber
    street: Street
    after_sequence: Annotated[StrictInt, Field(ge=0)]
    source: PolicySource
    confidence: str = "grounded"
    prior_mass: Annotated[Decimal, Field(ge=0)]
    retained_mass: Annotated[Decimal, Field(ge=0)]
    combos: dict[str, RangeBeliefCombo]
    parent_snapshot_id: str | None = None
    update: RangeUpdateMetadata | None = None

    @model_validator(mode="after")
    def validate_probabilities_sum(self) -> RangeBeliefSnapshot:
        total = sum((combo.probability for combo in self.combos.values()), Decimal("0"))
        if abs(total - Decimal("1")) > _PROBABILITY_TOLERANCE:
            raise ValueError(f"combo probabilities must sum to one; got {total}")
        return self

    @property
    def retained_fraction(self) -> Decimal:
        """Share of prior reach retained at this node (None-safe for zero)."""
        if self.prior_mass == 0:
            return Decimal("0")
        return self.retained_mass / self.prior_mass


def snapshot_id_for(seat_id: int, street: Street | str, after_sequence: int) -> str:
    street_value = street.value if isinstance(street, Street) else street
    return f"seat{seat_id}-seq{after_sequence}-{street_value}"
