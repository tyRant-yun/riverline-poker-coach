"""Combo-level belief -> 169 matrix aggregation.

The matrix is a derived view only: each cell sums the probability mass of
every concrete combo in that starting-hand class. Cell probability mass is
the SUM of combo probabilities (never an average), so

    sum(matrix169 probabilityMass) == sum(combo probabilities) == ~1
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field

from poker_coach.analysis.cards import RANK_VALUE, SUITS
from poker_coach.domain.models import DomainModel

from .belief import RangeBeliefSnapshot


@lru_cache(maxsize=1326)
def cell_key(combo: str) -> str:
    """Map a concrete combo key to its 169 starting-hand cell.

    ``AsKs``/``AhKh`` -> ``AKs``; ``AsKd`` -> ``AKo``; ``AsAh`` -> ``AA``.
    """
    first, second = combo[:2], combo[2:]
    if first[0] == second[0]:
        return f"{first[0]}{second[0]}"
    high, low = sorted(
        (first, second),
        key=lambda card: (RANK_VALUE[card[0]], SUITS.index(card[1])),
        reverse=True,
    )
    return f"{high[0]}{low[0]}{'s' if high[1] == low[1] else 'o'}"


class RangeBeliefMatrixCell(DomainModel):
    """169-cell aggregation of a belief snapshot."""

    reach_mass: Decimal = Field(ge=0)
    probability_mass: Decimal = Field(ge=0, le=1)
    combo_count: int = Field(ge=0)
    prior_probability_mass: Decimal = Field(ge=0, le=1)
    delta: Decimal
    multiplier: Decimal | None = None


def aggregate_belief_to_matrix169(
    snapshot: RangeBeliefSnapshot,
    *,
    prior: RangeBeliefSnapshot | None = None,
) -> dict[str, RangeBeliefMatrixCell]:
    """Aggregate a combo-level snapshot into 169-cell probability mass.

    ``prior`` supplies per-combo prior probabilities so each cell can report
    priorProbabilityMass / delta / multiplier against the initial prior.
    """
    acc: dict[str, dict[str, Decimal | int]] = {}
    combo_keys = set(snapshot.combos)
    if prior is not None:
        combo_keys.update(prior.combos)
    for combo_key in sorted(combo_keys):
        combo = snapshot.combos.get(combo_key)
        prior_combo = prior.combos.get(combo_key) if prior is not None else None
        cell = cell_key(combo_key)
        entry = acc.setdefault(
            cell,
            {
                "reach": Decimal("0"),
                "prob": Decimal("0"),
                "prior_prob": Decimal("0"),
                "count": 0,
            },
        )
        if combo is not None:
            entry["reach"] = Decimal(entry["reach"]) + combo.reach
            entry["prob"] = Decimal(entry["prob"]) + combo.probability
        if prior_combo is not None:
            entry["prior_prob"] = Decimal(entry["prior_prob"]) + prior_combo.probability
        entry["count"] = int(entry["count"]) + 1

    cells: dict[str, RangeBeliefMatrixCell] = {}
    for cell in sorted(acc):
        entry = acc[cell]
        probability = Decimal(entry["prob"])
        prior_probability = Decimal(entry["prior_prob"])
        delta = probability - prior_probability
        multiplier = (
            probability / prior_probability
            if prior_probability > 0
            else None
        )
        cells[cell] = RangeBeliefMatrixCell.model_construct(
            reach_mass=Decimal(entry["reach"]),
            probability_mass=probability,
            combo_count=int(entry["count"]),
            prior_probability_mass=prior_probability,
            delta=delta,
            multiplier=multiplier,
        )
    return cells
