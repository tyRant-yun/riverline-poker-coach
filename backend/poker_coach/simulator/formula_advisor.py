"""Fast, read-only L0 poker formula advice at the simulator boundary.

This service deliberately reports only deterministic chip math and legal-action
facts.  Its optional hint is labelled heuristic; it is never a solver, GTO,
equity, range, EV, or opponent-information claim.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from time import perf_counter_ns
from typing import Literal, Sequence

from pydantic import ConfigDict, Field

from poker_coach.domain.models import DomainModel, Street

from .contracts import AmountSemanticsV1, LegalActionV1, ObservationV1, SimulatorActionV1


class _FormulaContractV1(DomainModel):
    """Immutable, project-owned Formula Advisor result contract."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1


class FormulaAdvisorInputsV1(_FormulaContractV1):
    """Non-secret input identity and scope retained with each result."""

    hand_id: str
    sequence: int = Field(ge=0)
    observer_seat: int = Field(ge=0, le=7)
    street: Street
    legal_actions_count: int = Field(ge=0)


class LegalActionBoundV1(_FormulaContractV1):
    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)
    all_in_endpoint: bool


class FormulaRecommendationV1(_FormulaContractV1):
    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    amount: int | None = Field(default=None, ge=0)
    kind: Literal["heuristic"] = "heuristic"
    threshold: Decimal | None = Field(default=None, ge=0, le=1)
    reason: str
    limitations: str


class FormulaLatencyV1(_FormulaContractV1):
    elapsed_microseconds: int = Field(ge=0)
    measured_by: Literal["service_monotonic_clock"] = "service_monotonic_clock"


class AdvisorDecisionIdentityV1(_FormulaContractV1):
    """The current public/Hero-visible decision node, never a solver identity."""

    fingerprint: str
    hand_id: str
    sequence: int = Field(ge=0)
    street: Street


class FormulaAdvisorResultV1(_FormulaContractV1):
    """Versioned L0 result with auditable definitions and provenance."""

    pot: int = Field(ge=0)
    hero_stack: int = Field(ge=0)
    call_cost: int = Field(ge=0)
    pot_after_call: int = Field(ge=0)
    pot_odds: Decimal = Field(ge=0, le=1)
    pot_odds_basis: Literal["call_cost_over_pot_after_call", "no_call_cost"]
    effective_stack: int = Field(ge=0)
    spr: Decimal | None = Field(default=None, ge=0)
    spr_basis: Literal[
        "effective_stack_over_current_pot_before_action", "undefined_zero_pot"
    ]
    legal_action_bounds: tuple[LegalActionBoundV1, ...]
    recommended_action: FormulaRecommendationV1 | None = None
    recommendation_unavailable_reason: str | None = None
    status: Literal["ready", "degraded", "not_ready", "not_applicable"]
    confidence: Literal["high", "limited", "unavailable"]
    equity_threshold: Decimal | None = Field(default=None, ge=0, le=1)
    explanation_key: str
    limitations: tuple[str, ...]
    decision: AdvisorDecisionIdentityV1
    inputs: FormulaAdvisorInputsV1
    assumptions: tuple[str, ...]
    source: Literal["deterministic_formula", "safe_legal_fallback"] = "deterministic_formula"
    version: Literal["formula-advisor/v1"] = "formula-advisor/v1"
    latency: FormulaLatencyV1


class FormulaAdvisor:
    """Evaluate formulas without taking actions or changing rules/events."""

    version = "formula-advisor/v1"

    def __init__(self, *, call_pot_odds_threshold: Decimal = Decimal("0.25")) -> None:
        if not Decimal("0") <= call_pot_odds_threshold <= Decimal("1"):
            raise ValueError("call_pot_odds_threshold must be between 0 and 1")
        self._call_pot_odds_threshold = call_pot_odds_threshold

    def evaluate(
        self,
        observation: ObservationV1,
        *,
        legal_actions: Sequence[LegalActionV1] | None = None,
        decision_fingerprint: str | None = None,
    ) -> FormulaAdvisorResultV1:
        """Return deterministic decision-point math from permission-safe inputs.

        Pot odds are ``call_cost / (current_pot + call_cost)``.  A zero call
        cost returns 0 with ``no_call_cost`` rather than implying an equity
        threshold.  SPR is the minimum remaining stack among active seats,
        divided by the current *pre-action* pot; it is undefined for a zero pot.
        """

        started = perf_counter_ns()
        actions = tuple(observation.legal_actions if legal_actions is None else legal_actions)
        hero_stack = observation.stacks[observation.observer_seat]
        call = next((item for item in actions if item.action is SimulatorActionV1.CALL), None)
        call_cost = 0 if call is None else call.min_amount
        assert call_cost is not None  # validated LegalActionV1 invariant
        pot_after_call = observation.pot + call_cost
        pot_odds_basis: Literal["call_cost_over_pot_after_call", "no_call_cost"]
        if call_cost == 0:
            pot_odds = Decimal("0")
            pot_odds_basis = "no_call_cost"
        else:
            pot_odds = Decimal(call_cost) / Decimal(pot_after_call)
            pot_odds_basis = "call_cost_over_pot_after_call"

        effective_stack = min(observation.stacks[seat] for seat in observation.active_seats)
        if observation.pot == 0:
            spr = None
            spr_basis: Literal[
                "effective_stack_over_current_pot_before_action", "undefined_zero_pot"
            ] = "undefined_zero_pot"
        else:
            spr = Decimal(effective_stack) / Decimal(observation.pot)
            spr_basis = "effective_stack_over_current_pot_before_action"

        bounds = tuple(self._bound(action, observation, hero_stack) for action in actions)
        fingerprint = decision_fingerprint or self._fingerprint(observation, actions)
        limitations = (
            "Deterministic L0 guidance only; it is not a solver, GTO, range, EV, or opponent-truth conclusion.",
            "Only Hero cards, public board/action facts, stacks, pot, position, and authoritative legal actions are used.",
        )
        status: Literal["ready", "degraded", "not_ready", "not_applicable"]
        confidence: Literal["high", "limited", "unavailable"]
        source: Literal["deterministic_formula", "safe_legal_fallback"]
        explanation_key: str
        equity_threshold: Decimal | None
        if not actions:
            recommendation = None
            status = "not_ready"
            confidence = "unavailable"
            source = "deterministic_formula"
            explanation_key = "advisor.not_ready.no_legal_actions"
            equity_threshold = None
        else:
            try:
                recommendation = self._recommend(actions, pot_odds)
                status = "ready"
                confidence = "high"
                source = "deterministic_formula"
                explanation_key = self._explanation_key(recommendation.action)
                equity_threshold = recommendation.threshold
            except Exception:
                recommendation = self._fallback(actions, observation, pot_odds)
                status = "degraded"
                confidence = "limited"
                source = "safe_legal_fallback"
                explanation_key = "advisor.degraded.safe_legal_action"
                equity_threshold = pot_odds if recommendation.action is SimulatorActionV1.CALL else None
        elapsed_microseconds = (perf_counter_ns() - started) // 1_000
        return FormulaAdvisorResultV1(
            pot=observation.pot,
            hero_stack=hero_stack,
            call_cost=call_cost,
            pot_after_call=pot_after_call,
            pot_odds=pot_odds,
            pot_odds_basis=pot_odds_basis,
            effective_stack=effective_stack,
            spr=spr,
            spr_basis=spr_basis,
            legal_action_bounds=bounds,
            recommended_action=recommendation,
            recommendation_unavailable_reason="no_legal_actions" if not actions else None,
            status=status,
            confidence=confidence,
            equity_threshold=equity_threshold,
            explanation_key=explanation_key,
            limitations=limitations,
            decision=AdvisorDecisionIdentityV1(
                fingerprint=fingerprint,
                hand_id=observation.hand_id,
                sequence=observation.sequence,
                street=observation.street,
            ),
            inputs=FormulaAdvisorInputsV1(
                hand_id=observation.hand_id,
                sequence=observation.sequence,
                observer_seat=observation.observer_seat,
                street=observation.street,
                legal_actions_count=len(actions),
            ),
            assumptions=(
                "current pot and stacks are the supplied ObservationV1 decision point",
                "effective stack is the minimum remaining stack among active seats",
                "SPR uses the current pre-action pot and is undefined when that pot is zero",
                "recommendations are always one of the authoritative legal actions and do not use solver output or opponent private cards",
            ),
            source=source,
            latency=FormulaLatencyV1(elapsed_microseconds=elapsed_microseconds),
        )

    def _bound(
        self, action: LegalActionV1, observation: ObservationV1, hero_stack: int
    ) -> LegalActionBoundV1:
        maximum = action.max_amount
        if action.amount_semantics is AmountSemanticsV1.TO:
            all_in_amount = observation.street_commitments[observation.observer_seat] + hero_stack
        else:
            all_in_amount = hero_stack
        return LegalActionBoundV1(
            action=action.action,
            amount_semantics=action.amount_semantics,
            minimum=action.min_amount,
            maximum=maximum,
            all_in_endpoint=maximum == all_in_amount if maximum is not None else False,
        )

    def _recommend(
        self, actions: tuple[LegalActionV1, ...], pot_odds: Decimal
    ) -> FormulaRecommendationV1:
        kinds = {action.action for action in actions}
        limitations = "Not a solver, GTO, equity, range, EV, or opponent-truth conclusion."
        if SimulatorActionV1.CHECK in kinds:
            return FormulaRecommendationV1(
                action=SimulatorActionV1.CHECK,
                amount_semantics=AmountSemanticsV1.NONE,
                reason="check is legal and requires no additional chips",
                limitations=limitations,
            )
        if SimulatorActionV1.CALL in kinds and pot_odds <= self._call_pot_odds_threshold:
            call = next(item for item in actions if item.action is SimulatorActionV1.CALL)
            return FormulaRecommendationV1(
                action=SimulatorActionV1.CALL,
                amount_semantics=AmountSemanticsV1.COST,
                amount=call.min_amount,
                threshold=self._call_pot_odds_threshold,
                reason="call is legal and its pot-odds ratio is at or below the explicit heuristic threshold",
                limitations=limitations,
            )
        raise ValueError("formula_shape_not_supported")

    def _fallback(
        self, actions: tuple[LegalActionV1, ...], observation: ObservationV1, pot_odds: Decimal
    ) -> FormulaRecommendationV1:
        """Choose a legal, public-information-only L0 action after formula failure."""

        by_action = {item.action: item for item in actions}
        limitations = "Safe degraded fallback; no Solver, opponent private cards, terminal reveal, or future events are used."
        if SimulatorActionV1.CHECK in by_action:
            action = by_action[SimulatorActionV1.CHECK]
        elif SimulatorActionV1.CALL in by_action and self._hero_signal(observation) >= pot_odds:
            action = by_action[SimulatorActionV1.CALL]
        elif SimulatorActionV1.FOLD in by_action:
            action = by_action[SimulatorActionV1.FOLD]
        else:
            action = next(iter(actions))
        return FormulaRecommendationV1(
            action=action.action,
            amount_semantics=action.amount_semantics,
            amount=action.min_amount,
            threshold=pot_odds if action.action is SimulatorActionV1.CALL else None,
            reason="a safe legal fallback was selected from public decision facts",
            limitations=limitations,
        )

    @staticmethod
    def _hero_signal(observation: ObservationV1) -> Decimal:
        """Cheap, deterministic hand-strength signal from Hero/board only."""

        ranks = "23456789TJQKA"
        hero_ranks = [ranks.index(card[0]) + 2 for card in observation.own_hole_cards]
        board_ranks = [ranks.index(card[0]) + 2 for card in observation.board]
        paired = any(rank in board_ranks for rank in hero_ranks) or hero_ranks[0] == hero_ranks[1]
        high_card = Decimal(max(hero_ranks) - 2) / Decimal(24)
        position_bonus = Decimal("0.05") if observation.observer_seat == observation.button_seat else Decimal("0")
        return min(Decimal("0.70"), high_card + (Decimal("0.20") if paired else Decimal("0")) + position_bonus)

    @staticmethod
    def _explanation_key(action: SimulatorActionV1) -> str:
        return f"advisor.formula.{action.value}"

    @staticmethod
    def _fingerprint(observation: ObservationV1, actions: tuple[LegalActionV1, ...]) -> str:
        safe = {
            "handId": observation.hand_id, "sequence": observation.sequence,
            "observerSeat": observation.observer_seat, "street": observation.street.value,
            "heroCards": observation.own_hole_cards, "board": observation.board,
            "pot": observation.pot, "stacks": observation.stacks,
            "commitments": observation.street_commitments, "activeSeats": observation.active_seats,
            "legalActions": [item.to_dict() for item in actions],
        }
        return hashlib.sha256(repr(safe).encode("utf-8")).hexdigest()


class FormulaAdvisorFactory:
    """Small construction seam for future API/service wiring."""

    def create(self) -> FormulaAdvisor:
        return FormulaAdvisor()
