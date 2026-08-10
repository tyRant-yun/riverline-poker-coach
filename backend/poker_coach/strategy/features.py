"""Deterministic, PokerKit-independent features used for strategy matching."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from poker_coach.domain.models import ActionType, ScenarioSpec, SeatPosition, Street


@dataclass(frozen=True)
class ScenarioFeatures:
    game_variant: str
    table_size: int
    stack_bb: Decimal
    rake_signature: str
    hero_position: SeatPosition | None
    villain_position: SeatPosition | None
    street: Street
    action_signature: tuple[str, ...]
    board_labels: tuple[str, ...]
    hero_range_id: str | None
    villain_range_id: str | None
    bet_size_signature: tuple[str, ...]


def features_for_scenario(scenario: ScenarioSpec) -> ScenarioFeatures:
    positions = {seat.seat_id: seat.position for seat in scenario.seats}
    # Multiway tables have no single villain: strategy matching for 3+
    # players keys on the hero's position and the action signature only.
    villain_seat = (
        next(
            (seat.seat_id for seat in scenario.seats if seat.seat_id != scenario.hero_seat),
            None,
        )
        if scenario.table_size == 2
        else None
    )
    stack_bb = Decimal(min(seat.starting_stack for seat in scenario.seats)) / Decimal(scenario.big_blind)
    meaningful_actions = tuple(
        event.action_type.value
        for event in scenario.action_history[: scenario.decision_point.after_sequence]
        if event.action_type not in {
            ActionType.POST_BLIND,
            ActionType.DEAL_FLOP,
            ActionType.DEAL_TURN,
            ActionType.DEAL_RIVER,
        }
    )
    board_labels = _board_labels(_visible_board(scenario))
    bet_sizes = tuple(sorted(size.label for size in scenario.allowed_bet_sizes))
    rake = scenario.rake_config
    rake_signature = (
        "no_rake"
        if not rake.enabled
        else f"{rake.percent_bps}bps-cap-{rake.cap}"
    )
    return ScenarioFeatures(
        game_variant=scenario.game_variant.value,
        table_size=scenario.table_size,
        stack_bb=stack_bb,
        rake_signature=rake_signature,
        hero_position=positions.get(scenario.hero_seat),
        villain_position=positions.get(villain_seat) if villain_seat is not None else None,
        street=scenario.decision_point.street,
        action_signature=meaningful_actions,
        board_labels=board_labels,
        hero_range_id=scenario.hero_range.range_id if scenario.hero_range else None,
        villain_range_id=scenario.villain_range.range_id if scenario.villain_range else None,
        bet_size_signature=bet_sizes,
    )


def _board_labels(board: tuple[str, ...]) -> tuple[str, ...]:
    """Return the same public texture vocabulary without importing analysis."""

    if len(board) < 3:
        return ()
    ranks = "23456789TJQKA"
    rank_values = sorted({ranks.index(card[0]) for card in board}, reverse=True)
    suits = {card[1] for card in board}
    rank_counts = {rank: sum(card[0] == rank for card in board) for rank in set(card[0] for card in board)}
    if len(suits) == 1:
        labels = ["monotone"]
    elif len(suits) == 2:
        labels = ["two_tone"]
    else:
        labels = ["rainbow"]
    paired_ranks = sum(count >= 2 for count in rank_counts.values())
    if paired_ranks >= 2:
        labels.append("double_paired")
    elif paired_ranks == 1:
        labels.append("paired")
    run = _longest_run(rank_values)
    labels.append("highly_connected" if run >= 3 else "connected" if run == 2 else "disconnected")
    if any(value >= ranks.index("T") for value in rank_values):
        labels.append("high_card_structure")
    if rank_values:
        top_rank = ranks[max(rank_values)]
        rank_label = {"A": "ace_high", "K": "king_high"}.get(top_rank)
        if rank_label:
            labels.append(rank_label)
    if rank_values and max(rank_values) <= ranks.index("9"):
        labels.append("low_card_structure")
    return tuple(labels)


def _visible_board(scenario) -> tuple[str, ...]:
    """Use only cards dealt before the selected decision point.

    ScenarioSpec may carry future turn/river cards for a later node. Strategy
    matching must not let those hidden cards change a preflop or flop match.
    """

    dealt = 0
    for event in scenario.action_history[: scenario.decision_point.after_sequence]:
        if event.action_type is ActionType.DEAL_FLOP:
            dealt = 3
        elif event.action_type is ActionType.DEAL_TURN:
            dealt = 4
        elif event.action_type is ActionType.DEAL_RIVER:
            dealt = 5
    return scenario.board[:dealt]


def _longest_run(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(set(values))
    longest = current = 1
    for previous, value in zip(ordered, ordered[1:]):
        current = current + 1 if value == previous + 1 else 1
        longest = max(longest, current)
    return longest
