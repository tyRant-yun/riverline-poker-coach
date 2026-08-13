"""Bounded, deterministic Monte Carlo approximate-EV solver for table decisions.

This is deliberately an L1 approximation, not a GTO/Nash solver.  It consumes
only the Hero-safe ObservationV1 and LegalActionV1 boundary and never reads
authoritative opponent cards or later board events.
"""

from __future__ import annotations

import hashlib
import random
import time
from decimal import Decimal
from typing import Callable, Literal

from pydantic import ConfigDict, Field

from poker_coach.analysis.cards import best_hand_key, deck
from poker_coach.domain.models import DomainModel, Street

from .contracts import AmountSemanticsV1, LegalActionV1, ObservationV1, SimulatorActionV1


class _FastSolverContractV1(DomainModel):
    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1


class SolverDecisionIdentityV1(_FastSolverContractV1):
    fingerprint: str
    hand_id: str
    sequence: int = Field(ge=0)
    street: Street


class SolverCandidateV1(_FastSolverContractV1):
    action: SimulatorActionV1
    amount_semantics: AmountSemanticsV1
    amount: int | None = Field(default=None, ge=0)
    approximate_ev_chips: Decimal


class FastSolverResultV1(_FastSolverContractV1):
    status: Literal["ready", "degraded", "unavailable", "not_ready"]
    recommended_action: SolverCandidateV1 | None = None
    candidates: tuple[SolverCandidateV1, ...] = ()
    equity: Decimal | None = Field(default=None, ge=0, le=1)
    iterations: int = Field(ge=0)
    elapsed_microseconds: int = Field(ge=0)
    budget_ms: int = Field(ge=0)
    hard_budget_ms: int = Field(ge=0)
    source: Literal["monte_carlo_uniform_opponents"] = "monte_carlo_uniform_opponents"
    version: Literal["fast-ev-solver/v1"] = "fast-ev-solver/v1"
    confidence: Literal["coarse", "partial", "unavailable"]
    limitations: tuple[str, ...]
    decision: SolverDecisionIdentityV1
    unavailable_reason: str | None = None


class FastSolver:
    """Evaluate legal actions with seeded uniform-opponent runout samples."""

    def __init__(
        self,
        *,
        iteration_cap: int = 120,
        soft_budget_ms: int = 75,
        hard_budget_ms: int = 150,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if iteration_cap <= 0 or soft_budget_ms < 0 or hard_budget_ms < soft_budget_ms:
            raise ValueError("invalid FastSolver budget configuration")
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
    ) -> FastSolverResultV1:
        started = self._clock()
        identity = SolverDecisionIdentityV1(
            fingerprint=decision_fingerprint,
            hand_id=observation.hand_id,
            sequence=observation.sequence,
            street=observation.street,
        )
        if not is_hero_decision:
            return self._unavailable(identity, "not_hero_decision", "not_ready", started)
        if not observation.legal_actions:
            return self._unavailable(identity, "no_legal_actions", "not_ready", started)
        sample_seed = self._seed(decision_fingerprint) if seed is None else seed
        rng = random.Random(sample_seed)
        equity_sum = Decimal("0")
        iterations = 0
        timed_out = False
        for _ in range(self.iteration_cap):
            elapsed_ms = (self._clock() - started) * 1_000
            if elapsed_ms >= self.soft_budget_ms:
                timed_out = True
                break
            equity_sum += self._hero_share(observation, self._sample_trial(observation, rng))
            iterations += 1
            if (self._clock() - started) * 1_000 >= self.hard_budget_ms:
                timed_out = True
                break
        if iterations == 0:
            return self._unavailable(identity, "solver_budget_exhausted", "unavailable", started)
        equity = equity_sum / iterations
        candidates = tuple(self._candidate(action, observation, equity) for action in observation.legal_actions)
        recommendation = max(candidates, key=lambda candidate: (candidate.approximate_ev_chips, candidate.action.value))
        elapsed = max(0, int((self._clock() - started) * 1_000_000))
        return FastSolverResultV1(
            status="degraded" if timed_out else "ready",
            recommended_action=recommendation,
            candidates=candidates,
            equity=equity,
            iterations=iterations,
            elapsed_microseconds=elapsed,
            budget_ms=self.soft_budget_ms,
            hard_budget_ms=self.hard_budget_ms,
            confidence="partial" if timed_out else "coarse",
            limitations=(
                "Approximate EV only: deterministic Monte Carlo against uniform unknown opponent cards.",
                "No opponent private cards, authoritative hole-card events, revealed terminal cards, ranges, GTO/Nash, fold equity, or future betting model are used.",
                "Bet and raise EV use the legal minimum size and a one-street showdown approximation; amount semantics remain none/cost/by/to.",
            ),
            decision=identity,
        )

    def not_ready(
        self, *, decision_fingerprint: str, hand_id: str, sequence: int, street: Street
    ) -> FastSolverResultV1:
        started = self._clock()
        return self._unavailable(
            SolverDecisionIdentityV1(
                fingerprint=decision_fingerprint, hand_id=hand_id, sequence=sequence, street=street
            ),
            "not_hero_decision",
            "not_ready",
            started,
        )

    def sample_trial(self, observation: ObservationV1, *, seed: int) -> tuple[str, ...]:
        """Test-only sampling seam; callers never receive this private sample."""

        return self._sample_trial(observation, random.Random(seed))

    def _sample_trial(self, observation: ObservationV1, rng: random.Random) -> tuple[str, ...]:
        known = tuple(observation.own_hole_cards) + tuple(observation.board)
        count = (len(observation.active_seats) - 1) * 2 + (5 - len(observation.board))
        return known + tuple(rng.sample(deck(known), count))

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
        return Decimal("1") / keys.count(max(keys)) if hero_key == max(keys) else Decimal("0")

    def _candidate(
        self, action: LegalActionV1, observation: ObservationV1, equity: Decimal
    ) -> SolverCandidateV1:
        amount = None if action.min_amount is None else action.min_amount
        if action.action is SimulatorActionV1.FOLD:
            ev = Decimal("0")
        elif action.action is SimulatorActionV1.CHECK:
            ev = equity * Decimal(observation.pot)
        else:
            assert amount is not None
            cost = amount
            if action.amount_semantics is AmountSemanticsV1.TO:
                cost = amount - observation.street_commitments[observation.observer_seat]
            ev = equity * Decimal(observation.pot + cost) - Decimal(cost)
        return SolverCandidateV1(
            action=action.action,
            amount_semantics=action.amount_semantics,
            amount=amount,
            approximate_ev_chips=ev,
        )

    def _unavailable(
        self, identity: SolverDecisionIdentityV1, reason: str, status: Literal["unavailable", "not_ready"], started: float
    ) -> FastSolverResultV1:
        return FastSolverResultV1(
            status=status, iterations=0, elapsed_microseconds=max(0, int((self._clock() - started) * 1_000_000)),
            budget_ms=self.soft_budget_ms, hard_budget_ms=self.hard_budget_ms, confidence="unavailable", limitations=("Fast EV Solver L1 did not run; L0 Formula Advisor remains independent.",),
            decision=identity, unavailable_reason=reason,
        )

    @staticmethod
    def _seed(fingerprint: str) -> int:
        return int.from_bytes(hashlib.sha256(fingerprint.encode("utf-8")).digest()[:8], "big")
