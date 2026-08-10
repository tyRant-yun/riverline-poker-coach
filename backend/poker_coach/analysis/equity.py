"""Exact and sampled showdown equity with reproducible cancellation points."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from decimal import Decimal, localcontext
from itertools import combinations, product
from threading import Event
from typing import Iterable

from poker_coach.domain.models import AnalysisLevel, Card, EquityAlgorithm, RangeSpec

from .cards import best_hand_key, deck, sort_cards
from .models import (
    AnalysisCancelled,
    AnalysisTimeout,
    EquityResult,
    InvalidAnalysisInput,
    MultiwayEquityResult,
    WeightedCombo,
)
from .range_analysis import expand_range


# Retry budget for whole-tuple rejection sampling. Each attempt draws one
# weighted combo per seat, so 10k attempts is cheap; hitting the cap means
# the legal joint space is effectively empty (e.g. ranges that cannot be
# dealt non-overlapping).
_MAX_SAMPLING_ATTEMPTS = 10_000


@dataclass
class _Accumulator:
    weighted: bool = False
    hero_wins: int = 0
    villain_wins: int = 0
    ties: int = 0
    trials: int = 0
    hero_mass: Decimal = Decimal("0")
    villain_mass: Decimal = Decimal("0")
    tie_mass: Decimal = Decimal("0")
    total_mass: Decimal = Decimal("0")

    def add(self, hero_key, villain_key, weight: Decimal = Decimal("1")) -> None:
        self.trials += 1
        if hero_key > villain_key:
            self.hero_wins += 1
        elif villain_key > hero_key:
            self.villain_wins += 1
        else:
            self.ties += 1
        if not self.weighted:
            return
        self.total_mass += weight
        if hero_key > villain_key:
            self.hero_mass += weight
        elif villain_key > hero_key:
            self.villain_mass += weight
        else:
            self.tie_mass += weight


class _MultiwayAccumulator:
    """Per-seat win mass for N-player showdowns (ties split equally)."""

    def __init__(self, *, weighted: bool):
        self.weighted = weighted
        self.trials = 0
        self.total_mass = Decimal("0")
        self.tie_mass = Decimal("0")
        self.wins: dict[int, Decimal] = {}
        # Sum of squared per-trial shares, for the Monte Carlo variance of
        # the equity estimator under split ties: Var(X) = E[X^2] - E[X]^2,
        # where X is the per-trial share (0, 1, or 1/k on a k-way tie).
        self.squared: dict[int, Decimal] = {}

    def add(
        self,
        keys: list[tuple[int, object]],
        weight: Decimal = Decimal("1"),
    ) -> None:
        self.trials += 1
        max_key = max(key for _, key in keys)
        winners = [seat for seat, key in keys if key == max_key]
        share = weight / len(winners)
        for seat in winners:
            self.wins[seat] = self.wins.get(seat, Decimal("0")) + share
            self.squared[seat] = self.squared.get(seat, Decimal("0")) + share * share
        if len(winners) > 1:
            self.tie_mass += weight
        if self.weighted:
            self.total_mass += weight


class EquityEngine:
    """Calculate showdown equity without mutating scenarios or rule state."""

    def __init__(self, *, max_exact_operations: int = 2_000_000):
        self.max_exact_operations = max_exact_operations

    def evaluate_hand_vs_hand(
        self,
        hero_hole_cards: tuple[Card, Card],
        villain_hole_cards: tuple[Card, Card],
        board: tuple[Card, ...] = (),
        *,
        algorithm: EquityAlgorithm = EquityAlgorithm.EXACT_ENUMERATION,
        trials: int = 10_000,
        random_seed: int | None = None,
        cancel_event: Event | None = None,
        timeout_seconds: float | None = None,
    ) -> EquityResult:
        known = self._validate_known_cards(hero_hole_cards, villain_hole_cards, board)
        remaining = deck(known)
        missing = 5 - len(board)
        if missing < 0:
            raise InvalidAnalysisInput("board cannot contain more than five cards")
        if algorithm is EquityAlgorithm.EXACT_ENUMERATION:
            runouts = math.comb(len(remaining), missing)
            self._ensure_workload(runouts)
            accumulator = _Accumulator()
            started_at = time.monotonic()
            for runout in _iter_runouts(remaining, missing):
                self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
                self._add_showdown(
                    accumulator,
                    hero_hole_cards,
                    villain_hole_cards,
                    board + tuple(runout),
                )
            return self._result(accumulator, algorithm, weighted=False)
        self._require_sampling(trials, random_seed)
        rng = random.Random(random_seed)
        accumulator = _Accumulator()
        started_at = time.monotonic()
        for _ in range(trials):
            self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
            runout = tuple(rng.sample(remaining, missing))
            self._add_showdown(
                accumulator,
                hero_hole_cards,
                villain_hole_cards,
                board + runout,
            )
        return self._result(
            accumulator,
            algorithm,
            random_seed=random_seed,
            weighted=False,
        )

    def evaluate_hand_vs_range(
        self,
        hero_hole_cards: tuple[Card, Card],
        villain_range: RangeSpec,
        board: tuple[Card, ...] = (),
        *,
        algorithm: EquityAlgorithm = EquityAlgorithm.EXACT_ENUMERATION,
        trials: int = 10_000,
        random_seed: int | None = None,
        cancel_event: Event | None = None,
        timeout_seconds: float | None = None,
    ) -> EquityResult:
        known = self._validate_cards(hero_hole_cards + tuple(board))
        combos = expand_range(villain_range, dead_cards=known)
        if not combos:
            raise InvalidAnalysisInput("villain range is empty after dead-card removal")
        if algorithm is EquityAlgorithm.EXACT_ENUMERATION:
            missing = 5 - len(board)
            operations = sum(math.comb(len(deck(known + combo.cards)), missing) for combo in combos)
            self._ensure_workload(operations)
            accumulator = _Accumulator(weighted=True)
            started_at = time.monotonic()
            for combo in combos:
                for runout in _iter_runouts(deck(known + combo.cards), missing):
                    self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
                    self._add_showdown(
                        accumulator,
                        hero_hole_cards,
                        combo.cards,
                        board + tuple(runout),
                        combo.weight,
                    )
            return self._result(accumulator, algorithm, weighted=True)
        self._require_sampling(trials, random_seed)
        rng = random.Random(random_seed)
        accumulator = _Accumulator(weighted=True)
        started_at = time.monotonic()
        for _ in range(trials):
            self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
            combo = _weighted_choice(rng, combos)
            runout = tuple(rng.sample(deck(known + combo.cards), 5 - len(board)))
            self._add_showdown(
                accumulator,
                hero_hole_cards,
                combo.cards,
                board + runout,
            )
        return self._result(
            accumulator,
            algorithm,
            random_seed=random_seed,
            weighted=True,
        )

    def evaluate_range_vs_range(
        self,
        hero_range: RangeSpec,
        villain_range: RangeSpec,
        board: tuple[Card, ...] = (),
        *,
        algorithm: EquityAlgorithm = EquityAlgorithm.EXACT_ENUMERATION,
        trials: int = 10_000,
        random_seed: int | None = None,
        cancel_event: Event | None = None,
        timeout_seconds: float | None = None,
    ) -> EquityResult:
        board = tuple(sort_cards(board))
        self._validate_cards(board)
        hero_combos = expand_range(hero_range, dead_cards=board)
        villain_combos = expand_range(villain_range, dead_cards=board)
        if not hero_combos or not villain_combos:
            raise InvalidAnalysisInput("one or both ranges are empty after dead-card removal")
        if algorithm is EquityAlgorithm.EXACT_ENUMERATION:
            operations = 0
            for hero in hero_combos:
                for villain in villain_combos:
                    if set(hero.cards).intersection(villain.cards):
                        continue
                    operations += math.comb(
                        len(deck(tuple(board) + hero.cards + villain.cards)),
                        5 - len(board),
                    )
            self._ensure_workload(operations)
            accumulator = _Accumulator(weighted=True)
            started_at = time.monotonic()
            for hero in hero_combos:
                for villain in villain_combos:
                    if set(hero.cards).intersection(villain.cards):
                        continue
                    weight = hero.weight * villain.weight
                    for runout in _iter_runouts(
                        deck(tuple(board) + hero.cards + villain.cards), 5 - len(board)
                    ):
                        self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
                        self._add_showdown(
                            accumulator,
                            hero.cards,
                            villain.cards,
                            board + tuple(runout),
                            weight,
                        )
            if accumulator.trials == 0:
                raise InvalidAnalysisInput("ranges contain no non-overlapping combo pair")
            return self._result(accumulator, algorithm, weighted=True)
        self._require_sampling(trials, random_seed)
        rng = random.Random(random_seed)
        accumulator = _Accumulator(weighted=True)
        started_at = time.monotonic()
        for _ in range(trials):
            self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
            hero, villain = self._sample_non_overlapping_pair(
                rng, hero_combos, villain_combos
            )
            runout = tuple(rng.sample(deck(tuple(board) + hero.cards + villain.cards), 5 - len(board)))
            self._add_showdown(
                accumulator,
                hero.cards,
                villain.cards,
                board + runout,
            )
        return self._result(
            accumulator,
            algorithm,
            random_seed=random_seed,
            weighted=True,
        )

    def evaluate_multiway(
        self,
        players: Iterable[tuple[int, tuple[Card, Card] | RangeSpec]],
        board: tuple[Card, ...] = (),
        *,
        algorithm: EquityAlgorithm = EquityAlgorithm.EXACT_ENUMERATION,
        trials: int = 10_000,
        random_seed: int | None = None,
        cancel_event: Event | None = None,
        timeout_seconds: float | None = None,
    ) -> MultiwayEquityResult:
        """N-player showdown equity keyed by seat.

        Each entry is ``(seat, hole_cards)`` or ``(seat, RangeSpec)``; a
        concrete hand is a single weight-one combo. Ties split the mass
        equally among the tied best hands.
        """
        board = tuple(sort_cards(board))
        self._validate_cards(board)
        normalized: list[tuple[int, tuple[WeightedCombo, ...], bool]] = []
        for seat, spec in players:
            if isinstance(spec, RangeSpec):
                combos = expand_range(spec, dead_cards=board)
                weighted = True
            else:
                combos = (
                    WeightedCombo(cards=tuple(sort_cards(spec)), weight=Decimal("1")),
                )
                weighted = False
            if not combos:
                raise InvalidAnalysisInput(
                    f"seat {seat} has no playable combos after dead-card removal"
                )
            for combo in combos:
                self._validate_cards(board + combo.cards)
            normalized.append((seat, combos, weighted))
        if len(normalized) < 2:
            raise InvalidAnalysisInput("multiway equity requires at least two players")
        any_weighted = any(weighted for _, _, weighted in normalized)
        combo_lists = [combos for _, combos, _ in normalized]

        def _trial_weight(combo_tuple: tuple[WeightedCombo, ...]) -> Decimal:
            if not any_weighted:
                return Decimal("1")
            return _prod_weights(combo_tuple)

        if algorithm is EquityAlgorithm.EXACT_ENUMERATION:
            operations = 0
            for combo_tuple in product(*combo_lists):
                cards = tuple(board)
                for combo in combo_tuple:
                    if set(cards).intersection(combo.cards):
                        break
                    cards = cards + combo.cards
                else:
                    operations += math.comb(len(deck(cards)), 5 - len(board))
            self._ensure_workload(operations)
            accumulator = _MultiwayAccumulator(weighted=any_weighted)
            started_at = time.monotonic()
            for combo_tuple in product(*combo_lists):
                cards = tuple(board)
                for combo in combo_tuple:
                    if set(cards).intersection(combo.cards):
                        break
                    cards = cards + combo.cards
                else:
                    weight = _trial_weight(combo_tuple)
                    for runout in _iter_runouts(deck(cards), 5 - len(board)):
                        self._checkpoint(
                            accumulator.trials, cancel_event, timeout_seconds, started_at
                        )
                        accumulator.add(
                            [
                                (seat, best_hand_key(combo.cards + board + tuple(runout)))
                                for (seat, _, _), combo in zip(normalized, combo_tuple)
                            ],
                            weight,
                        )
            return self._multiway_result(
                accumulator,
                algorithm,
                normalized,
                random_seed=random_seed,
                weighted=any_weighted,
            )
        self._require_sampling(trials, random_seed)
        rng = random.Random(random_seed)
        accumulator = _MultiwayAccumulator(weighted=any_weighted)
        started_at = time.monotonic()
        for _ in range(trials):
            self._checkpoint(accumulator.trials, cancel_event, timeout_seconds, started_at)
            sampled = self._sample_non_overlapping_multiway(rng, combo_lists, board)
            cards = tuple(board)
            for combo in sampled:
                cards = cards + combo.cards
            runout = tuple(rng.sample(deck(cards), 5 - len(board)))
            # Each accepted joint sample is drawn from the exact legal joint
            # distribution (weights acted once, inside the proposal), so every
            # trial contributes equal mass: re-weighting here would double-count
            # the combo weights and polarize the estimate.
            accumulator.add(
                [
                    (seat, best_hand_key(combo.cards + board + runout))
                    for (seat, _, _), combo in zip(normalized, sampled)
                ],
                Decimal("1"),
            )
        return self._multiway_result(
            accumulator,
            algorithm,
            normalized,
            random_seed=random_seed,
            weighted=any_weighted,
        )

    def _multiway_result(
        self,
        accumulator: _MultiwayAccumulator,
        algorithm: EquityAlgorithm,
        normalized: list[tuple[int, tuple[WeightedCombo, ...], bool]],
        *,
        random_seed: int | None,
        weighted: bool,
    ) -> MultiwayEquityResult:
        if accumulator.trials == 0 or (weighted and accumulator.total_mass == 0):
            raise InvalidAnalysisInput("equity calculation produced no trials")
        seats = [seat for seat, _, _ in normalized]
        with localcontext() as context:
            context.prec = 28
            total = accumulator.total_mass if weighted else Decimal(accumulator.trials)
            equities = {
                seat: accumulator.wins.get(seat, Decimal("0")) / total for seat in seats
            }
            tie_probability = accumulator.tie_mass / total
        standard_errors = None
        if algorithm is EquityAlgorithm.MONTE_CARLO:
            standard_errors = {}
            for seat, equity in equities.items():
                # Per-trial outcome is a share (0, 1, or 1/k under a k-way
                # split tie), so the estimator variance is E[X^2] - E[X]^2,
                # not the Bernoulli p(1-p) which assumes binary outcomes and
                # would overstate the error whenever ties are split.
                mean_square = accumulator.squared.get(seat, Decimal("0")) / total
                variance = max(0.0, float(mean_square) - float(equity) ** 2)
                standard_errors[seat] = Decimal(
                    str(math.sqrt(variance / accumulator.trials))
                )
        return MultiwayEquityResult(
            algorithm=algorithm,
            source_level=(
                AnalysisLevel.ENUMERATED
                if algorithm is EquityAlgorithm.EXACT_ENUMERATION
                else AnalysisLevel.SIMULATED
            ),
            equity_by_seat={seat: equities[seat] for seat in sorted(seats)},
            active_player_count=len(seats),
            tie_probability=tie_probability,
            trials=accumulator.trials,
            random_seed=random_seed,
            standard_errors_by_seat=standard_errors,
            weighted=weighted,
        )

    def _sample_non_overlapping_pair(self, rng, hero_combos, villain_combos):
        """Sample a legal hero/villain combo pair from the joint distribution.

        Both seats are drawn independently from their own weighted combo
        distributions; overlapping pairs are rejected wholesale and redrawn.
        Accepted pairs are i.i.d. from P(h, v) ∝ weight(h) * weight(v) over
        non-overlapping pairs, so each trial counts once with weight one.
        """
        for _ in range(_MAX_SAMPLING_ATTEMPTS):
            hero = _weighted_choice(rng, hero_combos)
            villain = _weighted_choice(rng, villain_combos)
            if not set(hero.cards).intersection(villain.cards):
                return hero, villain
        raise InvalidAnalysisInput("could not sample non-overlapping range combos")

    @staticmethod
    def _sample_non_overlapping_multiway(
        rng: random.Random,
        combo_lists: list[tuple[WeightedCombo, ...]],
        board: tuple[Card, ...],
    ) -> tuple[WeightedCombo, ...]:
        """Sample a legal joint combo tuple from the exact joint distribution.

        Each seat is drawn independently from its own weighted combo
        distribution (proposal P ∝ ∏ weight_i); tuples with any overlapping
        cards are rejected wholesale and redrawn. This is standard rejection
        sampling: accepted draws are i.i.d. from the conditional distribution
        Q(tuple | legal) ∝ ∏ weight_i(combo_i) over legal non-overlapping
        tuples, which is exactly the target joint distribution. Unlike
        seat-by-seat conditional rejection, this is unbiased regardless of
        how the per-seat ranges overlap.
        """
        board_cards = set(board)
        for _ in range(_MAX_SAMPLING_ATTEMPTS):
            sampled = tuple(_weighted_choice(rng, combos) for combos in combo_lists)
            seen = set(board_cards)
            for combo in sampled:
                if seen.intersection(combo.cards):
                    break
                seen.update(combo.cards)
            else:
                return sampled
        raise InvalidAnalysisInput("could not sample non-overlapping multiway combos")

    def _add_showdown(
        self,
        accumulator: _Accumulator,
        hero_hole_cards: tuple[Card, Card],
        villain_hole_cards: tuple[Card, Card],
        board: tuple[Card, ...],
        weight: Decimal = Decimal("1"),
    ) -> None:
        accumulator.add(
            best_hand_key(hero_hole_cards + board),
            best_hand_key(villain_hole_cards + board),
            weight,
        )

    def _result(
        self,
        accumulator: _Accumulator,
        algorithm: EquityAlgorithm,
        *,
        random_seed: int | None = None,
        weighted: bool,
    ) -> EquityResult:
        if accumulator.trials == 0 or (
            accumulator.weighted and accumulator.total_mass == 0
        ):
            raise InvalidAnalysisInput("equity calculation produced no trials")
        if accumulator.weighted:
            hero_mass = accumulator.hero_mass
            villain_mass = accumulator.villain_mass
            tie_mass = accumulator.tie_mass
            total_mass = accumulator.total_mass
        else:
            hero_mass = Decimal(accumulator.hero_wins)
            villain_mass = Decimal(accumulator.villain_wins)
            tie_mass = Decimal(accumulator.ties)
            total_mass = Decimal(accumulator.trials)
        with localcontext() as context:
            context.prec = 28
            hero_equity = (hero_mass + tie_mass / 2) / total_mass
            villain_equity = (villain_mass + tie_mass / 2) / total_mass
            tie_probability = tie_mass / total_mass
        confidence = standard_error = None
        if algorithm is EquityAlgorithm.MONTE_CARLO:
            p = float(hero_equity)
            variance = max(0.0, p * (1 - p))
            standard_error = Decimal(str(math.sqrt(variance / accumulator.trials)))
            margin = Decimal("1.96") * standard_error
            confidence = (
                max(Decimal("0"), hero_equity - margin),
                min(Decimal("1"), hero_equity + margin),
            )
        return EquityResult(
            algorithm=algorithm,
            source_level=(
                AnalysisLevel.ENUMERATED
                if algorithm is EquityAlgorithm.EXACT_ENUMERATION
                else AnalysisLevel.SIMULATED
            ),
            hero_wins=accumulator.hero_wins,
            villain_wins=accumulator.villain_wins,
            ties=accumulator.ties,
            trials=accumulator.trials,
            hero_equity=hero_equity,
            villain_equity=villain_equity,
            tie_probability=tie_probability,
            random_seed=random_seed,
            confidence_interval=confidence,
            standard_error=standard_error,
            weighted=weighted,
        )

    def _validate_known_cards(self, hero, villain, board):
        return self._validate_cards(tuple(hero) + tuple(villain) + tuple(board))

    @staticmethod
    def _validate_cards(cards: Iterable[Card]) -> tuple[Card, ...]:
        normalized = tuple(cards)
        if len(normalized) != len(set(normalized)):
            raise InvalidAnalysisInput("known cards cannot overlap")
        if len(normalized) > 9:
            raise InvalidAnalysisInput("analysis accepts at most four hole cards and five board cards")
        return sort_cards(normalized)

    def _ensure_workload(self, operations: int) -> None:
        if operations <= 0:
            raise InvalidAnalysisInput("equity calculation has no possible runouts")
        if operations > self.max_exact_operations:
            raise InvalidAnalysisInput(
                f"exact enumeration requires {operations} evaluations; use Monte Carlo"
            )

    @staticmethod
    def _require_sampling(trials: int, random_seed: int | None) -> None:
        if trials <= 0:
            raise InvalidAnalysisInput("Monte Carlo trials must be positive")
        if random_seed is None or random_seed < 0:
            raise InvalidAnalysisInput("Monte Carlo requires a non-negative random seed")

    @staticmethod
    def _checkpoint(
        count: int,
        cancel_event: Event | None,
        timeout_seconds: float | None,
        started_at: float,
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AnalysisCancelled("equity calculation cancelled")
        if timeout_seconds is not None and timeout_seconds < 0:
            raise InvalidAnalysisInput("timeout_seconds cannot be negative")
        if timeout_seconds is not None:
            if time.monotonic() - started_at > timeout_seconds:
                raise AnalysisTimeout("equity calculation timed out")


def _iter_runouts(remaining: tuple[Card, ...], missing: int):
    if missing < 0:
        raise InvalidAnalysisInput("board cannot contain more than five cards")
    if missing == 0:
        yield ()
        return
    yield from combinations(remaining, missing)


def _weighted_choice(rng: random.Random, combos: tuple[WeightedCombo, ...]) -> WeightedCombo:
    total = sum((combo.weight for combo in combos), Decimal("0"))
    if total <= 0:
        raise InvalidAnalysisInput("range weights must have positive total weight")
    target = Decimal(str(rng.random())) * total
    cursor = Decimal("0")
    for combo in combos:
        cursor += combo.weight
        if target < cursor:
            return combo
    return combos[-1]


def _prod_weights(combos: Iterable[WeightedCombo]) -> Decimal:
    result = Decimal("1")
    for combo in combos:
        result *= combo.weight
    return result
