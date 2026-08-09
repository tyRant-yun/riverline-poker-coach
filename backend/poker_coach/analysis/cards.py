"""Small, deterministic card primitives used by the analysis core."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Iterable

from poker_coach.domain.models import Card

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VALUE = {rank: index + 2 for index, rank in enumerate(RANKS)}
VALUE_RANK = {value: rank for rank, value in RANK_VALUE.items()}
STRAIGHT_SEQUENCES = (
    (14, 2, 3, 4, 5),
    (2, 3, 4, 5, 6),
    (3, 4, 5, 6, 7),
    (4, 5, 6, 7, 8),
    (5, 6, 7, 8, 9),
    (6, 7, 8, 9, 10),
    (7, 8, 9, 10, 11),
    (8, 9, 10, 11, 12),
    (9, 10, 11, 12, 13),
    (10, 11, 12, 13, 14),
)


def rank(card: str) -> int:
    return RANK_VALUE[card[0]]


def suit(card: str) -> str:
    return card[1]


def sort_cards(cards: Iterable[str]) -> tuple[Card, ...]:
    return tuple(sorted(cards, key=lambda card: (rank(card), SUITS.index(suit(card)))))  # type: ignore[return-value]


def deck(excluded: Iterable[str] = ()) -> tuple[Card, ...]:
    dead = set(excluded)
    return tuple(
        f"{card_rank}{card_suit}"
        for card_rank in RANKS
        for card_suit in SUITS
        if f"{card_rank}{card_suit}" not in dead
    )  # type: ignore[return-value]


def ensure_unique(cards: Iterable[str], label: str = "cards") -> tuple[Card, ...]:
    normalized = tuple(cards)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} cannot contain duplicate cards")
    return sort_cards(normalized)


def straight_high(ranks: Iterable[int]) -> int | None:
    rank_set = set(ranks)
    for sequence in STRAIGHT_SEQUENCES:
        if set(sequence).issubset(rank_set):
            return 5 if sequence == (14, 2, 3, 4, 5) else sequence[-1]
    return None


def evaluate_five(cards: tuple[str, ...]) -> tuple[int, tuple[int, ...]]:
    """Return a comparable five-card hand key: category then tie breakers."""

    if len(cards) != 5 or len(set(cards)) != 5:
        raise ValueError("evaluate_five requires five distinct cards")
    ranks = [rank(card) for card in cards]
    counts = Counter(ranks)
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    flush = len({suit(card) for card in cards}) == 1
    high = straight_high(ranks)
    if flush and high is not None:
        return 8, (high,)
    if groups[0][0] == 4:
        quad = groups[0][1]
        kicker = max(value for value, count in counts.items() if count != 4)
        return 7, (quad, kicker)
    if groups[0][0] == 3 and groups[1][0] == 2:
        return 6, (groups[0][1], groups[1][1])
    if flush:
        return 5, tuple(sorted(ranks, reverse=True))
    if high is not None:
        return 4, (high,)
    if groups[0][0] == 3:
        trips = groups[0][1]
        kickers = tuple(sorted((value for value, count in counts.items() if count == 1), reverse=True))
        return 3, (trips, *kickers)
    if groups[0][0] == 2 and groups[1][0] == 2:
        pairs = tuple(sorted((groups[0][1], groups[1][1]), reverse=True))
        kicker = next(value for value, count in counts.items() if count == 1)
        return 2, (*pairs, kicker)
    if groups[0][0] == 2:
        pair = groups[0][1]
        kickers = tuple(sorted((value for value, count in counts.items() if count == 1), reverse=True))
        return 1, (pair, *kickers)
    return 0, tuple(sorted(ranks, reverse=True))


def best_hand_key(cards: Iterable[str]) -> tuple[int, tuple[int, ...]]:
    normalized = tuple(cards)
    if len(normalized) < 5:
        counts = Counter(rank(card) for card in normalized)
        groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
        if groups and groups[0][0] >= 4:
            return 7, (groups[0][1],)
        if groups and groups[0][0] == 3:
            return 3, (groups[0][1],)
        if len(groups) > 1 and groups[0][0] == 2 and groups[1][0] == 2:
            return 2, tuple(sorted((groups[0][1], groups[1][1]), reverse=True))
        if groups and groups[0][0] == 2:
            return 1, (groups[0][1],)
        return 0, tuple(sorted((rank(card) for card in normalized), reverse=True))
    return max(evaluate_five(tuple(five)) for five in combinations(normalized, 5))


def category_name(category_value: int) -> str:
    return (
        "high_card",
        "one_pair",
        "two_pair",
        "three_of_a_kind",
        "straight",
        "flush",
        "full_house",
        "four_of_a_kind",
        "straight_flush",
    )[category_value]
