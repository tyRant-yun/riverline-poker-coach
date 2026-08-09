"""Public-board texture classification and next-card candidates."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from poker_coach.domain.models import Card

from .cards import RANKS, best_hand_key, category_name, deck, rank as card_rank, sort_cards, suit
from .models import BoardAnalysis


def analyze_board(board: tuple[Card, ...]) -> BoardAnalysis:
    board = sort_cards(board)
    signature = _signature(board)
    nut_combos = _possible_nut_combos(board)
    next_cards: tuple[Card, ...] = ()
    if 3 <= len(board) < 5:
        next_cards = sort_cards(
            card
            for card in deck(board)
            if _signature(board + (card,))["labels"] != signature["labels"]
        )
    return BoardAnalysis(
        board=board,
        labels=signature["labels"],
        suit_counts=signature["suit_counts"],
        rank_counts=signature["rank_counts"],
        rainbow=signature["rainbow"],
        two_tone=signature["two_tone"],
        monotone=signature["monotone"],
        paired=signature["paired"],
        double_paired=signature["double_paired"],
        connectedness=signature["connectedness"],
        high_card_ranks=signature["high_card_ranks"],
        low_card_ranks=signature["low_card_ranks"],
        static_or_dynamic=signature["static_or_dynamic"],
        next_street_change_cards=next_cards,
        possible_nut_hands=tuple(sorted({category_name(key[0]) for key in nut_combos[0]})),
        possible_nut_combos=nut_combos[1],
        nut_combo_count=nut_combos[2],
    )


def _signature(board: tuple[Card, ...]) -> dict[str, object]:
    suit_counts = Counter(suit(card) for card in board)
    rank_counts = Counter(card[0] for card in board)
    unique_suits = len(suit_counts)
    unique_ranks = sorted({card_rank(card) for card in board}, reverse=True)
    max_run = _max_consecutive_run(unique_ranks)
    monotone = len(board) >= 3 and unique_suits == 1
    two_tone = len(board) >= 3 and unique_suits == 2
    rainbow = len(board) >= 3 and unique_suits >= 3
    paired = any(count >= 2 for count in rank_counts.values())
    double_paired = sum(count >= 2 for count in rank_counts.values()) >= 2
    connectedness = (
        "highly_connected"
        if max_run >= 3
        else "connected"
        if max_run == 2
        else "disconnected"
    )
    labels: list[str] = []
    if monotone:
        labels.append("monotone")
    elif two_tone:
        labels.append("two_tone")
    elif rainbow:
        labels.append("rainbow")
    if double_paired:
        labels.append("double_paired")
    elif paired:
        labels.append("paired")
    labels.append(connectedness)
    if any(value >= 10 for value in unique_ranks):
        labels.append("high_card_structure")
    if unique_ranks and max(unique_ranks) <= 9:
        labels.append("low_card_structure")
    static_or_dynamic = (
        "dynamic"
        if monotone or two_tone or connectedness != "disconnected" or paired
        else "static"
    )
    high_cards = tuple(
        rank for rank in RANKS[::-1] if rank in {card[0] for card in board} and card_rank(rank + "c") >= 10
    )
    low_cards = tuple(
        rank for rank in RANKS if rank in {card[0] for card in board} and card_rank(rank + "c") < 10
    )
    return {
        "labels": tuple(labels),
        "suit_counts": dict(sorted(suit_counts.items())),
        "rank_counts": dict(sorted(rank_counts.items(), key=lambda item: RANKS.index(item[0]))),
        "rainbow": rainbow,
        "two_tone": two_tone,
        "monotone": monotone,
        "paired": paired,
        "double_paired": double_paired,
        "connectedness": connectedness,
        "high_card_ranks": high_cards,
        "low_card_ranks": low_cards,
        "static_or_dynamic": static_or_dynamic,
    }


def _max_consecutive_run(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(set(values))
    longest = current = 1
    for previous, value in zip(ordered, ordered[1:]):
        if value == previous + 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _possible_nut_combos(
    board: tuple[Card, ...],
) -> tuple[tuple[tuple[int, tuple[int, ...]], ...], tuple[tuple[Card, Card], ...], int]:
    candidates: list[tuple[tuple[int, tuple[int, ...]], tuple[Card, Card]]] = []
    for combo in combinations(deck(board), 2):
        cards = tuple(sort_cards(combo))  # type: ignore[assignment]
        candidates.append((best_hand_key(cards + board), cards))
    if not candidates:
        return (), (), 0
    max_key = max(key for key, _ in candidates)
    matching = tuple(cards for key, cards in candidates if key == max_key)
    return (max_key,), matching[:64], len(matching)
