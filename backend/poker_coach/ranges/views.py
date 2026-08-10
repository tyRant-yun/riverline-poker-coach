"""API-facing belief view: prior / current / delta for a seat.

Built from a ``RangeBeliefTrace``; the 169 matrix is derived from the
combo-level state. ``available=False`` means no grounded policy could
produce a current belief — the view never fabricates numbers.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from poker_coach.domain.models import DomainModel, SeatNumber, Street

from .aggregation import RangeBeliefMatrixCell, aggregate_belief_to_matrix169
from .belief import (
    PolicySource,
    RangeBeliefSnapshot,
    RangeUpdateMetadata,
)
from .trace import RangeBeliefTrace


class RangeBeliefComboView(DomainModel):
    """Per-combo prior/current/delta numbers (combo-level view)."""

    reach: Decimal = Field(ge=0, le=1)
    probability: Decimal = Field(ge=0, le=1)
    prior_probability: Decimal = Field(ge=0, le=1)
    delta: Decimal
    multiplier: Decimal | None = None


class RangeBeliefView(DomainModel):
    """Current belief with prior/current/delta and the derived 169 matrix."""

    seat_id: SeatNumber
    street: Street | None = None
    after_sequence: int = Field(ge=0)
    available: bool = False
    unavailable_reason: str | None = None
    source: PolicySource | None = None
    confidence: str | None = None
    prior_mass: Decimal | None = Field(default=None, ge=0)
    retained_mass: Decimal | None = Field(default=None, ge=0)
    retained_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    combos: dict[str, RangeBeliefComboView] | None = None
    matrix169: dict[str, RangeBeliefMatrixCell] | None = None
    update: RangeUpdateMetadata | None = None


def build_belief_view(trace: RangeBeliefTrace) -> RangeBeliefView:
    """Project a trace onto the wire view (prior/current/delta)."""
    prior = trace.prior
    current = trace.current
    if prior is None or current is None:
        return RangeBeliefView(
            seat_id=trace.seat_id,
            after_sequence=0,
            available=False,
            unavailable_reason="no_prior_range: no prior range is available for this seat",
        )
    matrix = aggregate_belief_to_matrix169(current, prior=prior)
    combos = {
        combo_key: RangeBeliefComboView(
            reach=combo.reach,
            probability=combo.probability,
            prior_probability=(
                prior.combos[combo_key].probability
                if combo_key in prior.combos
                else Decimal("0")
            ),
            delta=combo.probability
            - (
                prior.combos[combo_key].probability
                if combo_key in prior.combos
                else Decimal("0")
            ),
            multiplier=(
                combo.probability / prior.combos[combo_key].probability
                if combo_key in prior.combos and prior.combos[combo_key].probability > 0
                else None
            ),
        )
        for combo_key, combo in current.combos.items()
    }
    return RangeBeliefView(
        seat_id=trace.seat_id,
        street=current.street,
        after_sequence=current.after_sequence,
        available=trace.available,
        unavailable_reason=trace.unavailable_reason,
        source=current.source,
        confidence=current.confidence,
        prior_mass=current.prior_mass,
        retained_mass=current.retained_mass,
        retained_fraction=current.retained_fraction,
        combos=combos,
        matrix169=matrix,
        update=current.update,
    )
