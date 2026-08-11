"""Tests for the deliberately narrow 8-max curated RFI policy provider."""

from __future__ import annotations

from decimal import Decimal

import pytest

from poker_coach.domain.models import (
    ActionEvent,
    ActionType,
    AmountType,
    ScenarioSpec,
    Street,
    positions_for_table,
)
from poker_coach.ranges import NoPolicyError, PolicySource, PreflopPolicyProvider


def rfi_scenario(*, actor_seat: int = 3, amount: int = 250, table_size: int = 8) -> ScenarioSpec:
    positions = positions_for_table(table_size)
    rfi_seats = (3, 4, 5, 6, 7, 0, 1)
    prior_folders = rfi_seats[: rfi_seats.index(actor_seat)] if actor_seat in rfi_seats else ()
    events = [
        {
            "actionId": f"fold-{seat_id}",
            "sequence": sequence,
            "street": "preflop",
            "actorSeat": seat_id,
            "actionType": "fold",
        }
        for sequence, seat_id in enumerate(prior_folders, start=1)
    ]
    events.append(
        {
            "actionId": "open",
            "sequence": len(events) + 1,
            "street": "preflop",
            "actorSeat": actor_seat,
            "actionType": "raise_to",
            "amount": amount,
            "amountType": "to",
        }
    )
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": table_size,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": actor_seat,
            "seats": [
                {
                    "seatId": seat_id,
                    "startingStack": 10_000,
                    "position": position.value,
                }
                for seat_id, position in enumerate(positions)
            ],
            "board": [],
            "actionHistory": events,
            "decisionPoint": {
                "street": "preflop",
                "actorSeat": actor_seat,
                "afterSequence": len(events),
            },
            "assumptions": {},
        }
    )


class TestPreflopPolicyProvider:
    def test_utg_rfi_returns_a_complete_curated_policy(self):
        scenario = rfi_scenario()
        policy = PreflopPolicyProvider().get_action_frequencies(
            scenario, 3, 1, ("AsAh", "Ac5c", "7s6s")
        )

        assert policy.source is PolicySource.PREFLOP_POLICY
        assert policy.confidence == "curated"
        assert policy.actions == ("Raise(250)", "Fold")
        assert policy.reference_pot == 150
        assert policy.frequencies["AsAh"] == {
            "Raise(250)": Decimal("1"),
            "Fold": Decimal("0"),
        }
        assert policy.frequencies["Ac5c"] == {
            "Raise(250)": Decimal("0"),
            "Fold": Decimal("1"),
        }
        assert all(sum(table.values()) == Decimal("1") for table in policy.frequencies.values())
        assert "8max-rfi-utg-2.5bb" in (policy.node or "")

    @pytest.mark.parametrize("actor_seat", (3, 4, 5, 6, 7, 0, 1))
    def test_every_non_bb_8max_position_has_rfi_coverage(self, actor_seat):
        scenario = rfi_scenario(actor_seat=actor_seat)
        policy = PreflopPolicyProvider().get_action_frequencies(
            scenario, actor_seat, scenario.decision_point.after_sequence, ("AsAh",)
        )
        assert policy.frequencies["AsAh"]["Raise(250)"] == Decimal("1")

    def test_rejects_nearby_nodes_instead_of_guessing(self):
        provider = PreflopPolicyProvider()
        with pytest.raises(NoPolicyError, match="2.5BB"):
            provider.get_action_frequencies(rfi_scenario(amount=220), 3, 1, ("AsAh",))
        with pytest.raises(NoPolicyError, match="big-blind option"):
            provider.get_action_frequencies(rfi_scenario(actor_seat=2), 2, 1, ("AsAh",))
        with pytest.raises(NoPolicyError, match="tableSize=8"):
            provider.get_action_frequencies(rfi_scenario(table_size=6, actor_seat=3), 3, 1, ("AsAh",))

    def test_rejects_later_position_without_the_required_folds(self):
        scenario = rfi_scenario(actor_seat=7)
        scenario = scenario.model_copy(update={"action_history": (scenario.action_history[-1],)})
        with pytest.raises(NoPolicyError, match="folds from every earlier position"):
            PreflopPolicyProvider().get_action_frequencies(scenario, 7, 5, ("AsAh",))

    def test_rejects_a_node_with_an_earlier_open(self):
        scenario = rfi_scenario(actor_seat=7)
        scenario = scenario.model_copy(
            update={
                "action_history": (
                    ActionEvent(
                        action_id="earlier-open",
                        sequence=1,
                        street=Street.PREFLOP,
                        actor_seat=3,
                        action_type=ActionType.RAISE_TO,
                        amount=250,
                        amount_type=AmountType.TO,
                    ),
                    ActionEvent(
                        action_id="later-action",
                        sequence=2,
                        street=Street.PREFLOP,
                        actor_seat=7,
                        action_type=ActionType.RAISE_TO,
                        amount=250,
                        amount_type=AmountType.TO,
                    ),
                )
            }
        )
        with pytest.raises(NoPolicyError, match="no earlier voluntary entry"):
            PreflopPolicyProvider().get_action_frequencies(scenario, 7, 2, ("AsAh",))
