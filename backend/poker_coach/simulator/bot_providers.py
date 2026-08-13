"""Small deterministic in-process bot providers for the MVP table path.

These profiles are intentionally lightweight heuristics, not a solver or a
GTO claim.  They consume only the provider port's observation and legal-action
set; the authoritative runtime still validates every returned decision.
"""

from __future__ import annotations

from .bot_runtime import FixedPolicyProvider
from .contracts import (
    BotDecisionV1,
    LegalActionV1,
    ObservationV1,
    SimulatorActionV1,
)


BLUEPRINT_PROFILE_IDS = ("cautious", "balanced", "aggressive")
BOT_PROFILE_IDS = ("fixed", *BLUEPRINT_PROFILE_IDS)


class LightweightBlueprintProvider:
    """Deterministic, legal-action-only heuristic profile.

    ``cautious`` avoids a wager when folding is allowed; ``balanced`` prefers
    check/call and otherwise uses the midpoint; ``aggressive`` prefers the
    largest available bet or raise.  It neither evaluates hidden cards nor
    represents a solved strategy.
    """

    name = "lightweight-blueprint"
    version = "1.0.0"

    def __init__(self, profile_id: str):
        if profile_id not in BLUEPRINT_PROFILE_IDS:
            raise ValueError(f"unknown bot profile: {profile_id}")
        self.profile_id = profile_id

    async def decide(
        self,
        observation: ObservationV1,
        legal_actions: tuple[LegalActionV1, ...],
        time_budget_ms: int,
        rng_seed: int,
    ) -> BotDecisionV1:
        del time_budget_ms, rng_seed
        legal = _select_profile_action(self.profile_id, observation, legal_actions)
        return BotDecisionV1(
            action=legal.action,
            amount=_profile_amount(self.profile_id, legal),
            amount_semantics=legal.amount_semantics,
            provider=self.name,
            provider_version=self.version,
            latency_ms=0,
            metadata={
                "kind": "lightweight-heuristic",
                "profileId": self.profile_id,
                "strategy": _PROFILE_DESCRIPTIONS[self.profile_id],
            },
        )


def build_bot_provider(profile_id: str):
    """Create an in-process provider by stable MVP profile identifier."""
    if profile_id == "fixed":
        return FixedPolicyProvider()
    return LightweightBlueprintProvider(profile_id)


_PROFILE_DESCRIPTIONS = {
    "cautious": "fold-check-minimum",
    "balanced": "visible-strength-price-action-variety",
    "aggressive": "maximum-bet-or-raise",
}


def _select_profile_action(
    profile_id: str,
    observation: ObservationV1,
    legal_actions: tuple[LegalActionV1, ...],
) -> LegalActionV1:
    """Choose only from the legal set using deliberately coarse visible facts."""
    by_action = {legal.action: legal for legal in legal_actions}
    strength = _visible_hand_strength(observation)
    call = by_action.get(SimulatorActionV1.CALL)
    pot_odds = (
        call.min_amount / (observation.pot + call.min_amount)
        if call is not None and call.min_amount is not None
        else 0.0
    )
    if profile_id == "balanced":
        if call is None:
            if strength >= 0.72 and SimulatorActionV1.BET in by_action:
                return by_action[SimulatorActionV1.BET]
            return _first_legal(
                by_action,
                (SimulatorActionV1.CHECK, SimulatorActionV1.BET, SimulatorActionV1.FOLD),
            )
        if strength >= 0.82 and SimulatorActionV1.RAISE in by_action:
            return by_action[SimulatorActionV1.RAISE]
        if strength < pot_odds + 0.08 and SimulatorActionV1.FOLD in by_action:
            return by_action[SimulatorActionV1.FOLD]
        return _first_legal(
            by_action,
            (SimulatorActionV1.CALL, SimulatorActionV1.CHECK, SimulatorActionV1.FOLD),
        )
    priorities = {
        "cautious": (
            SimulatorActionV1.FOLD,
            SimulatorActionV1.CHECK,
            SimulatorActionV1.CALL,
            SimulatorActionV1.BET,
            SimulatorActionV1.RAISE,
        ),
        "balanced": (
            SimulatorActionV1.CHECK,
            SimulatorActionV1.CALL,
            SimulatorActionV1.BET,
            SimulatorActionV1.RAISE,
            SimulatorActionV1.FOLD,
        ),
        "aggressive": (
            SimulatorActionV1.BET,
            SimulatorActionV1.RAISE,
            SimulatorActionV1.CALL,
            SimulatorActionV1.CHECK,
            SimulatorActionV1.FOLD,
        ),
    }[profile_id]
    return _first_legal(by_action, priorities)


def _first_legal(
    by_action: dict[SimulatorActionV1, LegalActionV1],
    priorities: tuple[SimulatorActionV1, ...],
) -> LegalActionV1:
    for action in priorities:
        if action in by_action:
            return by_action[action]
    raise ValueError("legal_actions must contain at least one action")


def _visible_hand_strength(observation: ObservationV1) -> float:
    """A coarse, explainable score from only own cards and public board.

    This is intentionally not an equity calculation or solver approximation.
    It only creates enough variety for a responsive MVP opponent.
    """
    ranks = {card[0] for card in observation.own_hole_cards}
    board_ranks = [card[0] for card in observation.board]
    rank_value = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
    values = sorted((rank_value[card[0]] for card in observation.own_hole_cards), reverse=True)
    if len(ranks) == 1:
        strength = 0.78 + min(values[0] - 2, 10) / 100
    elif any(rank in board_ranks for rank in ranks):
        strength = 0.82 if max(board_ranks.count(rank) for rank in ranks) >= 2 else 0.74
    elif values[0] >= 13 and values[1] >= 11:
        strength = 0.64
    elif values[0] >= 12:
        strength = 0.48
    else:
        strength = 0.22
    position_distance = (observation.observer_seat - observation.button_seat) % observation.table_size
    if position_distance in (0, observation.table_size - 1):
        strength += 0.03
    if observation.street.value in ("turn", "river") and not any(rank in board_ranks for rank in ranks):
        strength -= 0.05
    return max(0.0, min(1.0, strength))


def _profile_amount(profile_id: str, legal: LegalActionV1) -> int | None:
    if legal.min_amount is None or legal.max_amount is None:
        return None
    if profile_id == "cautious":
        return legal.min_amount
    if profile_id == "balanced":
        return (legal.min_amount + legal.max_amount) // 2
    return legal.max_amount
