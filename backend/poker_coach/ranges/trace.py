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

from collections.abc import Callable, Sequence
from decimal import Decimal

from poker_coach.domain.models import (
    Card,
    DecisionPoint,
    DomainModel,
    RangeSpec,
    ScenarioSpec,
    SeatNumber,
)

from .belief import (
    NoPolicyError,
    PolicySequenceMismatchError,
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
    providers: Sequence[ActionPolicyProvider] = (),
    max_sequence: int | None = None,
    pot_provider: Callable[[int], int | None] | None = None,
) -> RangeBeliefTrace:
    """Rebuild the seat's belief chain over scenario.action_history.

    ``max_sequence`` defaults to the scenario's decision point. ``provider``
    (single) or ``providers`` (ordered list, e.g. a preflop fixture followed
    by the postflop solver adapter) supply the action frequencies; the first
    provider that covers a node wins. When a step cannot be grounded (no
    policy / unsupported action / zero probability), the chain stops and the
    trace reports the reason.
    """
    if max_sequence is None:
        max_sequence = scenario.decision_point.after_sequence
    events = [
        event
        for event in scenario.action_history
        if event.sequence <= max_sequence
    ]
    provider_chain = tuple(providers) if providers else ((provider,) if provider is not None else ())
    # RangeSpec.dead_cards is a parse-time convenience and may have been
    # produced at a later street. Belief tracing derives dead cards solely
    # from the scenario's visible board and other seats' known cards.
    belief_prior_range = prior_range.model_copy(update={"dead_cards": ()})
    visible_board = board_at_sequence(scenario, 0)
    known_cards = dead_cards_for_belief(scenario, seat_id, visible_board)

    snapshot = snapshot_from_range(
        belief_prior_range,
        seat_id=seat_id,
        street=_street_for_sequence(scenario, 0),
        after_sequence=0,
        dead_cards=known_cards,
    )
    chain: list[RangeBeliefSnapshot] = [snapshot]

    applied_board_count = 0
    for event in events:
        if event.action_type.value in DEAL_ACTION_TYPES:
            board = board_at_sequence(scenario, event.sequence)
            if len(board) > applied_board_count:
                applied_board_count = len(board)
                snapshot = apply_dead_cards(
                    snapshot,
                    dead_cards_for_belief(scenario, seat_id, board),
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
        if not provider_chain:
            return _stalled(
                seat_id, chain, "no_policy",
                f"no grounded action policy is available for this node (seat {seat_id} at sequence {event.sequence})",
                event.sequence,
            )
        policy = None
        no_policy_message: str | None = None
        # Providers must see the exact action-time node. In particular, a
        # completed imported hand can carry a future runout in scenario.board;
        # passing that wholesale would both leak cards and reject preflop-only
        # curated policies for an otherwise valid historical action.
        policy_scenario = _scenario_at_action(scenario, event.sequence)
        for candidate in provider_chain:
            try:
                policy = candidate.get_action_frequencies(
                    policy_scenario, seat_id, event.sequence, tuple(snapshot.combos)
                )
                break
            except NoPolicyError as exc:
                no_policy_message = str(exc)
                continue
            except PolicySequenceMismatchError:
                # A solver artifact is intentionally node-scoped. In an
                # ordered provider chain it simply does not cover this
                # earlier/later action; another provider may still do so.
                continue
            except RangeBeliefError as exc:
                return _stalled(seat_id, chain, exc.code, str(exc), event.sequence)
        if policy is None:
            return _stalled(
                seat_id, chain, "no_policy",
                no_policy_message
                or f"no grounded action policy is available for this node (seat {seat_id} at sequence {event.sequence})",
                event.sequence,
            )
        try:
            pot_before = pot_provider(event.sequence) if pot_provider else None
            board = board_at_sequence(scenario, event.sequence)
            snapshot = update_range_belief(
                snapshot,
                event,
                policy,
                pot_before=pot_before,
                dead_cards=dead_cards_for_belief(scenario, seat_id, board),
            )
        except RangeBeliefError as exc:
            return _stalled(seat_id, chain, exc.code, str(exc), event.sequence)
        chain.append(snapshot)

    # Imported/static spots can have a board and no deal events. Apply only
    # the board visible at the requested endpoint; never use scenario.board
    # wholesale as a future-card fallback.
    endpoint_board = board_at_sequence(scenario, max_sequence)
    if len(endpoint_board) > applied_board_count:
        snapshot = apply_dead_cards(
            snapshot,
            dead_cards_for_belief(scenario, seat_id, endpoint_board),
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


def dead_cards_for_belief(
    scenario: ScenarioSpec,
    target_seat_id: int,
    visible_board: tuple[Card, ...] = (),
) -> tuple[Card, ...]:
    """Public dead-card contract for a seat's strategic range belief.

    Public board cards and known hole cards belonging to *other* seats block
    the target's range. The target's own known cards are intentionally not
    treated as dead cards: the belief is a strategic range, not a hand-
    conditioned equity calculation.
    """
    cards: list[str] = list(visible_board)
    for seat_id, seat_cards in scenario.known_hole_cards_by_seat.items():
        if seat_id != target_seat_id:
            cards.extend(seat_cards)
    return tuple(dict.fromkeys(cards))


def board_at_sequence(scenario: ScenarioSpec, sequence: int) -> tuple[Card, ...]:
    """Return public cards visible at an exact action-history sequence.

    Deal events are authoritative. For an imported static spot with no deal
    events, the board is visible only at the scenario's current endpoint;
    this permits a flop/turn/river spot without allowing that board to leak
    into earlier historical snapshots.
    """
    deals = [
        event
        for event in scenario.action_history
        if event.sequence <= sequence and event.action_type.value in DEAL_ACTION_TYPES
    ]
    if deals:
        revealed = max(_BOARD_SIZE_BY_DEAL[event.action_type.value] for event in deals)
        return tuple(scenario.board[:revealed])
    if sequence == scenario.decision_point.after_sequence:
        revealed = {
            "preflop": 0,
            "flop": 3,
            "turn": 4,
            "river": 5,
        }.get(scenario.decision_point.street.value, 0)
        return tuple(scenario.board[:revealed])
    return ()


def _street_for_sequence(scenario: ScenarioSpec, sequence: int) -> str:
    for event in reversed(scenario.action_history):
        if event.sequence <= sequence and event.action_type.value in DEAL_ACTION_TYPES:
            return event.street.value
    if sequence == scenario.decision_point.after_sequence:
        return scenario.decision_point.street.value
    return "preflop"


def _deal_label(action_type: str) -> str:
    return f"Deal {action_type.removeprefix('deal_')}"


def _scenario_at_action(scenario: ScenarioSpec, sequence: int) -> ScenarioSpec:
    """Provider input containing no state later than the observed action."""

    event = next(item for item in scenario.action_history if item.sequence == sequence)
    return scenario.model_copy(
        update={
            "action_history": tuple(
                item for item in scenario.action_history if item.sequence <= sequence
            ),
            "board": board_at_sequence(scenario, sequence),
            "decision_point": DecisionPoint(
                street=event.street,
                actor_seat=event.actor_seat,
                after_sequence=sequence,
            ),
        }
    )
