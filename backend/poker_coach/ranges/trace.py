"""Multi-step belief trace: rebuild a seat's snapshot chain from the action
history.

Snapshots are generated only when the tracked seat acts, when public cards
change (street deals), or at the initial prior. Other seats' actions do not
change this seat's belief and produce no snapshot.

When a step has no grounded policy (or the observed action is unsupported /
zero-probability), the chain stops: no further snapshot is fabricated and
the trace is marked unavailable with the reason code.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from poker_coach.domain.models import (
    Card,
    DomainModel,
    RangeSpec,
    ScenarioSpec,
    SeatNumber,
)

from .belief import (
    NoPolicyError,
    RangeBeliefError,
    RangeBeliefSnapshot,
    snapshot_id_for,
)
from .policy import ActionPolicyProvider
from .update import (
    POLICY_ACTION_TYPES,
    apply_dead_cards,
    snapshot_from_range,
    update_range_belief,
)

DEAL_ACTION_TYPES = frozenset({"deal_flop", "deal_turn", "deal_river"})
_BOARD_SIZE_BY_DEAL = {"deal_flop": 3, "deal_turn": 4, "deal_river": 5}


class RangeBeliefTrace(DomainModel):
    """The ordered snapshot chain for one seat up to a sequence."""

    seat_id: SeatNumber
    snapshots: tuple[RangeBeliefSnapshot, ...]
    available: bool = True
    unavailable_reason: str | None = None
    stalled_at_sequence: int | None = None

    @property
    def prior(self) -> RangeBeliefSnapshot | None:
        return self.snapshots[0] if self.snapshots else None

    @property
    def current(self) -> RangeBeliefSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None


def build_range_trace(
    scenario: ScenarioSpec,
    seat_id: int,
    *,
    prior_range: RangeSpec,
    provider: ActionPolicyProvider | None = None,
    max_sequence: int | None = None,
    pot_provider: Callable[[int], int | None] | None = None,
) -> RangeBeliefTrace:
    """Rebuild the seat's belief chain over scenario.action_history.

    ``max_sequence`` defaults to the scenario's decision point. When a step
    cannot be grounded (no policy / unsupported action / zero probability),
    the chain stops and the trace reports the reason.
    """
    if max_sequence is None:
        max_sequence = scenario.decision_point.after_sequence
    events = [
        event
        for event in scenario.action_history
        if event.sequence <= max_sequence
    ]
    known_cards = _known_cards(scenario)

    snapshot = snapshot_from_range(
        prior_range,
        seat_id=seat_id,
        street=_street_for_sequence(scenario, 0),
        after_sequence=0,
        dead_cards=known_cards,
    )
    chain: list[RangeBeliefSnapshot] = [snapshot]

    applied_board_count = 0
    for event in events:
        if event.action_type.value in DEAL_ACTION_TYPES:
            board = _board_at_sequence(scenario, event.sequence)
            if len(board) > applied_board_count:
                applied_board_count = len(board)
                snapshot = apply_dead_cards(
                    snapshot,
                    tuple(known_cards) + board,
                    street=event.street,
                    after_sequence=event.sequence,
                    action_type=event.action_type.value,
                    action_label=_deal_label(event.action_type.value),
                )
                chain.append(snapshot)
            continue
        if event.action_type.value not in POLICY_ACTION_TYPES or event.actor_seat != seat_id:
            continue
        # The tracked seat acts: the belief must be updated through a policy.
        if provider is None:
            return _stalled(
                seat_id, chain, "no_policy",
                f"no grounded action policy is available for this node (seat {seat_id} at sequence {event.sequence})",
                event.sequence,
            )
        try:
            policy = provider.get_action_frequencies(
                scenario, seat_id, event.sequence, tuple(snapshot.combos)
            )
        except NoPolicyError as exc:
            return _stalled(seat_id, chain, "no_policy", str(exc), event.sequence)
        except RangeBeliefError as exc:
            return _stalled(seat_id, chain, exc.code, str(exc), event.sequence)
        try:
            pot_before = pot_provider(event.sequence) if pot_provider else None
            board = _board_at_sequence(scenario, event.sequence)
            snapshot = update_range_belief(
                snapshot,
                event,
                policy,
                pot_before=pot_before,
                dead_cards=tuple(known_cards) + board,
            )
        except RangeBeliefError as exc:
            return _stalled(seat_id, chain, exc.code, str(exc), event.sequence)
        chain.append(snapshot)

    # A hand loaded with board cards but without deal events (or a trace
    # ending after the board was set) still filters the final belief.
    if len(scenario.board) > applied_board_count:
        snapshot = apply_dead_cards(
            snapshot,
            tuple(known_cards) + tuple(scenario.board),
            street=_street_for_sequence(scenario, max_sequence),
            after_sequence=max_sequence,
            action_type="deal",
            action_label=f"Deal {_street_for_sequence(scenario, max_sequence).value}",
        )
        chain.append(snapshot)

    return RangeBeliefTrace(seat_id=seat_id, snapshots=tuple(chain))


def _stalled(
    seat_id: int,
    chain: list[RangeBeliefSnapshot],
    reason: str,
    message: str,
    sequence: int,
) -> RangeBeliefTrace:
    return RangeBeliefTrace(
        seat_id=seat_id,
        snapshots=tuple(chain),
        available=False,
        unavailable_reason=f"{reason}: {message}",
        stalled_at_sequence=sequence,
    )


def _known_cards(scenario: ScenarioSpec) -> tuple[Card, ...]:
    # knownHoleCardsBySeat is the canonical source; the domain validator
    # normalizes the legacy hero/villain fields into it.
    cards: list[str] = []
    for seat_cards in scenario.known_hole_cards_by_seat.values():
        cards.extend(seat_cards)
    return tuple(dict.fromkeys(cards))


def _board_at_sequence(scenario: ScenarioSpec, sequence: int) -> tuple[Card, ...]:
    deals = [
        event
        for event in scenario.action_history
        if event.sequence <= sequence and event.action_type.value in DEAL_ACTION_TYPES
    ]
    if not deals:
        return ()
    revealed = max(_BOARD_SIZE_BY_DEAL[event.action_type.value] for event in deals)
    return tuple(scenario.board[:revealed])


def _street_for_sequence(scenario: ScenarioSpec, sequence: int) -> str:
    for event in reversed(scenario.action_history):
        if event.sequence <= sequence and event.action_type.value in DEAL_ACTION_TYPES:
            return event.street.value
    return "preflop"


def _deal_label(action_type: str) -> str:
    return f"Deal {action_type.removeprefix('deal_')}"
