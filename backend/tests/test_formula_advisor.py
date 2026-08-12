"""Public seam tests for the deterministic, read-only L0 Formula Advisor."""

from __future__ import annotations

from decimal import Decimal
from time import perf_counter_ns

from poker_coach.simulator import (
    FormulaAdvisor,
    FormulaAdvisorFactory,
    LegalActionV1,
    ObservationV1,
)


def _observation(*, pot: int = 300, hero_stack: int = 900, street: str = "flop") -> ObservationV1:
    return ObservationV1(
        handId="formula-hand",
        sequence=7,
        observerSeat=0,
        tableSize=2,
        buttonSeat=0,
        street=street,
        ownHoleCards=("As", "Kd"),
        board=("7c", "6d", "2h") if street != "preflop" else (),
        pot=pot,
        stacks={0: hero_stack, 1: 750},
        streetCommitments={0: 0, 1: 0},
        activeSeats=(0, 1),
        legalActions=(LegalActionV1(action="check", amountSemantics="none"),),
    )


def test_formula_advisor_reports_auditable_postflop_math_and_legal_bounds():
    observation = _observation()
    actions = (
        LegalActionV1(action="fold", amountSemantics="none"),
        LegalActionV1(action="call", amountSemantics="cost", minAmount=100, maxAmount=100),
        LegalActionV1(action="raise", amountSemantics="to", minAmount=300, maxAmount=900),
    )

    result = FormulaAdvisor().evaluate(observation, legal_actions=actions)

    assert result.schema_version == 1
    assert result.pot == 300
    assert result.hero_stack == 900
    assert result.call_cost == 100
    assert result.pot_after_call == 400
    assert result.pot_odds == Decimal("0.25")
    assert result.pot_odds_basis == "call_cost_over_pot_after_call"
    assert result.effective_stack == 750
    assert result.spr == Decimal("2.5")
    assert result.spr_basis == "effective_stack_over_current_pot_before_action"
    assert [(bound.action.value, bound.amount_semantics.value, bound.minimum, bound.maximum, bound.all_in_endpoint) for bound in result.legal_action_bounds] == [
        ("fold", "none", None, None, False),
        ("call", "cost", 100, 100, False),
        ("raise", "to", 300, 900, True),
    ]
    assert result.recommended_action is not None
    assert result.recommended_action.action.value == "call"
    assert result.recommended_action.kind == "heuristic"
    assert result.recommended_action.threshold == Decimal("0.25")
    assert "solver" in result.recommended_action.limitations
    assert result.inputs.hand_id == "formula-hand"
    assert result.source == "deterministic_formula"
    assert result.version == "formula-advisor/v1"
    assert result.latency.measured_by == "service_monotonic_clock"


def test_formula_advisor_makes_no_cost_and_zero_pot_boundaries_explicit():
    result = FormulaAdvisor().evaluate(_observation(pot=0, street="preflop"))

    assert result.call_cost == 0
    assert result.pot_odds == Decimal("0")
    assert result.pot_odds_basis == "no_call_cost"
    assert result.spr is None
    assert result.spr_basis == "undefined_zero_pot"
    assert result.recommended_action is not None
    assert result.recommended_action.action.value == "check"
    assert result.recommended_action.kind == "heuristic"


def test_formula_advisor_preserves_bet_by_and_short_stack_all_in_endpoints():
    observation = _observation(hero_stack=120)
    actions = (
        LegalActionV1(action="fold", amountSemantics="none"),
        LegalActionV1(action="bet", amountSemantics="by", minAmount=50, maxAmount=120),
    )

    result = FormulaAdvisor().evaluate(observation, legal_actions=actions)

    assert result.hero_stack == 120
    assert result.effective_stack == 120
    assert result.spr == Decimal("0.4")
    assert [(bound.action.value, bound.amount_semantics.value, bound.minimum, bound.maximum, bound.all_in_endpoint) for bound in result.legal_action_bounds] == [
        ("fold", "none", None, None, False),
        ("bet", "by", 50, 120, True),
    ]
    assert result.recommended_action is None
    assert result.recommendation_unavailable_reason == "no_check_or_low_cost_call_heuristic"


def test_formula_advisor_returns_structured_unavailable_for_no_actionable_input():
    result = FormulaAdvisor().evaluate(_observation(), legal_actions=())

    assert result.legal_action_bounds == ()
    assert result.recommended_action is None
    assert result.recommendation_unavailable_reason == "no_legal_actions"


def test_formula_advisor_factory_and_results_are_deterministic_and_fast():
    advisor = FormulaAdvisorFactory().create()
    observation = _observation()
    first = advisor.evaluate(observation)
    second = advisor.evaluate(observation)

    assert first.model_dump(exclude={"latency"}) == second.model_dump(exclude={"latency"})
    samples = []
    for _ in range(200):
        started = perf_counter_ns()
        advisor.evaluate(observation)
        samples.append(perf_counter_ns() - started)
    p95_ns = sorted(samples)[int(len(samples) * 0.95) - 1]
    assert p95_ns < 10_000_000
