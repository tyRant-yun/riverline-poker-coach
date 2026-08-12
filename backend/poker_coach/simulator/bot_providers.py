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
        del observation, time_budget_ms, rng_seed
        legal = _select_profile_action(self.profile_id, legal_actions)
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
    "balanced": "check-call-midpoint",
    "aggressive": "maximum-bet-or-raise",
}


def _select_profile_action(
    profile_id: str, legal_actions: tuple[LegalActionV1, ...]
) -> LegalActionV1:
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
    by_action = {legal.action: legal for legal in legal_actions}
    for action in priorities:
        if action in by_action:
            return by_action[action]
    raise ValueError("legal_actions must contain at least one action")


def _profile_amount(profile_id: str, legal: LegalActionV1) -> int | None:
    if legal.min_amount is None or legal.max_amount is None:
        return None
    if profile_id == "cautious":
        return legal.min_amount
    if profile_id == "balanced":
        return (legal.min_amount + legal.max_amount) // 2
    return legal.max_amount
