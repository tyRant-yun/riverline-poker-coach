"""Public contract tests for the bounded, read-only Fast EV Solver L1."""

from __future__ import annotations

from poker_coach.simulator import FastSolver, LegalActionV1, ObservationV1


def _observation(*, board: tuple[str, ...] = ("7c", "6d", "2h")) -> ObservationV1:
    return ObservationV1(
        handId="solver-hand", sequence=8, observerSeat=0, tableSize=3, buttonSeat=0,
        street="flop" if board else "preflop", ownHoleCards=("As", "Kd"), board=board,
        pot=300, stacks={0: 900, 1: 750, 2: 600}, streetCommitments={0: 0, 1: 0, 2: 0},
        activeSeats=(0, 1, 2), legalActions=(
            LegalActionV1(action="fold", amountSemantics="none"),
            LegalActionV1(action="call", amountSemantics="cost", minAmount=100, maxAmount=100),
            LegalActionV1(action="raise", amountSemantics="to", minAmount=300, maxAmount=900),
        ),
    )


def test_fast_solver_is_seeded_private_and_only_scores_legal_actions():
    solver = FastSolver(iteration_cap=80, clock=lambda: 0)

    first = solver.solve(_observation(), decision_fingerprint="decision-a", seed=7)
    second = solver.solve(_observation(), decision_fingerprint="decision-a", seed=7)

    assert first.status == "ready"
    assert first.to_dict() == second.to_dict()
    assert {candidate.action.value for candidate in first.candidates} == {"fold", "call", "raise"}
    assert first.recommended_action is not None
    assert first.recommended_action.action.value in {"fold", "call", "raise"}
    assert first.iterations == 80
    assert first.equity is not None
    assert "holeCards" not in first.to_json()
    assert "opponent" in " ".join(first.limitations).lower()
    assert first.source == "monte_carlo_uniform_opponents"
    assert first.version == "fast-ev-solver/v1"


def test_fast_solver_declines_non_decisions_without_sampling():
    result = FastSolver().solve(_observation(), decision_fingerprint="terminal", is_hero_decision=False)

    assert result.status == "not_ready"
    assert result.iterations == 0
    assert result.candidates == ()
    assert result.recommended_action is None


def test_fast_solver_samples_52_card_runouts_without_known_card_overlap():
    sample = FastSolver(iteration_cap=1).sample_trial(_observation(), seed=13)

    assert len(sample) == len(set(sample))
    assert {"As", "Kd", "7c", "6d", "2h"}.issubset(sample)


def test_fast_solver_handles_preflop_multiway_sampling_and_injected_budget_fallback():
    preflop = _observation(board=())
    assert len(FastSolver(iteration_cap=1).sample_trial(preflop, seed=17)) == 11

    ticks = iter((0.0, 0.0, 0.2, 0.2))
    partial = FastSolver(iteration_cap=80, clock=lambda: next(ticks)).solve(
        _observation(), decision_fingerprint="budget", seed=5
    )
    assert partial.status == "degraded"
    assert partial.iterations == 1

    exhausted_ticks = iter((0.0, 0.2, 0.2))
    unavailable = FastSolver(clock=lambda: next(exhausted_ticks)).solve(
        _observation(), decision_fingerprint="budget-zero", seed=5
    )
    assert unavailable.status == "unavailable"
    assert unavailable.unavailable_reason == "solver_budget_exhausted"
