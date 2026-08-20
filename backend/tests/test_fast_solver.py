"""Focused contract and truthfulness gates for Fast Solver L1.5."""

from __future__ import annotations

import statistics
import time
from collections import Counter
from decimal import Decimal
from itertools import combinations
from types import SimpleNamespace

from poker_coach.simulator import fast_solver as fast_solver_module
from poker_coach.analysis.cards import _best_hand_key_bruteforce, deck
from poker_coach.simulator import FastSolver, LegalActionV1, ObservationV1


def _observation(
    *,
    board: tuple[str, ...] = ("7c", "6d", "2h"),
    active_seats: tuple[int, ...] = (0, 1, 2),
) -> ObservationV1:
    return ObservationV1(
        handId="solver-hand", sequence=8, observerSeat=0,
        tableSize=max(active_seats) + 1, buttonSeat=0,
        street="river" if len(board) == 5 else "flop" if board else "preflop",
        ownHoleCards=("As", "Kd"), board=board, pot=300,
        stacks={seat: 900 - seat * 75 for seat in active_seats},
        streetCommitments={seat: (50 if seat == 0 else 0) for seat in active_seats},
        activeSeats=active_seats,
        legalActions=(
            LegalActionV1(action="fold", amountSemantics="none"),
            LegalActionV1(action="call", amountSemantics="cost", minAmount=100, maxAmount=100),
            LegalActionV1(action="raise", amountSemantics="to", minAmount=300, maxAmount=900),
        ),
    )


def _belief(seat: int, combos: dict[str, str], *, available: bool = True):
    weighted = {combo: SimpleNamespace(probability=Decimal(weight)) for combo, weight in combos.items()}
    return SimpleNamespace(
        seat_id=seat, available=available, inactive=False,
        current=SimpleNamespace(combos=weighted, snapshot_id=f"seat-{seat}"),
        provenance=SimpleNamespace(artifact_fingerprint="range-v2-fixture", version="heuristic_likelihood_v2"),
        opponent_hole_cards=("2s", "2h"),
    )


def _ranges(*beliefs):
    return {belief.seat_id: belief for belief in beliefs}


def _wide_ranges(seats: tuple[int, ...]):
    cards = deck(())
    combos = {first + second: "1" for first, second in combinations(cards, 2)}
    return _ranges(*(_belief(seat, combos) for seat in seats))


def test_range_only_sampling_applies_blockers_and_multiway_card_removal():
    observation = _observation()
    ranges = _ranges(
        _belief(1, {"AsAc": "0.9", "QcQd": "0.1"}),
        _belief(2, {"QcQs": "0.9", "JhJd": "0.1"}),
    )
    sample = FastSolver(iteration_cap=1).sample_trial(observation, seed=13, range_beliefs=ranges)
    assert len(sample) == len(set(sample))
    assert {"As", "Kd", "7c", "6d", "2h", "Qc", "Qd", "Jh", "Jd"}.issubset(sample)


def test_joint_sampler_backtracks_from_dead_end_without_uniform_fallback():
    observation = _observation()
    ranges = _ranges(
        _belief(1, {"QcQd": "0.5", "JhJd": "0.5"}),
        _belief(2, {"QcQs": "1"}),
    )
    solver = FastSolver(iteration_cap=1, clock=lambda: 0)

    first = solver.solve(
        observation, decision_fingerprint="joint", seed=0, range_beliefs=ranges
    )
    second = solver.solve(
        observation, decision_fingerprint="joint", seed=0, range_beliefs=ranges
    )

    assert first.to_dict() == second.to_dict()
    assert first.status == "ready"
    assert first.source == "range_weighted_public_beliefs"
    assert first.range_status == "ready"

    unsupported = solver.solve(
        observation,
        decision_fingerprint="no-joint-support",
        seed=0,
        range_beliefs=_ranges(
            _belief(1, {"QcQd": "1"}),
            _belief(2, {"QcQs": "1"}),
        ),
    )
    assert unsupported.status == "degraded"
    assert unsupported.source == "monte_carlo_uniform_opponents"
    assert unsupported.range_status == "unavailable_fallback_uniform"


def test_sparse_joint_sampler_preserves_conditional_product_weights():
    observation = _observation()
    ranges = _ranges(
        _belief(1, {"QcQd": "0.99", "JhJd": "0.01"}),
        _belief(2, {"QcQs": "0.99", "TcTd": "0.01"}),
    )
    solver = FastSolver()
    observed: Counter[tuple[str, str]] = Counter()
    for seed in range(5000):
        sample = solver.sample_trial(observation, seed=seed, range_beliefs=ranges)
        observed[("".join(sample[5:7]), "".join(sample[7:9]))] += 1

    expected = {
        ("QcQd", "TcTd"): 0.0099 / 0.0199,
        ("JhJd", "QcQs"): 0.0099 / 0.0199,
        ("JhJd", "TcTd"): 0.0001 / 0.0199,
    }
    assert set(observed) == set(expected)
    observed_percentages = {
        assignment: observed[assignment] / 50 for assignment in expected
    }
    print(f"joint conditional observed percentages={observed_percentages}")
    for assignment, target in expected.items():
        assert abs(observed[assignment] / 5000 - target) < 0.03
    assert solver.sample_trial(
        observation, seed=137, range_beliefs=ranges
    ) == solver.sample_trial(observation, seed=137, range_beliefs=ranges)


def test_joint_exact_cap_never_returns_first_feasible_range_sample(monkeypatch):
    observation = _observation()
    ranges = _ranges(
        _belief(1, {"QcQd": "0.999999", "JhJd": "0.000001"}),
        _belief(2, {"QcQs": "0.999999", "TcTd": "0.000001"}),
    )
    monkeypatch.setattr(fast_solver_module, "_JOINT_ENUM_STATE_CAP", 0)

    result = FastSolver(iteration_cap=1, clock=lambda: 0).solve(
        observation, decision_fingerprint="joint-cap", seed=0,
        range_beliefs=ranges,
    )

    assert result.status == "unavailable"
    assert result.source == "range_weighted_public_beliefs"
    assert result.range_status == "ready"
    assert result.sample_count == 0
    assert result.unavailable_reason == "range_joint_enumeration_cap_exhausted"


def test_private_poison_does_not_change_range_aware_result():
    observation = _observation(active_seats=(0, 1))
    clean = _belief(1, {"QcQd": "1"})
    poisoned = _belief(1, {"QcQd": "1"})
    poisoned.opponent_hole_cards = ("Ac", "Ad")
    solver = FastSolver(iteration_cap=40, clock=lambda: 0)
    first = solver.solve(observation, decision_fingerprint="private", range_beliefs={1: clean})
    second = solver.solve(observation, decision_fingerprint="private", range_beliefs={1: poisoned})
    assert first.to_dict() == second.to_dict()
    assert "holeCards" not in first.to_json()


def test_all_product_sizings_are_legal_and_preserve_cost_by_to_semantics():
    observation = _observation(active_seats=(0, 1))
    result = FastSolver(iteration_cap=20, clock=lambda: 0).solve(
        observation, decision_fingerprint="sizings",
        range_beliefs=_ranges(_belief(1, {"QcQd": "1"})),
    )
    actual = [(item.action.value, item.amount_semantics.value, item.amount) for item in result.candidates]
    assert actual == [
        ("fold", "none", None), ("call", "cost", 100),
        ("raise", "to", 300), ("raise", "to", 600), ("raise", "to", 900),
    ]
    for candidate in result.candidates:
        legal = next(item for item in observation.legal_actions if item.action is candidate.action)
        assert legal.accepts(action=candidate.action, amount=candidate.amount)
    assert result.candidates[1].incremental_cost == 100
    assert [item.incremental_cost for item in result.candidates[2:]] == [250, 550, 850]

    bet_observation = observation.model_copy(update={
        "street_commitments": {0: 0, 1: 0},
        "legal_actions": (
            LegalActionV1(action="check", amountSemantics="none"),
            LegalActionV1(action="bet", amountSemantics="by", minAmount=200, maxAmount=700),
        ),
    })
    bet_result = FastSolver(iteration_cap=20, clock=lambda: 0).solve(
        bet_observation, decision_fingerprint="bet-sizings",
        range_beliefs=_ranges(_belief(1, {"QcQd": "1"})),
    )
    assert [(item.amount_semantics.value, item.amount, item.incremental_cost) for item in bet_result.candidates] == [
        ("none", None, 0), ("by", 200, 200), ("by", 450, 450), ("by", 700, 700)
    ]


def test_raise_to_continuation_uses_asymmetric_opponent_call_increment():
    observation = ObservationV1(
        handId="raise-to-ev", sequence=1, observerSeat=0, tableSize=2,
        buttonSeat=0, street="river", ownHoleCards=("As", "Ad"),
        board=("2c", "3d", "7h", "8s", "9c"), pot=300,
        stacks={0: 950, 1: 900}, streetCommitments={0: 50, 1: 100},
        activeSeats=(0, 1), legalActions=(
            LegalActionV1(
                action="raise", amountSemantics="to", minAmount=300, maxAmount=300
            ),
        ),
    )
    result = FastSolver(clock=lambda: 0).solve(
        observation, decision_fingerprint="raise-to-ev",
        range_beliefs=_ranges(_belief(1, {"KcKd": "1"})),
    )
    candidate = result.candidates[0]
    expected = (
        candidate.response_mix.fold * Decimal(300)
        + candidate.response_mix.call * Decimal(500)
        + candidate.response_mix.raise_ * Decimal(-250)
    )

    assert candidate.incremental_cost == 250
    assert candidate.opponent_call_total == 200
    assert candidate.call_continuation_pot == 750
    assert candidate.raise_response_assumption == "hero_folds_no_further_cost"
    assert candidate.approximate_ev_chips == expected


def test_response_mix_metrics_and_provenance_are_truthful_and_deterministic():
    solver = FastSolver(iteration_cap=60, clock=lambda: 0)
    ranges = _ranges(_belief(1, {"QcQd": "0.6", "JhJd": "0.4"}))
    first = solver.solve(_observation(active_seats=(0, 1)), decision_fingerprint="same", range_beliefs=ranges)
    second = solver.solve(_observation(active_seats=(0, 1)), decision_fingerprint="same", range_beliefs=ranges)
    assert first.to_dict() == second.to_dict()
    assert first.source == "range_weighted_public_beliefs"
    assert first.version == "fast-ev-solver/v1"
    assert first.model_version == "fast-ev-solver/v1.5"
    assert first.budget_tier == "standard"
    assert first.sample_count == first.iterations > 0
    assert first.effective_sample_size > 0
    assert first.confidence_interval_95 is not None
    for candidate in first.candidates:
        assert candidate.showdown_equity is not None
        assert candidate.response_mix.fold + candidate.response_mix.call + candidate.response_mix.raise_ == Decimal("1")
    disclosure = " ".join(first.limitations).lower()
    assert "heuristic" in disclosure and "gto" in disclosure and "profile" in disclosure


def test_response_mix_uses_blocker_conditioned_probability_mass_not_support_count():
    observation = _observation(active_seats=(0, 1)).model_copy(update={
        "street_commitments": {0: 0, 1: 0},
        "legal_actions": (
            LegalActionV1(action="bet", amountSemantics="by", minAmount=200, maxAmount=200),
        ),
    })
    solver = FastSolver(iteration_cap=20, clock=lambda: 0)
    diffuse = solver.solve(
        observation, decision_fingerprint="mass", seed=1,
        range_beliefs=_ranges(_belief(1, {"QcQd": "0.5", "JhJd": "0.5"})),
    ).candidates[0]
    concentrated = solver.solve(
        observation, decision_fingerprint="mass", seed=1,
        range_beliefs=_ranges(_belief(1, {"QcQd": "0.99", "JhJd": "0.01"})),
    ).candidates[0]
    blocker_conditioned = solver.solve(
        observation, decision_fingerprint="mass", seed=1,
        range_beliefs=_ranges(_belief(1, {
            "AsAc": "0.99", "QcQd": "0.005", "JhJd": "0.005"
        })),
    ).candidates[0]

    assert concentrated.response_mix != diffuse.response_mix
    assert concentrated.response_mix.fold < diffuse.response_mix.fold
    assert concentrated.response_mix.raise_ > diffuse.response_mix.raise_
    assert concentrated.approximate_ev_chips != diffuse.approximate_ev_chips
    assert blocker_conditioned.response_mix == diffuse.response_mix


def test_nested_budget_ci_width_does_not_increase():
    observation = _observation(active_seats=(0, 1))
    ranges = _ranges(_belief(1, {"QcQd": "0.5", "JhJd": "0.5"}))
    quick = FastSolver(iteration_cap=20, clock=lambda: 0).solve(
        observation, decision_fingerprint="nested", range_beliefs=ranges, budget_tier="quick")
    standard = FastSolver(iteration_cap=80, clock=lambda: 0).solve(
        observation, decision_fingerprint="nested", range_beliefs=ranges, budget_tier="standard")
    assert standard.sample_count >= quick.sample_count
    assert standard.confidence_interval_95.width <= quick.confidence_interval_95.width


def test_timeout_returns_partial_and_zero_samples_are_unavailable():
    ticks = iter((0.0, 0.0, 0.2, 0.2, 0.2))
    partial = FastSolver(iteration_cap=80, clock=lambda: next(ticks)).solve(
        _observation(), decision_fingerprint="budget", seed=5)
    assert partial.status == "degraded"
    assert partial.sample_count == 1
    exhausted_ticks = iter((0.0, 0.3, 0.3))
    unavailable = FastSolver(clock=lambda: next(exhausted_ticks)).solve(
        _observation(), decision_fingerprint="budget-zero", seed=5)
    assert unavailable.status == "unavailable"
    assert unavailable.sample_count == 0
    assert unavailable.unavailable_reason == "solver_budget_exhausted"


def test_cold_start_between_soft_and_hard_returns_one_truthful_sample():
    observation = _observation(active_seats=(0, 1, 2, 3, 4, 5))
    ranges = _wide_ranges((1, 2, 3, 4, 5))
    ticks = iter((0.0, 0.2, 0.31, 0.31))

    result = FastSolver(clock=lambda: next(ticks)).solve(
        observation,
        decision_fingerprint="cold-start",
        seed=5,
        range_beliefs=ranges,
    )

    assert result.status == "degraded"
    assert result.sample_count == 1
    assert result.source == "range_weighted_public_beliefs"
    assert result.range_status == "ready"
    assert result.unavailable_reason is None


def test_range_unavailable_honestly_falls_back_to_uniform_l1():
    result = FastSolver(iteration_cap=20, clock=lambda: 0).solve(
        _observation(active_seats=(0, 1)), decision_fingerprint="fallback",
        range_beliefs={1: _belief(1, {}, available=False)})
    assert result.status == "degraded"
    assert result.source == "monte_carlo_uniform_opponents"
    assert result.range_status == "unavailable_fallback_uniform"
    assert result.recommended_action is not None


def test_fixed_river_range_matches_bruteforce_oracle_below_one_percentage_point():
    observation = _observation(board=("7c", "6d", "2h", "3s", "4c"), active_seats=(0, 1))
    combos = {"QcQd": "0.25", "JhJd": "0.75"}
    result = FastSolver(clock=lambda: 0).solve(
        observation, decision_fingerprint="river-oracle",
        range_beliefs=_ranges(_belief(1, combos)))
    hero_key = _best_hand_key_bruteforce(observation.own_hole_cards + observation.board)
    oracle = Decimal("0")
    for combo, weight in combos.items():
        villain_key = _best_hand_key_bruteforce((combo[:2], combo[2:]) + observation.board)
        share = Decimal("1") if hero_key > villain_key else Decimal("0.5") if hero_key == villain_key else Decimal("0")
        oracle += Decimal(weight) * share
    assert result.equity is not None
    mae = abs(result.equity - oracle)
    print(f"river equity MAE={float(mae * 100):.6f}pp")
    assert mae < Decimal("0.01")
    assert result.confidence_interval_95.width == 0


def test_standard_latency_is_monotonic_and_below_truthful_gate():
    observation = _observation(active_seats=(0, 1, 2, 3, 4, 5))
    ranges = _wide_ranges((1, 2, 3, 4, 5))
    solver = FastSolver()
    timings = []
    for index in range(25):
        started = time.perf_counter()
        result = solver.solve(observation, decision_fingerprint=f"bench-{index}", range_beliefs=ranges)
        timings.append((time.perf_counter() - started) * 1000)
        assert result.sample_count > 0
    timings.sort()
    p50 = statistics.median(timings)
    p95 = timings[int(0.95 * (len(timings) - 1))]
    print(f"standard solver p50={p50:.3f}ms p95={p95:.3f}ms")
    assert p50 < 150
    assert p95 < 300


def test_fast_solver_declines_non_decisions_without_sampling():
    result = FastSolver().solve(_observation(), decision_fingerprint="terminal", is_hero_decision=False)
    assert result.status == "not_ready"
    assert result.sample_count == 0
    assert result.candidates == ()
    assert result.recommended_action is None
