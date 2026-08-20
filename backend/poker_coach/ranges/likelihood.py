"""Deterministic, public-information likelihood features for Range V2.

This module is deliberately a bounded heuristic.  It does not read private
opponent cards, RNG/deck state, payouts, profiles, or future events, and it
does not claim solver/GTO provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from poker_coach.analysis.cards import RANK_VALUE
from poker_coach.domain.models import Card, Street
from poker_coach.simulator.contracts import SimulatorActionV1


@dataclass(frozen=True, slots=True)
class PublicActionContext:
    board: tuple[Card, ...]
    pot_before: int
    stack_before: int
    position: str

    @property
    def spr(self) -> Decimal:
        if self.pot_before <= 0:
            return Decimal("999")
        return Decimal(self.stack_before) / Decimal(self.pot_before)


def size_bucket(action: SimulatorActionV1, amount: int | None, pot_before: int) -> str:
    if action in {SimulatorActionV1.CHECK, SimulatorActionV1.FOLD} or not amount:
        return "none"
    ratio = Decimal(amount) / Decimal(max(1, pot_before))
    if ratio <= Decimal("0.40"):
        return "small"
    if ratio <= Decimal("0.80"):
        return "medium"
    if ratio <= Decimal("1.25"):
        return "large"
    return "overbet"


def spr_bucket(spr: Decimal) -> str:
    if spr < 4:
        return "short"
    if spr < 10:
        return "medium"
    return "deep"


def change_reason(
    action: SimulatorActionV1,
    street: Street,
    amount: int | None,
    context: PublicActionContext,
) -> str:
    return ":".join(
        (
            "public_action",
            street.value,
            action.value,
            size_bucket(action, amount, context.pot_before),
            context.position,
            spr_bucket(context.spr),
        )
    )


def likelihood(
    combo: str,
    action: SimulatorActionV1,
    street: Street,
    amount: int | None,
    context: PublicActionContext,
) -> Decimal:
    """Return P(public action | combo features), clipped to a safe interval."""
    bucket = size_bucket(action, amount, context.pot_before)
    made, draw, preflop = _combo_features(combo, context.board)
    selectivity = {
        "small": Decimal("0.80"),
        "medium": Decimal("1.00"),
        "large": Decimal("1.25"),
        "overbet": Decimal("1.50"),
        "none": Decimal("0.70"),
    }[bucket]
    if context.position in {"utg", "mp"}:
        selectivity += Decimal("0.10")
    if spr_bucket(context.spr) == "deep":
        selectivity += Decimal("0.08")
    elif spr_bucket(context.spr) == "short":
        selectivity -= Decimal("0.08")

    feature = Decimal(made) + Decimal(draw) * Decimal("0.75")
    if street is Street.PREFLOP:
        feature = Decimal(preflop) / Decimal("3")

    if action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
        value = Decimal("0.22") - (selectivity - Decimal("0.8")) * Decimal("0.18")
        value += feature * (Decimal("0.08") + selectivity * Decimal("0.035"))
    elif action is SimulatorActionV1.CALL:
        pressure = {
            "small": Decimal("0.00"), "medium": Decimal("0.04"),
            "large": Decimal("0.08"), "overbet": Decimal("0.13"),
            "none": Decimal("0.00"),
        }[bucket]
        value = Decimal("0.34") - pressure + feature * Decimal("0.075")
        value += Decimal(draw) * Decimal("0.04")
    elif action is SimulatorActionV1.FOLD:
        value = Decimal("0.86") - feature * Decimal("0.14")
    else:  # check
        value = Decimal("0.74") - feature * Decimal("0.075")
        value += Decimal("0.04") if made >= 3 else Decimal("0")
    return max(Decimal("0.02"), min(Decimal("0.95"), value))


@lru_cache(maxsize=4096)
def _combo_features(combo: str, board: tuple[Card, ...]) -> tuple[int, int, int]:
    first, second = combo[:2], combo[2:]
    hole = (first, second)
    pair = first[0] == second[0]
    suited = first[1] == second[1]
    rank_gap = abs(RANK_VALUE[first[0]] - RANK_VALUE[second[0]])
    broadway = sum(card[0] in "TJQKA" for card in hole)
    preflop = min(5, (3 if pair else 0) + (1 if suited else 0) + broadway + (1 if rank_gap <= 1 else 0))
    if not board:
        return 0, 0, preflop

    cards = (*hole, *board)
    rank_counts: dict[str, int] = {}
    suit_counts: dict[str, int] = {}
    for card in cards:
        rank_counts[card[0]] = rank_counts.get(card[0], 0) + 1
        suit_counts[card[1]] = suit_counts.get(card[1], 0) + 1
    counts = sorted(rank_counts.values(), reverse=True)
    made = 0
    if counts[0] >= 4:
        made = 5
    elif counts[0] >= 3:
        made = 4
    elif len(counts) > 1 and counts[0] >= 2 and counts[1] >= 2:
        made = 3
    elif counts[0] >= 2:
        made = 2
    if max(suit_counts.values()) >= 5:
        made = max(made, 5)

    values = {RANK_VALUE[rank] for rank in rank_counts}
    if 14 in values:
        values.add(1)
    longest = _longest_run(values)
    if longest >= 5:
        made = max(made, 5)
    draw = 0
    if max(suit_counts.values()) == 4:
        draw += 2
    if longest == 4:
        draw += 1
    return made, draw, preflop


def _longest_run(values: set[int]) -> int:
    longest = current = 0
    previous: int | None = None
    for value in sorted(values):
        current = current + 1 if previous is not None and value == previous + 1 else 1
        longest = max(longest, current)
        previous = value
    return longest
