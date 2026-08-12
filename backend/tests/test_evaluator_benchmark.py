"""Reproducible evaluator differential and benchmark spike tests."""

from __future__ import annotations

from poker_coach.analysis.cards import best_hand_key
from poker_coach.simulator.evaluator_benchmark import (
    CurrentEvaluatorBackend,
    differential_compare,
    generate_hands,
    oracle_compare_current,
    run_evaluator_spike,
)


class MirrorBackend:
    name = "mirror"
    version = "test"
    license = "test-only"

    def evaluate(self, cards):
        return best_hand_key(cards)

    def compare(self, left, right):
        left_key = self.evaluate(left)
        right_key = self.evaluate(right)
        return (left_key > right_key) - (left_key < right_key)


class ReversedBackend(MirrorBackend):
    name = "reversed"

    def compare(self, left, right):
        return -super().compare(left, right)


def test_fixed_seed_hand_generation_and_current_oracle_are_reproducible():
    first = generate_hands(samples_per_size=40, seed=20260812)
    second = generate_hands(samples_per_size=40, seed=20260812)

    assert first == second
    assert {len(hand) for hand in first} == {5, 6, 7}
    assert len(first) == 120
    assert oracle_compare_current(first).mismatch_count == 0


def test_current_evaluator_treats_two_trip_ranks_as_a_full_house():
    cards = ("Js", "Kc", "Ks", "Jd", "4d", "Jc", "Kd")

    assert best_hand_key(cards) == (6, (13, 11))


def test_differential_harness_detects_matching_and_inverted_backends():
    hands = generate_hands(samples_per_size=30, seed=20260812)
    current = CurrentEvaluatorBackend()

    matching = differential_compare(current, MirrorBackend(), hands)
    inverted = differential_compare(current, ReversedBackend(), hands)

    assert matching.comparison_count > 0
    assert matching.mismatch_count == 0
    assert inverted.mismatch_count > 0


def test_spike_report_is_honest_when_phevaluator_is_not_installed():
    report = run_evaluator_spike(
        samples_per_size=20,
        benchmark_rounds=2,
        seed=20260812,
        candidate=None,
        auto_detect_candidate=False,
    )

    assert report.current.oracle_mismatch_count == 0
    assert report.current.oracle_mismatches == ()
    assert report.current.benchmark.p50_ns_per_evaluation > 0
    assert report.candidate.status == "unavailable"
    assert report.candidate.differential is None
    assert report.adoption_gate.passed is False
    assert "candidate unavailable" in report.adoption_gate.reasons


def test_injected_candidate_runs_differential_benchmark_but_not_packaging_gate():
    report = run_evaluator_spike(
        samples_per_size=20,
        benchmark_rounds=2,
        seed=20260812,
        candidate=MirrorBackend(),
        auto_detect_candidate=False,
    )

    assert report.candidate.status == "available"
    assert report.candidate.differential.mismatch_count == 0
    assert report.candidate.benchmark.p50_ns_per_evaluation > 0
    assert report.adoption_gate.accuracy_passed is True
    assert report.adoption_gate.packaging_passed is False
    assert report.adoption_gate.passed is False
