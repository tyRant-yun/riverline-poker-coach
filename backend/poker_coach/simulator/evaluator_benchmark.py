"""Offline evaluator differential and latency harness.

The optional ``phevaluator`` import is deliberately isolated here. Importing
the simulator package never requires the candidate dependency.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version as package_version
from typing import Any, Protocol, Sequence

from poker_coach.analysis.cards import (
    _best_hand_key_bruteforce,
    _best_hand_key_cached,
    best_hand_key,
    deck,
)


Hand = tuple[str, ...]


class EvaluatorBackend(Protocol):
    name: str
    version: str
    license: str

    def evaluate(self, cards: Hand) -> Any: ...

    def compare(self, left: Hand, right: Hand) -> int: ...


class CurrentEvaluatorBackend:
    name = "riverline-current"
    version = "analysis-cards-v1"
    license = "AGPL-3.0-or-later"

    def evaluate(self, cards: Hand):
        return best_hand_key(cards)

    def compare(self, left: Hand, right: Hand) -> int:
        left_key = self.evaluate(left)
        right_key = self.evaluate(right)
        return (left_key > right_key) - (left_key < right_key)

    def prepare_round(self) -> None:
        _best_hand_key_cached.cache_clear()


class PHEvaluatorBackend:
    """Optional adapter for HenryRLee/PokerHandEvaluator's Python package."""

    name = "phevaluator"
    license = "Apache-2.0"

    def __init__(self):
        from phevaluator import evaluate_cards

        self._evaluate_cards = evaluate_cards
        self.version = package_version("phevaluator")

    def evaluate(self, cards: Hand) -> int:
        if len(cards) not in (5, 6, 7):
            raise ValueError("PH Evaluator accepts 5, 6, or 7 cards")
        return int(self._evaluate_cards(*cards))

    def compare(self, left: Hand, right: Hand) -> int:
        # PH Evaluator assigns smaller ranks to stronger hands.
        left_rank = self.evaluate(left)
        right_rank = self.evaluate(right)
        return (left_rank < right_rank) - (left_rank > right_rank)


@dataclass(frozen=True)
class OracleResult:
    sample_count: int
    mismatch_count: int
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class DifferentialResult:
    comparison_count: int
    mismatch_count: int
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkResult:
    evaluation_count: int
    rounds: int
    p50_ns_per_evaluation: float
    p95_ns_per_evaluation: float
    evaluations_per_second: float


@dataclass(frozen=True)
class CurrentAssessment:
    name: str
    version: str
    oracle_sample_count: int
    oracle_mismatch_count: int
    oracle_mismatches: tuple[str, ...]
    benchmark: BenchmarkResult


@dataclass(frozen=True)
class CandidateAssessment:
    status: str
    name: str
    version: str | None
    declared_license: str | None
    unavailable_reason: str | None
    differential: DifferentialResult | None
    benchmark: BenchmarkResult | None
    speedup_p50: float | None


@dataclass(frozen=True)
class AdoptionGate:
    accuracy_passed: bool
    latency_passed: bool
    packaging_passed: bool
    license_passed: bool
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvaluatorSpikeReport:
    seed: int
    samples_per_size: int
    current: CurrentAssessment
    candidate: CandidateAssessment
    adoption_gate: AdoptionGate

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_hands(*, samples_per_size: int, seed: int) -> tuple[Hand, ...]:
    if samples_per_size <= 0:
        raise ValueError("samples_per_size must be positive")
    rng = random.Random(seed)
    full_deck = deck()
    return tuple(
        tuple(rng.sample(full_deck, size))
        for size in (5, 6, 7)
        for _ in range(samples_per_size)
    )


def oracle_compare_current(hands: Sequence[Hand]) -> OracleResult:
    mismatches: list[str] = []
    mismatch_count = 0
    for cards in hands:
        actual = best_hand_key(cards)
        expected = _best_hand_key_bruteforce(cards)
        if actual != expected:
            mismatch_count += 1
            if len(mismatches) < 50:
                mismatches.append(f"{','.join(cards)}: current={actual}, oracle={expected}")
    return OracleResult(len(hands), mismatch_count, tuple(mismatches))


def differential_compare(
    reference: EvaluatorBackend,
    candidate: EvaluatorBackend,
    hands: Sequence[Hand],
) -> DifferentialResult:
    comparisons: list[tuple[Hand, Hand]] = [(hand, hand) for hand in hands]
    for size in (5, 6, 7):
        same_size = [hand for hand in hands if len(hand) == size]
        comparisons.extend(zip(same_size[::2], same_size[1::2]))
    mismatch_count = 0
    mismatches: list[str] = []
    for left, right in comparisons:
        expected = reference.compare(left, right)
        actual = candidate.compare(left, right)
        if actual != expected:
            mismatch_count += 1
            if len(mismatches) < 50:
                mismatches.append(
                    f"{','.join(left)} vs {','.join(right)}: "
                    f"reference={expected}, candidate={actual}"
                )
    return DifferentialResult(len(comparisons), mismatch_count, tuple(mismatches))


def benchmark_backend(
    backend: EvaluatorBackend,
    hands: Sequence[Hand],
    *,
    rounds: int,
) -> BenchmarkResult:
    if rounds <= 0:
        raise ValueError("benchmark rounds must be positive")
    if not hands:
        raise ValueError("benchmark requires at least one hand")
    ns_per_evaluation: list[float] = []
    total_elapsed_ns = 0
    for _ in range(rounds):
        prepare = getattr(backend, "prepare_round", None)
        if prepare is not None:
            prepare()
        started = time.perf_counter_ns()
        for hand in hands:
            backend.evaluate(hand)
        elapsed = max(1, time.perf_counter_ns() - started)
        total_elapsed_ns += elapsed
        ns_per_evaluation.append(elapsed / len(hands))
    p50 = float(statistics.median(ns_per_evaluation))
    p95 = float(_percentile(ns_per_evaluation, 0.95))
    total_evaluations = len(hands) * rounds
    evaluations_per_second = total_evaluations / (total_elapsed_ns / 1_000_000_000)
    return BenchmarkResult(
        evaluation_count=total_evaluations,
        rounds=rounds,
        p50_ns_per_evaluation=p50,
        p95_ns_per_evaluation=p95,
        evaluations_per_second=evaluations_per_second,
    )


def run_evaluator_spike(
    *,
    samples_per_size: int = 1_000,
    benchmark_rounds: int = 5,
    seed: int = 20260812,
    candidate: EvaluatorBackend | None = None,
    auto_detect_candidate: bool = True,
    candidate_packaging_verified: bool = False,
    candidate_license_verified: bool = False,
    minimum_speedup: float = 2.0,
) -> EvaluatorSpikeReport:
    hands = generate_hands(samples_per_size=samples_per_size, seed=seed)
    current_backend = CurrentEvaluatorBackend()
    oracle = oracle_compare_current(hands)
    current_benchmark = benchmark_backend(
        current_backend, hands, rounds=benchmark_rounds
    )
    unavailable_reason = None
    if candidate is None and auto_detect_candidate:
        try:
            candidate = PHEvaluatorBackend()
        except (ImportError, ModuleNotFoundError) as exc:
            unavailable_reason = f"{type(exc).__name__}: {exc}"

    current = CurrentAssessment(
        name=current_backend.name,
        version=current_backend.version,
        oracle_sample_count=oracle.sample_count,
        oracle_mismatch_count=oracle.mismatch_count,
        oracle_mismatches=oracle.mismatches,
        benchmark=current_benchmark,
    )
    reasons: list[str] = []
    if candidate is None:
        candidate_assessment = CandidateAssessment(
            status="unavailable",
            name="phevaluator",
            version=None,
            declared_license="Apache-2.0",
            unavailable_reason=unavailable_reason or "auto detection disabled",
            differential=None,
            benchmark=None,
            speedup_p50=None,
        )
        accuracy_passed = latency_passed = False
        reasons.append("candidate unavailable")
    else:
        differential = differential_compare(current_backend, candidate, hands)
        candidate_benchmark = benchmark_backend(
            candidate, hands, rounds=benchmark_rounds
        )
        speedup = (
            current_benchmark.p50_ns_per_evaluation
            / candidate_benchmark.p50_ns_per_evaluation
        )
        accuracy_passed = differential.mismatch_count == 0
        latency_passed = speedup >= minimum_speedup
        candidate_assessment = CandidateAssessment(
            status="available",
            name=candidate.name,
            version=candidate.version,
            declared_license=candidate.license,
            unavailable_reason=None,
            differential=differential,
            benchmark=candidate_benchmark,
            speedup_p50=speedup,
        )
        if not accuracy_passed:
            reasons.append("differential mismatches detected")
        if not latency_passed:
            reasons.append(f"p50 speedup is below {minimum_speedup:.1f}x")
    if oracle.mismatch_count:
        accuracy_passed = False
        reasons.append("current evaluator disagrees with independent oracle")
    if not candidate_packaging_verified:
        reasons.append("candidate packaging not verified on supported runtimes")
    if not candidate_license_verified:
        reasons.append("candidate distribution license metadata not verified locally")
    gate_passed = all(
        (
            accuracy_passed,
            latency_passed,
            candidate_packaging_verified,
            candidate_license_verified,
        )
    )
    gate = AdoptionGate(
        accuracy_passed=accuracy_passed,
        latency_passed=latency_passed,
        packaging_passed=candidate_packaging_verified,
        license_passed=candidate_license_verified,
        passed=gate_passed,
        reasons=tuple(reasons),
    )
    return EvaluatorSpikeReport(
        seed=seed,
        samples_per_size=samples_per_size,
        current=current,
        candidate=candidate_assessment,
        adoption_gate=gate,
    )


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-size", type=int, default=1_000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args(argv)
    report = run_evaluator_spike(
        samples_per_size=args.samples_per_size,
        benchmark_rounds=args.rounds,
        seed=args.seed,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a documented CLI
    raise SystemExit(main())
