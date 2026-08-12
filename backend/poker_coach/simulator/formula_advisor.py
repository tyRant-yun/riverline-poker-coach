"""Fast, read-only L0 poker formula advice at the simulator boundary.

This service deliberately reports only deterministic chip math and legal-action
facts.  Its optional hint is labelled heuristic; it is never a solver, GTO,
equity, range, EV, or opponent-information claim.
"""

from __future__ import annotations

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
    kind: Literal["heuristic"] = "heuristic"
    threshold: Decimal | None = Field(default=None, ge=0, le=1)
    reason: str
    limitations: str


class FormulaLatencyV1(_FormulaContractV1):
    elapsed_microseconds: int = Field(ge=0)
    measured_by: Literal["service_monotonic_clock"] = "service_monotonic_clock"


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
    inputs: FormulaAdvisorInputsV1
    assumptions: tuple[str, ...]
    source: Literal["deterministic_formula"] = "deterministic_formula"
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
        recommendation, unavailable_reason = self._recommend(actions, pot_odds)
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
            recommendation_unavailable_reason=unavailable_reason,
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
                "recommendations are optional heuristics, not solver, GTO, equity, range, EV, or opponent-truth claims",
            ),
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
    ) -> tuple[FormulaRecommendationV1 | None, str | None]:
        kinds = {action.action for action in actions}
        limitations = "Not a solver, GTO, equity, range, EV, or opponent-truth conclusion."
        if not actions:
            return None, "no_legal_actions"
        if SimulatorActionV1.CHECK in kinds:
            return (
                FormulaRecommendationV1(
                    action=SimulatorActionV1.CHECK,
                    reason="check is legal and requires no additional chips",
                    limitations=limitations,
                ),
                None,
            )
        if SimulatorActionV1.CALL in kinds and pot_odds <= self._call_pot_odds_threshold:
            return (
                FormulaRecommendationV1(
                    action=SimulatorActionV1.CALL,
                    threshold=self._call_pot_odds_threshold,
                    reason="call is legal and its pot-odds ratio is at or below the explicit heuristic threshold",
                    limitations=limitations,
                ),
                None,
            )
        return None, "no_check_or_low_cost_call_heuristic"


class FormulaAdvisorFactory:
    """Small construction seam for future API/service wiring."""

    def create(self) -> FormulaAdvisor:
        return FormulaAdvisor()
