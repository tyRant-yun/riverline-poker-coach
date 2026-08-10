"""Deterministic strategy analyzer: solver math -> teaching vocabulary.

Turns raw per-combo strategy tables into human-readable facts
(primary action, mixing degree, value/bluff/check shapes). This is the
layer that keeps raw arrays away from the LLM — the model only ever sees
these summaries plus the evidence items derived from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import SolverNode, SolveResult

# Classification thresholds (heuristics; deterministic and labeled as such
# in the evidence descriptions).
_VALUE_EQUITY = 0.60
_VALUE_BET_FREQ = 0.85
_BLUFF_BET_FREQ = 0.40
_BLUFF_EQUITY = 0.50
_PURE_CHECK_FREQ = 0.85
_MIXED_BET_FREQ = 0.15
_SPREAD_THRESHOLD = 0.05


def _is_bet_action(action: str) -> bool:
    return action.startswith(("Bet", "Raise", "AllIn"))


@dataclass(frozen=True)
class NodeAnalysis:
    actions: tuple[str, ...]
    primary_action: str
    primary_frequency: float
    mixing_degree: float  # 0 = pure, closer to 1 = heavily mixed
    action_spread: int  # actions with meaningful range frequency
    range_bet_frequency: float  # weighted share of bet-like actions


@dataclass(frozen=True)
class HandAnalysis:
    combo: str
    primary_action: str
    primary_frequency: float
    shape_class: str  # value_bet | bluff_bet | mixed_bet | check | check_dominant


@dataclass(frozen=True)
class SolverAnalysis:
    root: NodeAnalysis
    response: NodeAnalysis | None = None
    hero_hands: tuple[HandAnalysis, ...] = ()
    villain_hands: tuple[HandAnalysis, ...] = ()


def summarize_node(node: SolverNode) -> NodeAnalysis:
    total_weight = sum(hand.weight for hand in node.hands) or 1.0
    weighted: dict[str, float] = {}
    for hand in node.hands:
        for action, frequency in hand.strategy.items():
            weighted[action] = weighted.get(action, 0.0) + hand.weight * frequency
    frequencies = {action: value / total_weight for action, value in weighted.items()}
    primary_action = max(frequencies, key=frequencies.get)
    primary_frequency = frequencies[primary_action]
    spread = sum(1 for value in frequencies.values() if value > _SPREAD_THRESHOLD)
    range_bet_frequency = sum(
        value for action, value in frequencies.items() if _is_bet_action(action)
    )
    return NodeAnalysis(
        actions=tuple(node.actions),
        primary_action=primary_action,
        primary_frequency=primary_frequency,
        mixing_degree=round(1.0 - primary_frequency, 4),
        action_spread=spread,
        range_bet_frequency=round(range_bet_frequency, 4),
    )


def classify_hand(node: SolverNode, hand) -> str:
    bet_frequency = sum(
        frequency
        for action, frequency in hand.strategy.items()
        if _is_bet_action(action)
    )
    check_frequency = hand.strategy.get("Check", 0.0)
    if bet_frequency >= _VALUE_BET_FREQ and hand.equity >= _VALUE_EQUITY:
        return "value_bet"
    if bet_frequency >= _BLUFF_BET_FREQ and hand.equity < _BLUFF_EQUITY:
        return "bluff_bet"
    if check_frequency >= _PURE_CHECK_FREQ:
        return "check"
    if bet_frequency > _MIXED_BET_FREQ:
        return "mixed_bet"
    return "check_dominant"


def summarize_hand(node: SolverNode, hand) -> HandAnalysis:
    primary_action = max(hand.strategy, key=hand.strategy.get)
    return HandAnalysis(
        combo=hand.combo,
        primary_action=primary_action,
        primary_frequency=hand.strategy[primary_action],
        shape_class=classify_hand(node, hand),
    )


def analyze(result: SolveResult, *, hero_player: int = 0) -> SolverAnalysis:
    """Analyze a solved result; hero_player selects which dumped node is hero."""
    root_node = result.root
    response_node = result.response_node

    hero_node = root_node if root_node.player == hero_player else response_node
    villain_node = response_node if hero_node is root_node else root_node
    if hero_node is None or villain_node is None:
        raise ValueError("solver result does not contain both hero and villain nodes")

    hero_hands = tuple(summarize_hand(hero_node, hand) for hand in hero_node.hands)
    villain_hands = tuple(summarize_hand(villain_node, hand) for hand in villain_node.hands)
    return SolverAnalysis(
        root=summarize_node(root_node),
        response=summarize_node(response_node) if response_node is not None else None,
        hero_hands=hero_hands,
        villain_hands=villain_hands,
    )
