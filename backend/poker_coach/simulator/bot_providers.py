"""Small deterministic in-process bot providers for the MVP table path.

These profiles are intentionally lightweight heuristics, not a solver or a
GTO claim.  They consume only the provider port's observation and legal-action
set; the authoritative runtime still validates every returned decision.
"""

from __future__ import annotations

import hashlib

from poker_coach.theory.policy_artifact import (
    PolicyArtifact,
    PreflopPolicyContext,
    default_preflop_artifact,
    policy_miss_reason,
)

from .bot_runtime import FixedPolicyProvider
from .contracts import (
    BotAttemptStatusV1,
    BotAttemptV1,
    BotDecisionV1,
    LegalActionV1,
    ObservationV1,
    SimulatorActionV1,
)


BLUEPRINT_PROFILE_IDS = ("cautious", "balanced", "aggressive")
THEORY_PROFILE_IDS = ("theory",)
BOT_PROFILE_IDS = ("fixed", *BLUEPRINT_PROFILE_IDS, *THEORY_PROFILE_IDS)


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


class PolicyArtifactBot:
    """Seeded B-grade preflop policy consumer with an honest C-grade fallback.

    The artifact only sees its actor's two private cards and public observation
    fields.  A non-covered context, unsupported tree, or non-legal sizing is
    deliberately handled by the existing balanced C-grade provider.
    """

    name = "policy-artifact-bot"

    def __init__(
        self,
        artifact: PolicyArtifact | None = None,
        *,
        context: PreflopPolicyContext | None = None,
        fallback: LightweightBlueprintProvider | None = None,
    ):
        self.artifact = artifact or default_preflop_artifact()
        self.context = context or PreflopPolicyContext()
        self.fallback = fallback or LightweightBlueprintProvider("balanced")
        self.version = self.artifact.version

    async def decide(
        self,
        observation: ObservationV1,
        legal_actions: tuple[LegalActionV1, ...],
        time_budget_ms: int,
        rng_seed: int,
    ) -> BotDecisionV1:
        del time_budget_ms
        match = self.artifact.match(observation, self.context)
        if match is None:
            return await self._fallback(
                observation, legal_actions, rng_seed, policy_miss_reason(observation, self.context, self.artifact)
            )
        legal_by_action = {item.action: item for item in legal_actions}
        if not _node_is_legal(match.frequencies, match.raise_to, legal_by_action):
            return await self._fallback(observation, legal_actions, rng_seed, "legal_sizing_miss")
        selected = _sample_action(match.frequencies, rng_seed, match.node_id, match.hand_class)
        legal = legal_by_action.get(_POLICY_ACTIONS[selected])
        if legal is None:
            return await self._fallback(observation, legal_actions, rng_seed, "selected_action_not_legal")
        amount = match.raise_to if selected == "raise_to" else (legal.min_amount if selected == "call" else None)
        if not legal.accepts(action=legal.action, amount=amount):
            return await self._fallback(observation, legal_actions, rng_seed, "selected_amount_not_legal")
        return BotDecisionV1(
            action=legal.action,
            amount=amount,
            amount_semantics=legal.amount_semantics,
            provider=self.name,
            provider_version=self.version,
            latency_ms=0,
            metadata=self._metadata(
                coverage_status="covered",
                node_id=match.node_id,
                hand_class=match.hand_class,
                degrade_reason=None,
            ),
        )

    async def _fallback(
        self,
        observation: ObservationV1,
        legal_actions: tuple[LegalActionV1, ...],
        rng_seed: int,
        reason: str,
    ) -> BotDecisionV1:
        fallback = await self.fallback.decide(observation, legal_actions, 1, rng_seed)
        return BotDecisionV1(
            action=fallback.action,
            amount=fallback.amount,
            amount_semantics=fallback.amount_semantics,
            provider=self.name,
            provider_version=self.version,
            latency_ms=0,
            degraded=True,
            fallback_reason=reason,
            attempts=(BotAttemptV1(
                provider=self.name,
                provider_version=self.version,
                status=BotAttemptStatusV1.POLICY_FALLBACK,
                latency_ms=0,
                error_code="artifact_coverage_fallback",
                error_message=reason,
            ),),
            metadata=self._metadata(
                coverage_status="fallback",
                node_id=None,
                hand_class=None,
                degrade_reason=reason,
            ) | {"fallbackProvider": fallback.provider, "fallbackProviderVersion": fallback.provider_version},
        )

    def _metadata(
        self,
        *,
        coverage_status: str,
        node_id: str | None,
        hand_class: str | None,
        degrade_reason: str | None,
    ) -> dict[str, str | None]:
        is_fallback = coverage_status != "covered"
        return {
            "kind": "policy-artifact",
            "sourceKind": str(self.artifact.source["sourceKind"]),
            "evidenceGrade": "C" if is_fallback else str(self.artifact.source["evidenceGrade"]),
            "sourceLicense": str(self.artifact.source["license"]),
            "coverageStatus": coverage_status,
            "policyVersion": self.artifact.version,
            "policyFingerprint": self.artifact.fingerprint,
            "artifactDigest": self.artifact.digest,
            "nodeId": node_id,
            "handClass": hand_class,
            "degradeReason": degrade_reason,
            "degraded": is_fallback,
        }


def build_bot_provider(profile_id: str):
    """Create an in-process provider by stable MVP profile identifier."""
    if profile_id == "fixed":
        return FixedPolicyProvider()
    if profile_id == "theory":
        return PolicyArtifactBot()
    return LightweightBlueprintProvider(profile_id)


_POLICY_ACTIONS = {
    "fold": SimulatorActionV1.FOLD,
    "call": SimulatorActionV1.CALL,
    "raise_to": SimulatorActionV1.RAISE,
}


def _node_is_legal(
    frequencies: dict[str, float] | object,
    raise_to: int | None,
    legal_by_action: dict[SimulatorActionV1, LegalActionV1],
) -> bool:
    if not isinstance(frequencies, dict):
        frequencies = dict(frequencies)  # type: ignore[arg-type]
    for action, frequency in frequencies.items():
        if frequency <= 0:
            continue
        legal = legal_by_action.get(_POLICY_ACTIONS[action])
        if legal is None:
            return False
        amount = raise_to if action == "raise_to" else (legal.min_amount if action == "call" else None)
        if not legal.accepts(action=legal.action, amount=amount):
            return False
    return True


def _sample_action(frequencies: object, rng_seed: int, node_id: str, hand_class: str) -> str:
    table = dict(frequencies)  # type: ignore[arg-type]
    draw = int.from_bytes(
        hashlib.sha256(f"{rng_seed}:{node_id}:{hand_class}".encode("utf-8")).digest()[:8],
        "big",
    ) / 2**64
    cumulative = 0.0
    for action in sorted(table):
        cumulative += float(table[action])
        if draw < cumulative:
            return action
    # Loader validates normalization; this guard avoids an illegal implicit action.
    return sorted(table)[-1]


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
