"""Range expansion, combo removal, and deliberately labeled heuristics."""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations
import re

from poker_coach.domain.models import Card, RangeSource, RangeSpec

from .cards import RANKS, SUITS, sort_cards
from .hand import analyze_hand
from .models import RangeAnalysis, RangeComparison, WeightedCombo


def expand_range(
    range_spec: RangeSpec,
    *,
    dead_cards: tuple[Card, ...] = (),
) -> tuple[WeightedCombo, ...]:
    """Expand matrix and concrete combos into a deterministic weighted list."""

    dead = set(dead_cards).union(range_spec.dead_cards)
    combo_weights: dict[tuple[Card, Card], Decimal] = {}
    for hand, weight in sorted(range_spec.matrix_169.items()):
        for combo in _expand_starting_hand(hand):
            if not dead.intersection(combo):
                combo_weights[combo] = Decimal(weight)
    for combo in range_spec.combos:
        cards = tuple(sort_cards(combo.cards))  # type: ignore[assignment]
        if not dead.intersection(cards):
            combo_weights[cards] = Decimal(combo.weight)
    return tuple(
        WeightedCombo(cards=cards, weight=weight)
        for cards, weight in sorted(combo_weights.items())
        if weight > 0
    )


def parse_range_notation(notation: str, *, weight: Decimal = Decimal("1")) -> dict[str, Decimal]:
    """Parse common compact notation into normalized 169-grid entries.

    Supported forms are exact cells (``AKs``, ``QJo``, ``TT``), pair plus
    (``22+``), suited/offsuit plus (``A5s+``), and same-family ranges such as
    ``ATs-AQs``. A token may carry a weight with ``@`` or ``:``.
    """

    if not isinstance(notation, str) or not notation.strip():
        raise ValueError("range notation cannot be empty")
    if weight < 0 or weight > 1:
        raise ValueError("range weight must be between 0 and 1")
    entries: dict[str, Decimal] = {}
    for raw_token in re.split(r"[\s,]+", notation.strip()):
        if not raw_token:
            continue
        token, token_weight = _split_weight(raw_token, weight)
        for hand in _expand_notation_token(token):
            entries[hand] = token_weight
    if not entries:
        raise ValueError("range notation produced no starting hands")
    return dict(sorted(entries.items()))


def range_spec_from_notation(
    notation: str,
    *,
    range_id: str = "notation-range",
    name: str = "Imported range",
    version: str = "1",
    source: RangeSource = RangeSource.IMPORTED,
    weight: Decimal = Decimal("1"),
    dead_cards: tuple[Card, ...] = (),
) -> RangeSpec:
    return RangeSpec(
        rangeId=range_id,
        name=name,
        version=version,
        source=source,
        matrix169=parse_range_notation(notation, weight=weight),
        deadCards=dead_cards,
    )


def analyze_range(
    range_spec: RangeSpec,
    board: tuple[Card, ...] = (),
    *,
    known_cards: tuple[Card, ...] = (),
) -> RangeAnalysis:
    base_combos = expand_range(range_spec)
    combos = expand_range(range_spec, dead_cards=known_cards)
    total_weight = sum((combo.weight for combo in combos), Decimal("0"))
    value = bluff = draw = 0
    for combo in combos:
        hand = analyze_hand(combo.cards, board)
        if _is_value(hand.made_hand, hand.category.value):
            value += 1
        if hand.draws:
            draw += 1
        if not _is_value(hand.made_hand, hand.category.value) and not hand.draws:
            bluff += 1
    blocked_combos = len(base_combos) - len(combos)
    blocked_weight = sum((combo.weight for combo in base_combos), Decimal("0")) - total_weight
    return RangeAnalysis(
        total_combos=len(combos),
        weighted_combos=total_weight,
        value_combos=value,
        bluff_combos=bluff,
        draw_combos=draw,
        blocked_combos=blocked_combos,
        blocked_weight=max(blocked_weight, Decimal("0")),
        blocker_cards=sort_cards(known_cards),
        polarity=_polarity(value, bluff),
        heuristic=True,
    )


def blocker_effect(
    range_spec: RangeSpec,
    blocker_cards: tuple[Card, ...],
    *,
    dead_cards: tuple[Card, ...] = (),
) -> RangeAnalysis:
    return analyze_range(
        range_spec,
        known_cards=tuple(sort_cards(tuple(dead_cards) + tuple(blocker_cards))),
    )


def compare_ranges(
    hero_range: RangeSpec,
    villain_range: RangeSpec,
    board: tuple[Card, ...] = (),
    *,
    hero_known_cards: tuple[Card, ...] = (),
    villain_known_cards: tuple[Card, ...] = (),
    hero_equity: Decimal | None = None,
) -> RangeComparison:
    hero = analyze_range(hero_range, board, known_cards=villain_known_cards)
    villain = analyze_range(villain_range, board, known_cards=hero_known_cards)
    hero_nut_share = _nut_share(hero_range, board, villain_known_cards)
    villain_nut_share = _nut_share(villain_range, board, hero_known_cards)
    nut_advantage = hero_nut_share - villain_nut_share
    distribution = {
        "hero_value": _share(hero.value_combos, hero.total_combos),
        "hero_draw": _share(hero.draw_combos, hero.total_combos),
        "villain_value": _share(villain.value_combos, villain.total_combos),
        "villain_draw": _share(villain.draw_combos, villain.total_combos),
    }
    return RangeComparison(
        hero=hero,
        villain=villain,
        range_advantage=None if hero_equity is None else hero_equity - (Decimal("1") - hero_equity),
        nut_advantage=nut_advantage,
        equity_distribution=distribution,
        heuristic=hero_equity is None,
    )


def _expand_starting_hand(hand: str) -> tuple[tuple[Card, Card], ...]:
    first, second = hand[0], hand[1]
    if first == second:
        return tuple(
            sort_cards((f"{first}{suit_a}", f"{second}{suit_b}"))  # type: ignore[return-value]
            for suit_a, suit_b in combinations(SUITS, 2)
        )
    suffix = hand[2]
    if suffix == "s":
        return tuple(
            sort_cards((f"{first}{suit_name}", f"{second}{suit_name}"))  # type: ignore[return-value]
            for suit_name in SUITS
        )
    return tuple(
        sort_cards((f"{first}{suit_a}", f"{second}{suit_b}"))  # type: ignore[return-value]
        for suit_a in SUITS
        for suit_b in SUITS
        if suit_a != suit_b
    )


def _split_weight(token: str, default_weight: Decimal) -> tuple[str, Decimal]:
    for separator in ("@", ":"):
        if separator in token:
            raw_token, raw_weight = token.rsplit(separator, 1)
            parsed = Decimal(raw_weight)
            if parsed < 0 or parsed > 1:
                raise ValueError("range token weight must be between 0 and 1")
            return raw_token, parsed
    return token, default_weight


def _expand_notation_token(token: str) -> tuple[str, ...]:
    token = token.strip().upper()
    if token.endswith("+"):
        base = token[:-1]
        if len(base) == 2 and base[0] == base[1]:
            start = RANKS.index(base[0])
            return tuple(f"{rank}{rank}" for rank in RANKS[start:])
        if len(base) != 3:
            raise ValueError(f"invalid plus range token: {token}")
        first, second, suffix = _canonical_hand(base)
        first_index = RANKS.index(first)
        second_index = RANKS.index(second)
        if first_index <= second_index:
            raise ValueError(f"plus range must have descending ranks: {token}")
        return tuple(
            f"{first}{rank}{suffix}"
            for rank in RANKS[second_index:first_index]
        )
    if "-" in token:
        start, end = token.split("-", 1)
        start = _canonical_hand(start)
        end = _canonical_hand(end)
        if start[0] == start[1] and end[0] == end[1]:
            low = min(RANKS.index(start[0]), RANKS.index(end[0]))
            high = max(RANKS.index(start[0]), RANKS.index(end[0]))
            return tuple(f"{rank}{rank}" for rank in RANKS[low : high + 1])
        if start[0] != end[0] or start[2:] != end[2:]:
            raise ValueError(f"range endpoints must share a family: {token}")
        low = min(RANKS.index(start[1]), RANKS.index(end[1]))
        high = max(RANKS.index(start[1]), RANKS.index(end[1]))
        return tuple(f"{start[0]}{rank}{start[2]}" for rank in RANKS[low : high + 1])
    if len(token) == 2 and token[0] != token[1]:
        first, second, _ = _canonical_hand(token + "s")
        return (f"{first}{second}s", f"{first}{second}o")
    first, second, suffix = _canonical_hand(token)
    if first == second:
        return (f"{first}{second}",)
    return (f"{first}{second}{suffix}",)


def _canonical_hand(token: str) -> tuple[str, str, str]:
    token = token.strip().upper()
    if len(token) == 2 and token[0] == token[1]:
        return token[0], token[1], ""
    if len(token) != 3 or token[0] not in RANKS or token[1] not in RANKS:
        raise ValueError(f"invalid starting-hand token: {token}")
    suffix = token[2].lower()
    if suffix not in {"s", "o"}:
        raise ValueError(f"non-pair token must end with s or o: {token}")
    first, second = token[0], token[1]
    if RANKS.index(first) < RANKS.index(second):
        first, second = second, first
    return first, second, suffix


def _is_value(made_hand: str, category: str) -> bool:
    return category in {
        "two_pair",
        "three_of_a_kind",
        "straight",
        "flush",
        "full_house",
        "four_of_a_kind",
        "straight_flush",
    } or made_hand in {"overpair", "top_pair"}


def _polarity(value: int, bluff: int) -> str:
    if value and bluff:
        return "polarized"
    if value:
        return "value_heavy"
    if bluff:
        return "bluff_heavy"
    return "merged"


def _share(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator) if denominator else Decimal("0")


def _nut_share(
    range_spec: RangeSpec,
    board: tuple[Card, ...],
    known_cards: tuple[Card, ...],
) -> Decimal:
    combos = expand_range(range_spec, dead_cards=known_cards)
    if not combos:
        return Decimal("0")
    nut_count = 0
    for combo in combos:
        hand = analyze_hand(combo.cards, board)
        if hand.category.value in {
            "straight",
            "flush",
            "full_house",
            "four_of_a_kind",
            "straight_flush",
        }:
            nut_count += 1
    return _share(nut_count, len(combos))
