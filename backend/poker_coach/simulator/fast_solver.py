"""Bounded, deterministic range-aware approximate-EV solver.

Fast Solver L1.5 consumes only ObservationV1 plus R7-04 public-event beliefs.
It is intentionally a one-response heuristic, not GTO/Nash or a player model.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from bisect import bisect_left
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Literal

from pydantic import ConfigDict, Field, model_validator

from poker_coach.analysis.cards import best_hand_key, deck
from poker_coach.domain.models import DomainModel, Street

from .contracts import AmountSemanticsV1, LegalActionV1, ObservationV1, SimulatorActionV1

BudgetTier = Literal["quick", "standard", "deep"]
_BUDGETS: dict[str, tuple[int, int, int]] = {
    "quick": (50, 100, 64),
    "standard": (150, 300, 256),
    "deep": (500, 1500, 1024),
}
_ZERO = Decimal("0")
_ONE = Decimal("1")
_RangeEntries = tuple[tuple[str, str, Decimal], ...]
_RangeSampler = tuple[_RangeEntries, tuple[Decimal, ...], Decimal]
_JOINT_ENUM_STATE_CAP = 20_000
_JOINT_ENUM_LEAF_CAP = 4_096


class _NoJointRangeSupport(RuntimeError):
    pass


class _JointSearchLimit(RuntimeError):
    pass


class _FastSolverContractV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1


class SolverDecisionIdentityV1(_FastSolverContractV1):
    fingerprint: str
    hand_id: str
    sequence: int = Field(ge=0)
    street: Street


class SolverConfidenceIntervalV1(_FastSolverContractV1):
    lower: Decimal
    upper: Decimal
    confidence: Literal["95"] = "95"

    @model_validator(mode="after")
    def validate_bounds(self) -> "SolverConfidenceIntervalV1":
        if self.upper < self.lower:
            raise ValueError("confidence interval upper must be >= lower")
        return self

    @property
    def width(self) -> Decimal:
        return self.upper - self.lower


class SolverResponseMixV1(_FastSolverContractV1):
    fold: Decimal = Field(ge=0, le=1)
    call: Decimal = Field(ge=0, le=1)
    raise_: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_sum(self) -> "SolverResponseMixV1":
        if self.fold + self.call + self.raise_ != _ONE:
            raise ValueError("response probabilities must sum to one")
        return self


class SolverCandidateV1(_FastSolverContractV1):
    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    amount: int | None = Field(default=None, ge=0)
    incremental_cost: int = Field(ge=0)
    opponent_call_total: int = Field(ge=0)
    call_continuation_pot: int = Field(ge=0)
    raise_response_assumption: Literal["hero_folds_no_further_cost"] | None = None
    approximate_ev_chips: Decimal
    showdown_equity: Decimal = Field(ge=0, le=1)
    fold_equity: Decimal = Field(ge=0, le=1)
    sample_count: int = Field(ge=0)
    effective_sample_size: Decimal = Field(ge=0)
    confidence_interval_95: SolverConfidenceIntervalV1 | None = None
    pot_percentage: Decimal | None = None
    is_jam: bool = False
    sizing_class: Literal["non_sizing", "standard", "overbet", "jam"] = "non_sizing"
    delta_ev_chips: Decimal = _ZERO
    delta_ev_confidence_interval_95: SolverConfidenceIntervalV1 | None = None
    uncertainty_status: Literal["available", "not_available"] = "not_available"
    recommendation_tier: Literal[
        "robust", "close", "not_available", "not_recommended"
    ] = "not_recommended"
    response_mix: SolverResponseMixV1
    response_model: Literal["bounded_public_heuristic_v2"] = "bounded_public_heuristic_v2"


class FastSolverResultV1(_FastSolverContractV1):
    status: Literal["ready", "degraded", "unavailable", "not_ready"]
    recommended_action: SolverCandidateV1 | None = None
    candidates: tuple[SolverCandidateV1, ...] = ()
    equity: Decimal | None = Field(default=None, ge=0, le=1)
    iterations: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    effective_sample_size: Decimal = Field(ge=0)
    confidence_interval_95: SolverConfidenceIntervalV1 | None = None
    elapsed_microseconds: int = Field(ge=0)
    budget_ms: int = Field(ge=0)
    hard_budget_ms: int = Field(ge=0)
    budget_tier: BudgetTier
    source: Literal[
        "range_weighted_public_beliefs", "monte_carlo_uniform_opponents"
    ]
    range_status: Literal["ready", "unavailable_fallback_uniform"]
    range_fingerprint: str | None = None
    range_model_version: str | None = None
    version: Literal["fast-ev-solver/v1"] = "fast-ev-solver/v1"
    model_version: Literal["fast-ev-solver/v1.5"] = "fast-ev-solver/v1.5"
    confidence: Literal["exact", "coarse", "partial", "unavailable"]
    sizing_robustness: Literal["robust", "close", "not_available"] = "not_available"
    recommendation_reason_codes: tuple[
        Literal[
            "deterministic_model_clear",
            "sample_margin_clear",
            "close_conservative_tiebreak",
            "uncertainty_not_available_conservative_tiebreak",
        ], ...
    ] = ()
    robustness_margin_confidence_interval_95: SolverConfidenceIntervalV1 | None = None
    limitations: tuple[str, ...]
    decision: SolverDecisionIdentityV1
    unavailable_reason: str | None = None


class FastSolver:
    """Evaluate legal product sizings over a deterministic nested sample stream."""

    def __init__(
        self,
        *,
        iteration_cap: int | None = None,
        soft_budget_ms: int | None = None,
        hard_budget_ms: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if iteration_cap is not None and iteration_cap <= 0:
            raise ValueError("iteration_cap must be positive")
        if soft_budget_ms is not None and soft_budget_ms < 0:
            raise ValueError("soft_budget_ms must be non-negative")
        if (
            hard_budget_ms is not None
            and soft_budget_ms is not None
            and hard_budget_ms < soft_budget_ms
        ):
            raise ValueError("hard budget must be >= soft budget")
        self.iteration_cap = iteration_cap
        self.soft_budget_ms = soft_budget_ms
        self.hard_budget_ms = hard_budget_ms
        self._clock = clock or time.monotonic

    def solve(
        self,
        observation: ObservationV1,
        *,
        decision_fingerprint: str,
        seed: int | None = None,
        is_hero_decision: bool = True,
        range_beliefs: Mapping[int, object] | None = None,
        budget_tier: BudgetTier = "standard",
    ) -> FastSolverResultV1:
        if budget_tier not in _BUDGETS:
            raise ValueError("budget_tier must be quick, standard, or deep")
        soft_ms, hard_ms, tier_cap = _BUDGETS[budget_tier]
        soft_ms = soft_ms if self.soft_budget_ms is None else self.soft_budget_ms
        hard_ms = hard_ms if self.hard_budget_ms is None else self.hard_budget_ms
        if hard_ms < soft_ms:
            raise ValueError("hard budget must be >= soft budget")
        iteration_cap = tier_cap if self.iteration_cap is None else self.iteration_cap

        started = self._clock()
        identity = SolverDecisionIdentityV1(
            fingerprint=decision_fingerprint,
            hand_id=observation.hand_id,
            sequence=observation.sequence,
            street=observation.street,
        )
        if not is_hero_decision:
            return self._unavailable(
                identity, "not_hero_decision", "not_ready", started,
                budget_tier, soft_ms, hard_ms,
            )
        if not observation.legal_actions:
            return self._unavailable(
                identity, "no_legal_actions", "not_ready", started,
                budget_tier, soft_ms, hard_ms,
            )

        range_ready = self._range_ready(observation, range_beliefs)
        active_ranges = range_beliefs if range_ready else None
        range_samplers = (
            self._prepare_range_samplers(observation, active_ranges)
            if active_ranges is not None else None
        )
        exact = self._exact_heads_up_river(observation, active_ranges) if range_ready else None
        timed_out = False
        joint_limit_exhausted = False
        shares: list[Decimal] = []
        if exact is not None:
            equity, sample_count, ess = exact
        else:
            sample_seed = (
                self._seed(decision_fingerprint, observation)
                if seed is None else seed
            )
            rng = random.Random(sample_seed)
            for _ in range(iteration_cap):
                elapsed_ms = (self._clock() - started) * 1_000
                # Sampler preparation is part of the truthful end-to-end
                # budget. If cold-start work crosses only the soft deadline,
                # use the already-declared hard window for one real sample;
                # otherwise a slower runner can report zero evidence before
                # sampling even begins. Once evidence exists, soft remains the
                # normal stop boundary. Hard exhaustion is still unavailable.
                if (shares and elapsed_ms >= soft_ms) or (
                    not shares and elapsed_ms >= hard_ms
                ):
                    timed_out = True
                    break
                try:
                    trial = self._sample_trial(observation, rng, range_samplers)
                except _NoJointRangeSupport:
                    # Independent marginals can theoretically have no joint
                    # card-compatible support. Restart deterministically on the
                    # existing uniform L1 path and report the honest fallback.
                    range_ready = False
                    active_ranges = None
                    range_samplers = None
                    shares.clear()
                    rng = random.Random(sample_seed)
                    trial = self._sample_trial(observation, rng, None)
                except _JointSearchLimit:
                    timed_out = True
                    joint_limit_exhausted = True
                    break
                shares.append(self._hero_share(observation, trial))
                if (self._clock() - started) * 1_000 >= hard_ms:
                    timed_out = True
                    break
            sample_count = len(shares)
            if sample_count == 0:
                return self._unavailable(
                    identity,
                    (
                        "range_joint_enumeration_cap_exhausted"
                        if joint_limit_exhausted else "solver_budget_exhausted"
                    ),
                    "unavailable",
                    started,
                    budget_tier, soft_ms, hard_ms, range_ready=range_ready,
                )
            equity = sum(shares, _ZERO) / sample_count
            ess = Decimal(sample_count)

        uncertainty_available = exact is not None or sample_count >= 2
        equity_ci = (
            self._confidence_interval(equity, ess, exact=exact is not None)
            if uncertainty_available else None
        )
        raw_candidates = tuple(
            self._candidate(
                legal, amount, observation, equity, sample_count, ess, equity_ci,
                range_beliefs if range_ready else None,
            )
            for legal in observation.legal_actions
            for amount in self._amounts(legal, observation)
        )
        (
            candidates,
            recommendation,
            sizing_robustness,
            recommendation_reasons,
            robustness_margin_ci,
        ) = self._calibrate_recommendation(
            raw_candidates,
            sample_count=sample_count,
            exact=exact is not None,
        )
        elapsed = max(0, int((self._clock() - started) * 1_000_000))
        fallback = not range_ready
        return FastSolverResultV1(
            status="degraded" if timed_out or fallback else "ready",
            recommended_action=recommendation,
            candidates=candidates,
            equity=equity,
            iterations=sample_count,
            sample_count=sample_count,
            effective_sample_size=ess,
            confidence_interval_95=equity_ci,
            elapsed_microseconds=elapsed,
            budget_ms=soft_ms,
            hard_budget_ms=hard_ms,
            budget_tier=budget_tier,
            source=(
                "range_weighted_public_beliefs"
                if range_ready else "monte_carlo_uniform_opponents"
            ),
            range_status="ready" if range_ready else "unavailable_fallback_uniform",
            range_fingerprint=self._range_fingerprint(range_beliefs) if range_ready else None,
            range_model_version=self._range_version(range_beliefs) if range_ready else None,
            confidence=(
                "exact" if exact is not None else "partial" if timed_out else "coarse"
            ),
            sizing_robustness=sizing_robustness,
            recommendation_reason_codes=recommendation_reasons,
            robustness_margin_confidence_interval_95=robustness_margin_ci,
            limitations=(
                "Range-aware Fast EV L1.5 uses independent per-seat public-event combo marginals with strict visible-card and sequential opponent card removal.",
                "Opponent fold/call/raise is a bounded heuristic using public continuation-range width, position, SPR, street, and sizing; it is not GTO, Nash, or a player/profile model.",
                "The one-layer aggregate call branch stack-caps every active opponent's completion to Hero's target; the raise branch stops with Hero folding and no invented re-raise amount or further Hero cost.",
                "The response tree uses an approximate showdown continuation; no future actions, opponent private cards, RNG/deck state, terminal payout, or future events are consumed.",
                "Candidate EV intervals use common showdown samples and quantify sampling uncertainty only; sizing robustness does not include error in the bounded response heuristic.",
                (
                    "Exact joint enumeration hit its state/leaf cap; only earlier unbiased conditional-product samples are returned as partial range-aware output."
                    if joint_limit_exhausted else
                    "Joint samples use product-weighted rejection; sparse conflicts use exact state/leaf-capped feasible-joint enumeration and never first-feasible DFS."
                ),
                (
                    "R7-04 Range V2 was unavailable, so the action remained non-blocking via the deterministic uniform-opponent L1 fallback."
                    if fallback else
                    "R7-04 Range V2 heuristic provenance is preserved; independent marginals are conditioned on disjoint cards but are not a learned joint range."
                ),
            ),
            decision=identity,
        )

    def not_ready(
        self,
        *,
        decision_fingerprint: str,
        hand_id: str,
        sequence: int,
        street: Street,
        budget_tier: BudgetTier = "standard",
    ) -> FastSolverResultV1:
        soft_ms, hard_ms, _ = _BUDGETS[budget_tier]
        started = self._clock()
        return self._unavailable(
            SolverDecisionIdentityV1(
                fingerprint=decision_fingerprint,
                hand_id=hand_id,
                sequence=sequence,
                street=street,
            ),
            "not_hero_decision",
            "not_ready",
            started,
            budget_tier,
            soft_ms,
            hard_ms,
        )

    def sample_trial(
        self,
        observation: ObservationV1,
        *,
        seed: int,
        range_beliefs: Mapping[int, object] | None = None,
    ) -> tuple[str, ...]:
        """Test seam returning only the sampled cards, never production output."""

        ranges = range_beliefs if self._range_ready(observation, range_beliefs) else None
        samplers = self._prepare_range_samplers(observation, ranges) if ranges else None
        return self._sample_trial(observation, random.Random(seed), samplers)

    def _sample_trial(
        self,
        observation: ObservationV1,
        rng: random.Random,
        range_samplers: Mapping[int, _RangeSampler] | None,
    ) -> tuple[str, ...]:
        known = list((*observation.own_hole_cards, *observation.board))
        opponents: list[str] = []
        if range_samplers is None:
            count = (len(observation.active_seats) - 1) * 2
            opponents.extend(rng.sample(deck(tuple(known)), count))
        else:
            opponent_seats = tuple(
                seat for seat in observation.active_seats
                if seat != observation.observer_seat
            )
            assignments = self._sample_joint_opponents(
                range_samplers, opponent_seats, rng
            )
            opponents.extend(
                card for seat in opponent_seats for card in assignments[seat]
            )
        runout_count = 5 - len(observation.board)
        runout = rng.sample(deck(tuple((*known, *opponents))), runout_count)
        return tuple((*known, *opponents, *runout))

    @classmethod
    def _sample_joint_opponents(
        cls,
        samplers: Mapping[int, _RangeSampler],
        seats: tuple[int, ...],
        rng: random.Random,
    ) -> dict[int, tuple[str, str]]:
        # Independent rejection samples the product of seat marginals
        # conditioned on global card uniqueness. If sparse support defeats the
        # bounded rejection phase, exact capped enumeration preserves the same
        # conditional product weights. No first-feasible assignment is used.
        for _ in range(24):
            assignment = {
                seat: cls._draw_sampler(samplers[seat], rng)
                for seat in seats
            }
            if all(cards is not None for cards in assignment.values()):
                flattened = [card for cards in assignment.values() for card in cards]
                if len(flattened) == len(set(flattened)):
                    return assignment  # type: ignore[return-value]
        leaves: list[tuple[dict[int, tuple[str, str]], Decimal]] = []
        states = [0]
        cls._enumerate_joint(
            samplers,
            seats,
            set(),
            {},
            _ONE,
            leaves,
            states,
            state_cap=_JOINT_ENUM_STATE_CAP,
            leaf_cap=_JOINT_ENUM_LEAF_CAP,
        )
        if not leaves:
            raise _NoJointRangeSupport("range marginals have no compatible joint support")
        total = sum((weight for _assignment, weight in leaves), _ZERO)
        threshold = Decimal(str(rng.random())) * total
        cumulative = _ZERO
        for assignment, weight in leaves:
            cumulative += weight
            if threshold < cumulative:
                return assignment
        return leaves[-1][0]

    @classmethod
    def _enumerate_joint(
        cls,
        samplers: Mapping[int, _RangeSampler],
        remaining: tuple[int, ...],
        blocked: set[str],
        assignment: dict[int, tuple[str, str]],
        joint_weight: Decimal,
        leaves: list[tuple[dict[int, tuple[str, str]], Decimal]],
        states: list[int],
        *,
        state_cap: int,
        leaf_cap: int,
    ) -> None:
        if not remaining:
            if len(leaves) >= leaf_cap:
                raise _JointSearchLimit("exact joint leaf cap exhausted")
            leaves.append((dict(assignment), joint_weight))
            return
        eligible_by_seat = {
            seat: tuple(
                item for item in samplers[seat][0]
                if item[0] not in blocked and item[1] not in blocked
            )
            for seat in remaining
        }
        seat = min(remaining, key=lambda item: (len(eligible_by_seat[item]), item))
        eligible = eligible_by_seat[seat]
        if not eligible:
            return
        next_remaining = tuple(item for item in remaining if item != seat)
        for first, second, weight in eligible:
            states[0] += 1
            if states[0] > state_cap:
                raise _JointSearchLimit("exact joint state cap exhausted")
            assignment[seat] = (first, second)
            cls._enumerate_joint(
                samplers,
                next_remaining,
                blocked | {first, second},
                assignment,
                joint_weight * weight,
                leaves,
                states,
                state_cap=state_cap,
                leaf_cap=leaf_cap,
            )
        assignment.pop(seat, None)

    @staticmethod
    def _draw_sampler(
        sampler: _RangeSampler, rng: random.Random
    ) -> tuple[str, str] | None:
        entries, cumulative, total = sampler
        if total <= 0:
            return None
        threshold = Decimal(str(rng.random())) * total
        index = min(bisect_left(cumulative, threshold), len(entries) - 1)
        return (entries[index][0], entries[index][1]) if entries else None

    @staticmethod
    def _prepare_range_samplers(
        observation: ObservationV1,
        beliefs: Mapping[int, object],
    ) -> dict[int, _RangeSampler]:
        visible = set((*observation.own_hole_cards, *observation.board))
        prepared: dict[int, _RangeSampler] = {}
        for seat in observation.active_seats:
            if seat == observation.observer_seat:
                continue
            combos = getattr(getattr(beliefs[seat], "current", None), "combos", {})
            entries = tuple(
                (key[:2], key[2:], Decimal(getattr(combo, "probability", _ZERO)))
                for key, combo in sorted(combos.items())
                if len(key) == 4
                and key[:2] not in visible
                and key[2:] not in visible
                and key[:2] != key[2:]
                and Decimal(getattr(combo, "probability", _ZERO)) > 0
            )
            running = _ZERO
            cumulative: list[Decimal] = []
            for _first, _second, weight in entries:
                running += weight
                cumulative.append(running)
            prepared[seat] = (entries, tuple(cumulative), running)
        return prepared

    @staticmethod
    def _range_ready(
        observation: ObservationV1,
        beliefs: Mapping[int, object] | None,
    ) -> bool:
        if beliefs is None:
            return False
        blocked = set((*observation.own_hole_cards, *observation.board))
        for seat in observation.active_seats:
            if seat == observation.observer_seat:
                continue
            belief = beliefs.get(seat)
            if (
                belief is None
                or not getattr(belief, "available", False)
                or getattr(belief, "current", None) is None
            ):
                return False
            combos = getattr(belief.current, "combos", {})
            if not any(
                len(key) == 4
                and key[:2] not in blocked
                and key[2:] not in blocked
                and Decimal(getattr(combo, "probability", _ZERO)) > 0
                for key, combo in combos.items()
            ):
                return False
        return True

    @staticmethod
    def _hero_share(observation: ObservationV1, cards: tuple[str, ...]) -> Decimal:
        hero = cards[:2]
        board_count = len(observation.board)
        opponent_count = len(observation.active_seats) - 1
        opponent_start = 2 + board_count
        opponents = tuple(
            cards[opponent_start + index * 2 : opponent_start + (index + 1) * 2]
            for index in range(opponent_count)
        )
        runout = cards[opponent_start + opponent_count * 2 :]
        board = cards[2 : 2 + board_count] + runout
        hero_key = best_hand_key(hero + board)
        keys = [hero_key, *(best_hand_key(opponent + board) for opponent in opponents)]
        return _ONE / keys.count(max(keys)) if hero_key == max(keys) else _ZERO

    def _exact_heads_up_river(
        self,
        observation: ObservationV1,
        beliefs: Mapping[int, object] | None,
    ) -> tuple[Decimal, int, Decimal] | None:
        if (
            beliefs is None
            or len(observation.board) != 5
            or len(observation.active_seats) != 2
        ):
            return None
        opponent_seat = next(
            seat for seat in observation.active_seats if seat != observation.observer_seat
        )
        belief = beliefs[opponent_seat]
        blocked = set((*observation.own_hole_cards, *observation.board))
        weighted: list[tuple[tuple[str, str], Decimal]] = []
        for key, combo in getattr(belief.current, "combos", {}).items():
            cards = (key[:2], key[2:])
            probability = Decimal(getattr(combo, "probability", _ZERO))
            if len(key) == 4 and probability > 0 and not blocked.intersection(cards):
                weighted.append((cards, probability))
        total = sum((weight for _, weight in weighted), _ZERO)
        if total <= 0:
            return None
        hero_key = best_hand_key(observation.own_hole_cards + observation.board)
        equity = _ZERO
        squared = _ZERO
        for cards, weight in weighted:
            probability = weight / total
            opponent_key = best_hand_key(cards + observation.board)
            share = _ONE if hero_key > opponent_key else Decimal("0.5") if hero_key == opponent_key else _ZERO
            equity += probability * share
            squared += probability * probability
        return equity, len(weighted), _ONE / squared

    @staticmethod
    def _amounts(
        action: LegalActionV1, observation: ObservationV1
    ) -> tuple[int | None, ...]:
        if action.amount_semantics is AmountSemanticsV1.NONE:
            amounts: tuple[int | None, ...] = (None,)
        elif action.action is SimulatorActionV1.CALL:
            amounts = (action.min_amount,)
        else:
            assert action.min_amount is not None and action.max_amount is not None
            hero_commitment = observation.street_commitments[observation.observer_seat]
            standard = {
                int(
                    (Decimal(observation.pot) * percentage / Decimal(100)).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
                for percentage in (
                    Decimal("33"), Decimal("50"), Decimal("66"),
                    Decimal("75"), Decimal("100"),
                )
            }
            if action.amount_semantics is AmountSemanticsV1.TO:
                standard = {hero_commitment + amount for amount in standard}
            amounts = tuple(sorted({
                action.min_amount,
                action.max_amount,
                *(
                    amount for amount in standard
                    if action.min_amount <= amount <= action.max_amount
                ),
            }))
        if not all(action.accepts(action=action.action, amount=amount) for amount in amounts):
            raise ValueError("solver generated a candidate rejected by LegalActionV1")
        return amounts

    def _candidate(
        self,
        legal: LegalActionV1,
        amount: int | None,
        observation: ObservationV1,
        equity: Decimal,
        sample_count: int,
        ess: Decimal,
        equity_ci: SolverConfidenceIntervalV1 | None,
        range_beliefs: Mapping[int, object] | None,
    ) -> SolverCandidateV1:
        if legal.amount_semantics is AmountSemanticsV1.NONE:
            cost = 0
        elif legal.amount_semantics is AmountSemanticsV1.TO:
            assert amount is not None
            cost = amount - observation.street_commitments[observation.observer_seat]
        else:
            assert amount is not None
            cost = amount
        mix = self._response_mix(
            legal.action, cost, observation, range_beliefs
        )
        pot = Decimal(observation.pot)
        chip_cost = Decimal(cost)
        if legal.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
            assert amount is not None
            hero_target = (
                amount
                if legal.amount_semantics is AmountSemanticsV1.TO
                else observation.street_commitments[observation.observer_seat] + amount
            )
            opponent_call_total = sum(
                min(
                    max(0, hero_target - observation.street_commitments[seat]),
                    observation.stacks[seat],
                )
                for seat in observation.active_seats
                if seat != observation.observer_seat
            )
        else:
            opponent_call_total = 0
        continuation_pot = observation.pot + cost + opponent_call_total
        if legal.action is SimulatorActionV1.FOLD:
            ev = _ZERO
        elif legal.action is SimulatorActionV1.CHECK:
            ev = equity * pot
        elif legal.action is SimulatorActionV1.CALL:
            ev = equity * (pot + chip_cost) - chip_cost
        else:
            call_ev = equity * Decimal(continuation_pot) - chip_cost
            # The bounded response tree stops at an opponent raise. Hero folds;
            # there is no invented re-raise TO amount or further Hero cost.
            raise_ev = -chip_cost
            ev = mix.fold * pot + mix.call * call_ev + mix.raise_ * raise_ev
        if legal.action is SimulatorActionV1.FOLD:
            equity_sensitivity = _ZERO
        elif legal.action in {SimulatorActionV1.CHECK, SimulatorActionV1.CALL}:
            equity_sensitivity = Decimal(continuation_pot)
        else:
            equity_sensitivity = mix.call * Decimal(continuation_pot)
        ev_ci = None if equity_ci is None else SolverConfidenceIntervalV1(
            lower=ev - (equity - equity_ci.lower) * equity_sensitivity,
            upper=ev + (equity_ci.upper - equity) * equity_sensitivity,
        )
        pot_percentage = (
            Decimal(cost) * Decimal(100) / Decimal(observation.pot)
            if amount is not None and observation.pot > 0 else None
        )
        is_jam = (
            legal.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}
            and cost == observation.stacks[observation.observer_seat]
        )
        sizing_class: Literal["non_sizing", "standard", "overbet", "jam"]
        if amount is None:
            sizing_class = "non_sizing"
        elif is_jam:
            sizing_class = "jam"
        elif pot_percentage is not None and pot_percentage > Decimal("100"):
            sizing_class = "overbet"
        else:
            sizing_class = "standard"
        return SolverCandidateV1(
            action=legal.action,
            amount_semantics=legal.amount_semantics,
            amount=amount,
            incremental_cost=max(0, cost),
            opponent_call_total=opponent_call_total,
            call_continuation_pot=continuation_pot,
            raise_response_assumption=(
                "hero_folds_no_further_cost"
                if legal.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}
                else None
            ),
            approximate_ev_chips=ev,
            showdown_equity=equity,
            fold_equity=mix.fold if legal.action in {SimulatorActionV1.BET, SimulatorActionV1.RAISE} else _ZERO,
            sample_count=sample_count,
            effective_sample_size=ess,
            confidence_interval_95=ev_ci,
            pot_percentage=pot_percentage,
            is_jam=is_jam,
            sizing_class=sizing_class,
            uncertainty_status="available" if ev_ci is not None else "not_available",
            response_mix=mix,
        )

    @classmethod
    def _calibrate_recommendation(
        cls,
        candidates: tuple[SolverCandidateV1, ...],
        *,
        sample_count: int,
        exact: bool,
    ) -> tuple[
        tuple[SolverCandidateV1, ...],
        SolverCandidateV1,
        Literal["robust", "close", "not_available"],
        tuple[str, ...],
        SolverConfidenceIntervalV1 | None,
    ]:
        point_best = max(candidates, key=cls._point_estimate_key)
        uncertainty_available = exact or sample_count >= 2
        calibrated: list[SolverCandidateV1] = []
        for candidate in candidates:
            delta_ci = (
                cls._difference_interval(
                    candidate, point_best, sample_count=sample_count, exact=exact
                )
                if uncertainty_available else None
            )
            calibrated.append(candidate.model_copy(update={
                "delta_ev_chips": (
                    candidate.approximate_ev_chips - point_best.approximate_ev_chips
                ),
                "delta_ev_confidence_interval_95": delta_ci,
                "uncertainty_status": (
                    "available" if uncertainty_available else "not_available"
                ),
            }))
        candidates = tuple(calibrated)
        point_best = next(
            candidate for candidate in candidates
            if cls._same_candidate(candidate, point_best)
        )
        alternatives = tuple(
            candidate for candidate in candidates
            if not cls._same_candidate(candidate, point_best)
        )
        if not uncertainty_available:
            eligible = tuple(candidate for candidate in candidates if not cls._is_extreme(candidate))
            recommendation = max(eligible or candidates, key=cls._point_estimate_key)
            robustness: Literal["robust", "close", "not_available"] = "not_available"
            reasons = ("uncertainty_not_available_conservative_tiebreak",)
            margin_ci = None
        else:
            close = tuple(
                candidate for candidate in alternatives
                if cls._difference_interval(
                    point_best, candidate, sample_count=sample_count, exact=exact
                ).lower <= _ZERO
            )
            challenger = (
                max(alternatives, key=cls._point_estimate_key)
                if alternatives else point_best
            )
            if close:
                recommendation = min((point_best, *close), key=cls._conservative_key)
                robustness = "close"
                reasons = ("close_conservative_tiebreak",)
                margin_ci = cls._difference_interval(
                    point_best,
                    recommendation if not cls._same_candidate(point_best, recommendation) else challenger,
                    sample_count=sample_count,
                    exact=exact,
                )
            else:
                recommendation = point_best
                robustness = "robust"
                reasons = (
                    "deterministic_model_clear" if exact else "sample_margin_clear",
                )
                margin_ci = cls._difference_interval(
                    point_best, challenger, sample_count=sample_count, exact=exact
                )
        candidates = tuple(
            candidate.model_copy(update={
                "recommendation_tier": (
                    robustness if cls._same_candidate(candidate, recommendation)
                    else "not_recommended"
                )
            })
            for candidate in candidates
        )
        recommendation = next(
            candidate for candidate in candidates
            if cls._same_candidate(candidate, recommendation)
        )
        return candidates, recommendation, robustness, reasons, margin_ci

    @staticmethod
    def _point_estimate_key(candidate: SolverCandidateV1) -> tuple[Decimal, str, int]:
        return (
            candidate.approximate_ev_chips,
            candidate.action.value,
            -1 if candidate.amount is None else candidate.amount,
        )

    @staticmethod
    def _same_candidate(first: SolverCandidateV1, second: SolverCandidateV1) -> bool:
        return (
            first.action is second.action
            and first.amount_semantics is second.amount_semantics
            and first.amount == second.amount
        )

    @staticmethod
    def _is_extreme(candidate: SolverCandidateV1) -> bool:
        return candidate.is_jam or candidate.sizing_class == "overbet"

    @staticmethod
    def _conservative_key(candidate: SolverCandidateV1) -> tuple[int, int, Decimal, int]:
        action_risk = {
            SimulatorActionV1.CHECK: 0,
            SimulatorActionV1.CALL: 1,
            SimulatorActionV1.BET: 2,
            SimulatorActionV1.RAISE: 2,
            SimulatorActionV1.FOLD: 3,
        }[candidate.action]
        sizing_distance = (
            abs(candidate.pot_percentage - Decimal("66"))
            if candidate.pot_percentage is not None else _ZERO
        )
        return (
            1 if FastSolver._is_extreme(candidate) else 0,
            action_risk,
            sizing_distance,
            candidate.incremental_cost,
        )

    @staticmethod
    def _equity_sensitivity(candidate: SolverCandidateV1) -> Decimal:
        if candidate.action is SimulatorActionV1.FOLD:
            return _ZERO
        if candidate.action in {SimulatorActionV1.CHECK, SimulatorActionV1.CALL}:
            return Decimal(candidate.call_continuation_pot)
        return candidate.response_mix.call * Decimal(candidate.call_continuation_pot)

    @classmethod
    def _difference_interval(
        cls,
        first: SolverCandidateV1,
        second: SolverCandidateV1,
        *,
        sample_count: int,
        exact: bool,
    ) -> SolverConfidenceIntervalV1:
        difference = first.approximate_ev_chips - second.approximate_ev_chips
        radius = _ZERO if exact else (
            abs(cls._equity_sensitivity(first) - cls._equity_sensitivity(second))
            * Decimal(str(math.sqrt(math.log(40) / (2 * sample_count))))
        )
        return SolverConfidenceIntervalV1(
            lower=difference - radius,
            upper=difference + radius,
        )

    @staticmethod
    def _response_mix(
        action: SimulatorActionV1,
        cost: int,
        observation: ObservationV1,
        beliefs: Mapping[int, object] | None,
    ) -> SolverResponseMixV1:
        if action not in {SimulatorActionV1.BET, SimulatorActionV1.RAISE}:
            return SolverResponseMixV1(fold=_ZERO, call=_ONE, raise_=_ZERO)
        pot = max(1, observation.pot)
        size_ratio = min(Decimal("4"), Decimal(cost) / Decimal(pot))
        pressure = size_ratio / (_ONE + size_ratio)
        effective_stack = min(observation.stacks[seat] for seat in observation.active_seats)
        spr = Decimal(effective_stack) / Decimal(pot)
        spr_leverage = min(_ONE, spr / Decimal("3"))
        street_factor = {
            Street.PREFLOP: Decimal("0"),
            Street.FLOP: Decimal("0.03"),
            Street.TURN: Decimal("0.06"),
            Street.RIVER: Decimal("0.09"),
        }[observation.street]
        distance_to_button = (
            observation.button_seat - observation.observer_seat
        ) % observation.table_size
        position_factor = _ONE - (
            Decimal(distance_to_button) / Decimal(max(1, observation.table_size - 1))
        )
        position_factor = min(_ONE, max(_ZERO, position_factor))
        range_strength = Decimal("0.5")
        if beliefs:
            visible = set((*observation.own_hole_cards, *observation.board))
            feasible_combo_count = math.comb(52 - len(visible), 2)
            widths: list[Decimal] = []
            for seat in observation.active_seats:
                if seat == observation.observer_seat:
                    continue
                combos = getattr(getattr(beliefs[seat], "current", None), "combos", {})
                eligible_weights = tuple(
                    Decimal(getattr(combo, "probability", _ZERO))
                    for key, combo in combos.items()
                    if len(key) == 4
                    and key[:2] not in visible
                    and key[2:] not in visible
                    and Decimal(getattr(combo, "probability", _ZERO)) > 0
                )
                mass = sum(eligible_weights, _ZERO)
                if mass > 0:
                    squared = sum(
                        ((weight / mass) ** 2 for weight in eligible_weights),
                        _ZERO,
                    )
                    effective_width = _ONE / squared
                    widths.append(
                        min(_ONE, effective_width / Decimal(feasible_combo_count))
                    )
            if widths:
                range_strength = _ONE - sum(widths, _ZERO) / Decimal(len(widths))
        single_fold = (
            Decimal("0.10")
            + Decimal("0.40") * pressure * (Decimal("0.75") + Decimal("0.25") * spr_leverage)
            + street_factor
            + Decimal("0.04") * position_factor
            - Decimal("0.14") * range_strength
        )
        single_fold = min(Decimal("0.68"), max(Decimal("0.04"), single_fold))
        single_raise = (
            Decimal("0.04") + Decimal("0.10") * range_strength
            + Decimal("0.02") * spr_leverage - Decimal("0.025") * pressure
        )
        single_raise = min(Decimal("0.18"), max(Decimal("0.02"), single_raise))
        if single_fold + single_raise > Decimal("0.9"):
            single_raise = Decimal("0.9") - single_fold
        opponents = max(1, len(observation.active_seats) - 1)
        fold = single_fold ** opponents
        no_raise = (single_fold + (_ONE - single_fold - single_raise)) ** opponents
        raise_probability = _ONE - no_raise
        call = no_raise - fold
        return SolverResponseMixV1(fold=fold, call=call, raise_=raise_probability)

    @staticmethod
    def _confidence_interval(
        equity: Decimal, ess: Decimal, *, exact: bool
    ) -> SolverConfidenceIntervalV1:
        radius = (
            _ZERO
            if exact
            else Decimal(str(math.sqrt(math.log(40) / (2 * max(1.0, float(ess))))))
        )
        return SolverConfidenceIntervalV1(
            lower=max(_ZERO, equity - radius),
            upper=min(_ONE, equity + radius),
        )

    def _unavailable(
        self,
        identity: SolverDecisionIdentityV1,
        reason: str,
        status: Literal["unavailable", "not_ready"],
        started: float,
        budget_tier: BudgetTier,
        soft_ms: int,
        hard_ms: int,
        *,
        range_ready: bool = False,
    ) -> FastSolverResultV1:
        return FastSolverResultV1(
            status=status,
            iterations=0,
            sample_count=0,
            effective_sample_size=_ZERO,
            elapsed_microseconds=max(0, int((self._clock() - started) * 1_000_000)),
            budget_ms=soft_ms,
            hard_budget_ms=hard_ms,
            budget_tier=budget_tier,
            source=(
                "range_weighted_public_beliefs"
                if range_ready else "monte_carlo_uniform_opponents"
            ),
            range_status="ready" if range_ready else "unavailable_fallback_uniform",
            confidence="unavailable",
            limitations=(
                "Fast EV Solver L1.5 did not run; L0 Formula Advisor and the action path remain independent.",
            ),
            decision=identity,
            unavailable_reason=reason,
        )

    @staticmethod
    def _seed(fingerprint: str, observation: ObservationV1) -> int:
        material = f"{fingerprint}|{observation.to_json()}|fast-ev-solver/v1.5"
        return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")

    @staticmethod
    def _range_fingerprint(beliefs: Mapping[int, object] | None) -> str | None:
        if not beliefs:
            return None
        parts = []
        for seat, belief in sorted(beliefs.items()):
            if getattr(belief, "available", False):
                provenance = getattr(belief, "provenance", None)
                current = getattr(belief, "current", None)
                parts.append(
                    f"{seat}:{getattr(provenance, 'artifact_fingerprint', '')}:"
                    f"{getattr(current, 'snapshot_id', '')}"
                )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _range_version(beliefs: Mapping[int, object] | None) -> str | None:
        if not beliefs:
            return None
        versions = {
            getattr(getattr(belief, "provenance", None), "version", "")
            for belief in beliefs.values()
            if getattr(belief, "available", False)
        }
        return ",".join(sorted(version for version in versions if version)) or None
