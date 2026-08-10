"""Deterministic fixture policy provider for tests and manual overrides.

Accepts per-combo frequency tables keyed by observed action type:

    {
        "raise_to": {
            "AA":  {"raise": "1"},
            "JJ":  {"raise": "0.8"},
            "76s": {"raise": "0.7"},
            "J4o": {"raise": "0.05"},
        },
    }

Keys may be starting-hand notation (``AA``, ``76s``, ``J4o``) or concrete
combos (``AsAh``). Starting-hand keys expand to every concrete combo. The
tables are likelihood-only: each combo's frequencies are the probability of
the observed action given the combo, not a full strategy split.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from poker_coach.analysis.range_analysis import expand_range
from poker_coach.domain.models import RangeSource, RangeSpec, ScenarioSpec

from ..belief import InvalidPolicyError, NoPolicyError, PolicySource, combo_key
from ..policy import PolicyResult


class FixturePolicyProvider:
    """Action-type -> combo frequency table provider (deterministic)."""

    def __init__(self, policies: Mapping[str, Mapping[str, Mapping[str, Any]]]):
        self._policies = _normalize_policies(policies)

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
        table = self._policies.get(event.action_type.value)
        if table is None:
            raise NoPolicyError(
                f"no fixture policy is attached to action type "
                f"{event.action_type.value} for seat {seat_id}"
            )
        action_labels = tuple(next(iter(table.values())).keys())
        return PolicyResult(
            source=PolicySource.FIXTURE,
            actions=action_labels,
            frequencies=table,
            likelihood_only=True,
            node=event.action_type.value,
        )


def _action_at(scenario: ScenarioSpec, seat_id: int, sequence: int):
    for event in scenario.action_history:
        if event.sequence == sequence and event.actor_seat == seat_id:
            return event
    return None


def _normalize_policies(
    policies: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, dict[str, Decimal]]]:
    normalized: dict[str, dict[str, dict[str, Decimal]]] = {}
    for action_type, combo_tables in policies.items():
        if not isinstance(action_type, str) or not action_type:
            raise InvalidPolicyError("fixture policy keys must be action type strings")
        combo_map: dict[str, dict[str, Decimal]] = {}
        expected_labels: frozenset[str] | None = None
        for key, table in combo_tables.items():
            if not isinstance(table, Mapping) or not table:
                raise InvalidPolicyError(f"fixture table for {key} must be a non-empty mapping")
            action_frequencies: dict[str, Decimal] = {}
            for label, raw in table.items():
                try:
                    frequency = Decimal(str(raw))
                except Exception as exc:  # Decimal supplies the detail
                    raise InvalidPolicyError(f"invalid fixture frequency for {key} {label}") from exc
                if frequency < 0 or frequency > 1:
                    raise InvalidPolicyError(
                        f"fixture frequency {frequency} out of range for {key} {label}"
                    )
                action_frequencies[str(label)] = frequency
            labels = frozenset(action_frequencies)
            if expected_labels is None:
                expected_labels = labels
            elif labels != expected_labels:
                raise InvalidPolicyError(
                    f"fixture combos must share the same action labels; {key} "
                    f"has {sorted(labels)} expected {sorted(expected_labels)}"
                )
            for combo in _expand_key(key):
                combo_map[combo] = dict(action_frequencies)
        normalized[action_type] = combo_map
    return normalized


_RANKS = frozenset("23456789TJQKA")
_SUITS = frozenset("cdhs")


def _expand_key(key: str) -> tuple[str, ...]:
    """Expand a starting-hand or concrete-combo key into canonical combos."""
    if (
        len(key) == 4
        and key[0] in _RANKS
        and key[1] in _SUITS
        and key[2] in _RANKS
        and key[3] in _SUITS
    ):
        # Concrete combo ("AsAh"): canonicalize the card order.
        return (combo_key((key[:2], key[2:])),)
    try:
        spec = RangeSpec(
            range_id="fixture-key",
            name="fixture key",
            version="1",
            source=RangeSource.CURATED,
            matrix169={key: Decimal("1")},
        )
    except Exception as exc:  # pydantic supplies the detail
        raise InvalidPolicyError(f"invalid fixture combo key: {key!r}") from exc
    return tuple(combo_key(weighted.cards) for weighted in expand_range(spec))
