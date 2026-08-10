"""Solver-backed policy adapter.

Consumes an existing ``SolveResult`` (normalized solver output) as a policy
source: each dumped node's per-combo strategy becomes a full
combo x action frequency table. No solver math is recomputed — this is a
pure ``Solver output -> policy abstraction`` mapping.

The sidecar is heads-up postflop: the root node is the OOP player's
decision (player 0) and the response node is the IP player's decision
(player 1). The adapter maps seat ids onto those nodes.
"""

from __future__ import annotations

from decimal import Decimal

from poker_coach.domain.models import ScenarioSpec
from poker_coach.solver.types import SolverNode, SolveResult

from ..belief import NoPolicyError, PolicySource
from ..policy import PolicyResult


class SolverPolicyAdapter:
    """Serve a SolveResult's strategy tables as an ActionPolicyProvider."""

    def __init__(
        self,
        result: SolveResult,
        *,
        oop_seat: int,
        ip_seat: int,
        reference_pot: int | None = None,
    ):
        self._result = result
        self._oop_seat = oop_seat
        self._ip_seat = ip_seat
        self._reference_pot = reference_pot

    def node_for_seat(self, seat_id: int) -> SolverNode | None:
        if seat_id == self._oop_seat:
            return self._result.root
        if seat_id == self._ip_seat:
            return self._result.response_node
        return None

    def get_action_frequencies(
        self,
        scenario: ScenarioSpec,
        seat_id: int,
        sequence: int,
        combos: tuple[str, ...],
    ) -> PolicyResult:
        node = self.node_for_seat(seat_id)
        if node is None:
            raise NoPolicyError(
                f"solver result has no node for seat {seat_id} "
                f"(expected oop={self._oop_seat} or ip={self._ip_seat})"
            )
        frequencies: dict[str, dict[str, Decimal]] = {}
        for hand in node.hands:
            frequencies[hand.combo] = {
                action: Decimal(str(frequency))
                for action, frequency in hand.strategy.items()
            }
        return PolicyResult(
            source=PolicySource.SOLVER,
            actions=tuple(node.actions),
            frequencies=frequencies,
            likelihood_only=False,
            reference_pot=self._reference_pot,
            node=scenario.decision_point.street.value,
        )
