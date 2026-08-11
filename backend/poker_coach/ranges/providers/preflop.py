"""Versioned, deliberately narrow 8-max preflop policy baseline.

This is a first-party curated baseline, not a solver export.  It covers only
the exact, raise-first-in node declared below: 8-max NLHE, 100BB effective
stacks, no ante/rake, and a 2.5BB open.  Any other preflop node raises
``NoPolicyError`` so callers can report unavailable belief rather than
silently applying a nearby range.

The policy is complete for every requested concrete combo: an opening hand
raises at frequency one and folds at frequency zero; all remaining hands do
the inverse.  The deterministic split makes the policy useful for action-
conditioned range reconstruction while preserving an honest ``curated``
confidence label.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from poker_coach.analysis.range_analysis import expand_range, range_spec_from_notation
from poker_coach.domain.models import ActionEvent, ActionType, RangeSource, ScenarioSpec, SeatPosition

from ..belief import NoPolicyError, PolicySource, combo_key
from ..policy import PolicyResult


PREFLOP_POLICY_VERSION = "8max-rfi-100bb-0.1"
_OPEN_MULTIPLIER = 5  # 2.5BB expressed as an integer ratio (2.5 = 5 / 2).

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
    """Serve the exact 8-max 100BB raise-first-in policy baseline."""

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
