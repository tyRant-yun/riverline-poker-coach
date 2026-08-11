"""Versioned first-party curated preflop policy baselines.

This provider never represents Solver/GTO output. It contains the existing
exact 8-max RFI baseline plus a small HU product interpretation of the
project-owned default ranges. Those HU assets provide positive range weights,
not action mixes, so each supported HU node is deterministic: the
action-specific range receives frequency one and all other combinations
receive the remaining declared action. The exact default UI sizes are node
assumptions, not claims about external strategy frequencies.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from poker_coach.analysis.range_analysis import expand_range, range_spec_from_notation
from poker_coach.domain.models import ActionEvent, ActionType, RangeSource, ScenarioSpec, SeatPosition
from poker_coach.strategy.ranges import default_preflop_ranges

from ..belief import NoPolicyError, PolicySource, combo_key
from ..policy import PolicyResult


PREFLOP_POLICY_VERSION = "8max-rfi-100bb-0.1"
HU_PREFLOP_POLICY_VERSION = "hu-100bb-0.1"
_OPEN_MULTIPLIER = 5  # 2.5BB expressed as an integer ratio (2.5 = 5 / 2).
_HU_OPEN_SIZE = 200
_HU_THREE_BET_SIZE = 300
_HU_FOUR_BET_SIZE = 400
_HU_ASSUMPTIONS = (
    "HU NLHE",
    "100BB effective stacks",
    "no ante / no rake",
)

# These are deliberately explicit first-party baseline assumptions rather
# than inferred frequencies.  Keeping the source notation here makes review
# and future versioning of each position's policy straightforward.
_RFI_NOTATION_BY_POSITION: dict[SeatPosition, str] = {
    SeatPosition.UTG: "77+ AJs+ KQs AKo",
    SeatPosition.UTG_PLUS_1: "66+ ATs+ KQs KJs+ QJs AKo AQo+",
    SeatPosition.MP: "55+ A9s+ KTs+ QTs+ JTs AJo+ KQo",
    SeatPosition.HJ: "44+ A7s+ K9s+ Q9s+ J9s+ T9s 98s ATo+ KJo+ QJo",
    SeatPosition.CUTOFF: "22+ A2s+ K7s+ Q8s+ J8s+ T8s+ 98s 87s 76s A8o+ KTo+ QTo+ JTo",
    SeatPosition.BUTTON: "22+ A2s+ K2s+ Q5s+ J7s+ T7s+ 97s+ 86s+ 76s 65s 54s A2o+ K8o+ Q9o+ J9o+ T9o",
    SeatPosition.SMALL_BLIND: "22+ A2s+ K5s+ Q7s+ J7s+ T7s+ 97s+ 86s+ 75s+ 65s 54s A8o+ KTo+ QTo+ JTo",
}


class PreflopPolicyProvider:
    """Serve exact 8-max RFI and deliberately narrow HU curated nodes."""

    def get_action_frequencies(
        self,
        scenario: ScenarioSpec,
        seat_id: int,
        sequence: int,
        combos: tuple[str, ...],
    ) -> PolicyResult:
        event = _action_at(scenario, seat_id, sequence)
        if event is None:
            raise NoPolicyError(
                f"no action event found for seat {seat_id} at sequence {sequence}"
            )
        if scenario.table_size == 2:
            return _hu_policy_for_event(scenario, event, combos)
        position = _rfi_position_for_event(scenario, event)
        opening_combos = _opening_combos(position)
        raise_label = f"Raise({scenario.big_blind * _OPEN_MULTIPLIER // 2})"
        frequencies = {
            combo: {
                raise_label: Decimal("1") if combo in opening_combos else Decimal("0"),
                "Fold": Decimal("0") if combo in opening_combos else Decimal("1"),
            }
            for combo in combos
        }
        return PolicyResult(
            source=PolicySource.PREFLOP_POLICY,
            actions=(raise_label, "Fold"),
            frequencies=frequencies,
            node=(
                f"preflop-policy/{PREFLOP_POLICY_VERSION}/"
                f"8max-rfi-{position.value}-2.5bb"
            ),
            version=PREFLOP_POLICY_VERSION,
            assumptions=(
                "8-max NLHE",
                "100BB effective stacks",
                "no ante / no rake",
                "raise first in",
                "open fixed to 2.5BB",
                f"deterministic membership interpretation of {position.value} RFI baseline",
            ),
            reference_pot=scenario.small_blind + scenario.big_blind,
            confidence="curated",
        )


def _action_at(scenario: ScenarioSpec, seat_id: int, sequence: int):
    for event in scenario.action_history:
        if event.sequence == sequence and event.actor_seat == seat_id:
            return event
    return None


def _rfi_position_for_event(scenario: ScenarioSpec, event: ActionEvent) -> SeatPosition:
    if scenario.table_size != 8:
        raise NoPolicyError("8-max preflop policy only covers tableSize=8")
    if scenario.ante != 0 or scenario.rake_config.enabled or scenario.assumptions.rake_assumption != "no_rake":
        raise NoPolicyError("8-max preflop policy only covers no-ante, no-rake spots")
    expected_stack = scenario.big_blind * 100
    if any(seat.starting_stack != expected_stack for seat in scenario.seats):
        raise NoPolicyError("8-max preflop policy only covers exactly 100BB starting stacks")
    if scenario.board or event.street.value != "preflop":
        raise NoPolicyError("8-max preflop policy only covers preflop nodes with no board")
    if event.action_type not in (ActionType.RAISE_TO, ActionType.FOLD):
        raise NoPolicyError("8-max RFI policy only covers raise_to or fold actions")
    if event.action_type is ActionType.RAISE_TO and event.amount != scenario.big_blind * _OPEN_MULTIPLIER // 2:
        raise NoPolicyError("8-max RFI policy only covers an exact 2.5BB open size")
    earlier_voluntary = tuple(
        item
        for item in scenario.action_history
        if item.sequence < event.sequence and item.action_type is not ActionType.POST_BLIND
    )
    if any(item.action_type is not ActionType.FOLD for item in earlier_voluntary):
        raise NoPolicyError("8-max RFI policy requires no earlier voluntary entry into the pot")
    position = next(seat.position for seat in scenario.seats if seat.seat_id == event.actor_seat)
    if position not in _RFI_NOTATION_BY_POSITION:
        raise NoPolicyError("8-max RFI policy has no big-blind option coverage")
    rfi_seats = tuple(
        next(seat.seat_id for seat in scenario.seats if seat.position is rfi_position)
        for rfi_position in _RFI_NOTATION_BY_POSITION
    )
    expected_folders = rfi_seats[: rfi_seats.index(event.actor_seat)]
    actual_folders = tuple(item.actor_seat for item in earlier_voluntary)
    if actual_folders != expected_folders:
        raise NoPolicyError(
            "8-max RFI policy requires folds from every earlier position"
        )
    return position


def _hu_policy_for_event(
    scenario: ScenarioSpec,
    event: ActionEvent,
    combos: tuple[str, ...],
) -> PolicyResult:
    _validate_hu_baseline(scenario, event)
    events = scenario.action_history
    button_seat = scenario.button_seat
    big_blind_seat = next(seat.seat_id for seat in scenario.seats if seat.seat_id != button_seat)

    if event.sequence == 1:
        if event.actor_seat != button_seat:
            raise NoPolicyError("HU curated policy requires the BTN to act first")
        if event.action_type is ActionType.CALL:
            raise NoPolicyError("HU limp is intentionally unsupported by the curated policy")
        if event.action_type not in {ActionType.RAISE_TO, ActionType.FOLD}:
            raise NoPolicyError("HU BTN opening node only covers raise_to or fold")
        if event.action_type is ActionType.RAISE_TO and event.amount != _HU_OPEN_SIZE:
            raise NoPolicyError("HU BTN opening policy only covers the product default exact 2BB size")
        return _binary_membership_policy(
            combos=combos,
            action_label=f"Raise({_HU_OPEN_SIZE})",
            range_key="btn_open",
            node="hu-btn-open-2bb",
            reference_pot=scenario.small_blind + scenario.big_blind,
            assumptions=_HU_ASSUMPTIONS
            + (
                "BTN open fixed to the product default 2BB",
                "deterministic membership interpretation of default.btn_open.100bb",
            ),
        )

    if event.sequence == 2 and _is_raise(events[0], button_seat, _HU_OPEN_SIZE):
        if event.actor_seat != big_blind_seat:
            raise NoPolicyError("HU BTN open response must be the big blind")
        if event.action_type not in {ActionType.RAISE_TO, ActionType.CALL, ActionType.FOLD}:
            raise NoPolicyError("HU BB response only covers fold, call, or the product default 3BB three-bet")
        if event.action_type is ActionType.RAISE_TO and event.amount != _HU_THREE_BET_SIZE:
            raise NoPolicyError("HU BB response only covers the product default exact 3BB three-bet size")
        return _tiered_membership_policy(
            combos=combos,
            actions=(f"Raise({_HU_THREE_BET_SIZE})", "Call", "Fold"),
            highest_range_key="bb_3bet",
            middle_range_key="bb_defend",
            node="hu-bb-vs-btn-open-2bb",
            reference_pot=300,
            assumptions=_HU_ASSUMPTIONS
            + (
                "BTN open fixed to 2BB",
                "BB three-bet fixed to the product default 3BB",
                "deterministic priority: default.bb_3bet.100bb, then default.bb_defend.100bb",
            ),
        )

    if (
        event.sequence == 3
        and _is_raise(events[0], button_seat, _HU_OPEN_SIZE)
        and _is_raise(events[1], big_blind_seat, _HU_THREE_BET_SIZE)
    ):
        if event.actor_seat != button_seat:
            raise NoPolicyError("HU three-bet response must return action to the BTN")
        if event.action_type not in {ActionType.RAISE_TO, ActionType.CALL, ActionType.FOLD}:
            raise NoPolicyError("HU BTN vs three-bet only covers fold, call, or the product default 4BB four-bet")
        if event.action_type is ActionType.RAISE_TO and event.amount != _HU_FOUR_BET_SIZE:
            raise NoPolicyError("HU BTN vs three-bet only covers the product default exact 4BB four-bet size")
        return _tiered_membership_policy(
            combos=combos,
            actions=(f"Raise({_HU_FOUR_BET_SIZE})", "Call", "Fold"),
            highest_range_key="btn_4bet",
            middle_range_key="btn_vs_3bet",
            node="hu-btn-vs-bb-3bet-3bb",
            reference_pot=500,
            assumptions=_HU_ASSUMPTIONS
            + (
                "BTN open fixed to 2BB",
                "BB three-bet fixed to 3BB",
                "BTN four-bet fixed to the product default 4BB",
                "deterministic priority: default.btn_4bet.100bb, then default.btn_vs_3bet.100bb",
            ),
        )

    if (
        event.sequence == 4
        and _is_raise(events[0], button_seat, _HU_OPEN_SIZE)
        and _is_raise(events[1], big_blind_seat, _HU_THREE_BET_SIZE)
        and _is_raise(events[2], button_seat, _HU_FOUR_BET_SIZE)
        and event.actor_seat == big_blind_seat
    ):
        raise NoPolicyError(
            "HU BB vs four-bet is unsupported: default.bb-vs-4bet.100bb is a continue range with no action allocation (call vs five-bet vs fold)"
        )

    raise NoPolicyError(
        "HU curated policy has no exact node for this action history; limp, BB option, non-default sizes, and later branches remain unsupported"
    )


def _validate_hu_baseline(scenario: ScenarioSpec, event: ActionEvent) -> None:
    if scenario.ante != 0 or scenario.rake_config.enabled or scenario.assumptions.rake_assumption != "no_rake":
        raise NoPolicyError("HU curated policy only covers no-ante, no-rake spots")
    expected_stack = scenario.big_blind * 100
    if any(seat.starting_stack != expected_stack for seat in scenario.seats):
        raise NoPolicyError("HU curated policy only covers exactly 100BB starting stacks")
    if scenario.board or event.street.value != "preflop":
        raise NoPolicyError("HU curated policy only covers preflop nodes with no board")


def _is_raise(event: ActionEvent, actor_seat: int, amount: int) -> bool:
    return (
        event.actor_seat == actor_seat
        and event.action_type is ActionType.RAISE_TO
        and event.amount == amount
    )


def _binary_membership_policy(
    *,
    combos: tuple[str, ...],
    action_label: str,
    range_key: str,
    node: str,
    reference_pot: int,
    assumptions: tuple[str, ...],
) -> PolicyResult:
    in_action_range = _default_range_combos(range_key)
    return PolicyResult(
        source=PolicySource.PREFLOP_POLICY,
        actions=(action_label, "Fold"),
        frequencies={
            combo: {
                action_label: Decimal("1") if combo in in_action_range else Decimal("0"),
                "Fold": Decimal("0") if combo in in_action_range else Decimal("1"),
            }
            for combo in combos
        },
        node=f"preflop-policy/{HU_PREFLOP_POLICY_VERSION}/{node}",
        version=HU_PREFLOP_POLICY_VERSION,
        assumptions=assumptions,
        reference_pot=reference_pot,
        confidence="curated",
    )


def _tiered_membership_policy(
    *,
    combos: tuple[str, ...],
    actions: tuple[str, str, str],
    highest_range_key: str,
    middle_range_key: str,
    node: str,
    reference_pot: int,
    assumptions: tuple[str, ...],
) -> PolicyResult:
    highest = _default_range_combos(highest_range_key)
    middle = _default_range_combos(middle_range_key)
    raise_label, call_label, fold_label = actions
    frequencies: dict[str, dict[str, Decimal]] = {}
    for combo in combos:
        selected = raise_label if combo in highest else call_label if combo in middle else fold_label
        frequencies[combo] = {
            action: Decimal("1") if action == selected else Decimal("0")
            for action in actions
        }
    return PolicyResult(
        source=PolicySource.PREFLOP_POLICY,
        actions=actions,
        frequencies=frequencies,
        node=f"preflop-policy/{HU_PREFLOP_POLICY_VERSION}/{node}",
        version=HU_PREFLOP_POLICY_VERSION,
        assumptions=assumptions,
        reference_pot=reference_pot,
        confidence="curated",
    )


@lru_cache(maxsize=None)
def _opening_combos(position: SeatPosition) -> frozenset[str]:
    notation = _RFI_NOTATION_BY_POSITION[position]
    range_spec = range_spec_from_notation(
        notation,
        range_id=f"preflop-policy.{PREFLOP_POLICY_VERSION}.{position.value}.rfi",
        name=f"8-max {position.value} RFI 100BB",
        version=PREFLOP_POLICY_VERSION,
        source=RangeSource.CURATED,
    )
    return frozenset(combo_key(weighted.cards) for weighted in expand_range(range_spec))


@lru_cache(maxsize=None)
def _default_range_combos(range_key: str) -> frozenset[str]:
    """Expand only the existing project-owned positive default weights."""
    try:
        range_spec = default_preflop_ranges()[range_key]
    except KeyError as exc:
        raise NoPolicyError(f"project default range {range_key!r} is unavailable") from exc
    return frozenset(
        combo_key(weighted.cards)
        for weighted in expand_range(range_spec)
        if weighted.weight > 0
    )
