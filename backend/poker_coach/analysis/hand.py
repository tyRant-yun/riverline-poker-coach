"""Made-hand and draw classification for a concrete holding."""

from __future__ import annotations

from collections import Counter

from poker_coach.domain.models import Card

from .cards import (
    STRAIGHT_SEQUENCES,
    best_hand_key,
    category_name,
    deck,
    rank as card_rank,
    sort_cards,
    suit,
)
from .models import DrawType, HandAnalysis, HandCategory


def analyze_hand(hole_cards: tuple[Card, Card], board: tuple[Card, ...]) -> HandAnalysis:
    cards = tuple(hole_cards) + tuple(board)
    key = best_hand_key(cards)
    category = HandCategory(category_name(key[0]))
    made_hand = _made_hand_name(category, hole_cards, board)
    overcards = _overcards(hole_cards, board)
    draws, straight_outs, flush_outs = _draws(cards, board, category)
    out_cards = sort_cards(set(straight_outs).union(flush_outs))
    counterfeit = _counterfeit_risk(cards, board, category)
    return HandAnalysis(
        cards=sort_cards(cards),
        category=category,
        made_hand=made_hand,
        overcards=sort_cards(overcards),
        draws=tuple(draws),
        straight_outs=sort_cards(straight_outs),
        flush_outs=sort_cards(flush_outs),
        out_cards=out_cards,
        out_count=len(out_cards),
        counterfeit_risk_cards=sort_cards(counterfeit),
    )


def _made_hand_name(
    category: HandCategory,
    hole_cards: tuple[Card, Card],
    board: tuple[Card, ...],
) -> str:
    if category is HandCategory.THREE_OF_A_KIND:
        if hole_cards[0][0] == hole_cards[1][0]:
            return "set"
        return "trips"
    if category is HandCategory.ONE_PAIR and board:
        hole_ranks = [card_rank(card) for card in hole_cards]
        board_ranks = sorted({card_rank(card) for card in board}, reverse=True)
        if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] > max(board_ranks):
            return "overpair"
        if any(value == board_ranks[0] for value in hole_ranks):
            return "top_pair"
        if len(board_ranks) > 1 and any(value == board_ranks[1] for value in hole_ranks):
            return "middle_pair"
        if board_ranks and any(value == board_ranks[-1] for value in hole_ranks):
            return "bottom_pair"
    return category.value


def _overcards(hole_cards: tuple[Card, Card], board: tuple[Card, ...]) -> tuple[Card, ...]:
    if not board:
        return ()
    highest_board = max(card_rank(card) for card in board)
    return tuple(card for card in hole_cards if card_rank(card) > highest_board)


def _draws(
    cards: tuple[Card, ...],
    board: tuple[Card, ...],
    category: HandCategory,
) -> tuple[list[DrawType], tuple[Card, ...], tuple[Card, ...]]:
    if len(board) < 3 or category in {
        HandCategory.FLUSH,
        HandCategory.FULL_HOUSE,
        HandCategory.FOUR_OF_A_KIND,
        HandCategory.STRAIGHT_FLUSH,
    }:
        return [], (), ()

    known = set(cards)
    unknown = deck(known)
    ranks = {card_rank(card) for card in cards}
    flush_outs: set[Card] = set()
    draws: list[DrawType] = []
    suit_counts = Counter(suit(card) for card in cards)
    if category not in {HandCategory.FLUSH, HandCategory.STRAIGHT_FLUSH}:
        four_card_suits = {card_suit for card_suit, count in suit_counts.items() if count == 4}
        for card in unknown:
            if suit(card) in four_card_suits:
                flush_outs.add(card)
        if flush_outs:
            draws.append(DrawType.FLUSH_DRAW)
        if len(board) == 3 and not flush_outs:
            if any(count == 3 for count in suit_counts.values()):
                draws.append(DrawType.BACKDOOR_FLUSH_DRAW)

    one_card_sequences: list[set[int]] = []
    if category is not HandCategory.STRAIGHT:
        for sequence in STRAIGHT_SEQUENCES:
            missing = set(sequence) - ranks
            if len(missing) == 1:
                one_card_sequences.append(missing)
    missing_ranks = set().union(*one_card_sequences) if one_card_sequences else set()
    straight_outs = {
        card for card in unknown if card_rank(card) in missing_ranks
    }
    has_four_consecutive = any(
        set(range(start, start + 4)).issubset(ranks) for start in range(2, 12)
    )
    if has_four_consecutive and len(missing_ranks) >= 2:
        draws.append(DrawType.OPEN_ENDED_STRAIGHT_DRAW)
    elif len(missing_ranks) >= 2:
        draws.append(DrawType.DOUBLE_GUTTER)
    elif len(missing_ranks) == 1:
        draws.append(DrawType.GUTSHOT)

    has_straight_draw = any(
        draw
        in {
            DrawType.OPEN_ENDED_STRAIGHT_DRAW,
            DrawType.GUTSHOT,
            DrawType.DOUBLE_GUTTER,
        }
        for draw in draws
    )
    if DrawType.FLUSH_DRAW in draws and has_straight_draw:
        draws.append(DrawType.COMBO_DRAW)
    return draws, sort_cards(straight_outs), sort_cards(flush_outs)


def _counterfeit_risk(
    cards: tuple[Card, ...], board: tuple[Card, ...], category: HandCategory
) -> tuple[Card, ...]:
    if len(board) < 3 or category not in {
        HandCategory.ONE_PAIR,
        HandCategory.TWO_PAIR,
    }:
        return ()
    rank_counts = Counter(card_rank(card) for card in board)
    singleton_board_ranks = {value for value, count in rank_counts.items() if count == 1}
    known = set(cards)
    return tuple(
        card
        for card in deck(known)
        if card_rank(card) in singleton_board_ranks
    )
