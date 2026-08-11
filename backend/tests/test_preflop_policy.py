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


def hu_scenario(events: list[dict]) -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
            "schemaVersion": 2,
            "gameVariant": "nlhe",
            "tableSize": 2,
            "smallBlind": 50,
            "bigBlind": 100,
            "buttonSeat": 0,
            "heroSeat": 0,
            "seats": [
                {"seatId": 0, "startingStack": 10_000, "position": "button"},
                {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
            ],
            "board": [],
            "actionHistory": events,
            "decisionPoint": {
                "street": "preflop",
                "actorSeat": events[-1]["actorSeat"],
                "afterSequence": len(events),
            },
            "assumptions": {"rakeAssumption": "no_rake"},
        }
    )
def hu_raise(sequence: int, actor_seat: int, amount: int) -> dict:
    return {
        "actionId": f"raise-{sequence}",
        "sequence": sequence,
        "street": "preflop",
        "actorSeat": actor_seat,
        "actionType": "raise_to",
        "amount": amount,
        "amountType": "to",
    }


def hu_call(sequence: int, actor_seat: int, amount: int) -> dict:
    return {
        "actionId": f"call-{sequence}",
        "sequence": sequence,
        "street": "preflop",
        "actorSeat": actor_seat,
        "actionType": "call",
        "amount": amount,
        "amountType": "cost",
    }


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


class TestHuCuratedPolicy:
    def test_btn_open_uses_the_project_owned_range_as_a_complete_2bb_table(self):
        scenario = hu_scenario([hu_raise(1, 0, 200)])

        policy = PreflopPolicyProvider().get_action_frequencies(
            scenario, 0, 1, ("AsAh", "Jc4d")
        )

        assert policy.source is PolicySource.PREFLOP_POLICY
        assert policy.confidence == "curated"
        assert policy.version == "hu-100bb-0.1"
        assert policy.actions == ("Raise(200)", "Fold")
        assert policy.frequencies["AsAh"] == {"Raise(200)": Decimal("1"), "Fold": Decimal("0")}
        assert policy.frequencies["Jc4d"] == {"Raise(200)": Decimal("0"), "Fold": Decimal("1")}
        assert all(sum(table.values()) == Decimal("1") for table in policy.frequencies.values())
        assert policy.assumptions == (
            "HU NLHE",
            "100BB effective stacks",
            "no ante / no rake",
            "BTN open fixed to the product default 2BB",
            "deterministic membership interpretation of default.btn_open.100bb",
        )
        assert policy.node == "preflop-policy/hu-100bb-0.1/hu-btn-open-2bb"

    def test_bb_defend_table_assigns_3bet_before_call_before_fold(self):
        scenario = hu_scenario([hu_raise(1, 0, 200), hu_raise(2, 1, 300)])

        policy = PreflopPolicyProvider().get_action_frequencies(
            scenario, 1, 2, ("AsAh", "7s6s", "Jc4d")
        )

        assert policy.actions == ("Raise(300)", "Call", "Fold")
        assert policy.frequencies["AsAh"] == {"Raise(300)": Decimal("1"), "Call": Decimal("0"), "Fold": Decimal("0")}
        assert policy.frequencies["7s6s"] == {"Raise(300)": Decimal("0"), "Call": Decimal("1"), "Fold": Decimal("0")}
        assert policy.frequencies["Jc4d"] == {"Raise(300)": Decimal("0"), "Call": Decimal("0"), "Fold": Decimal("1")}

    def test_btn_facing_the_default_3bet_assigns_4bet_before_call_before_fold(self):
        scenario = hu_scenario(
            [hu_raise(1, 0, 200), hu_raise(2, 1, 300), hu_raise(3, 0, 400)]
        )

        policy = PreflopPolicyProvider().get_action_frequencies(
            scenario, 0, 3, ("Ac5c", "KsQs", "Jc4d")
        )

        assert policy.actions == ("Raise(400)", "Call", "Fold")
        assert policy.frequencies["Ac5c"]["Raise(400)"] == Decimal("1")
        assert policy.frequencies["KsQs"]["Call"] == Decimal("1")
        assert policy.frequencies["Jc4d"]["Fold"] == Decimal("1")
        assert all(sum(table.values()) == Decimal("1") for table in policy.frequencies.values())

    def test_bb_vs_4bet_stays_unsupported_when_the_asset_has_no_action_allocation(self):
        scenario = hu_scenario(
            [
                hu_raise(1, 0, 200),
                hu_raise(2, 1, 300),
                hu_raise(3, 0, 400),
                hu_call(4, 1, 100),
            ]
        )

        with pytest.raises(NoPolicyError, match="continue range.*no action allocation"):
            PreflopPolicyProvider().get_action_frequencies(scenario, 1, 4, ("AsAh",))

    @pytest.mark.parametrize(
        ("scenario", "seat_id", "sequence", "message"),
        (
            (hu_scenario([hu_raise(1, 0, 220)]), 0, 1, "exact 2BB"),
            (hu_scenario([hu_call(1, 0, 50)]), 0, 1, "limp"),
            (
                hu_scenario(
                    [
                        hu_call(1, 0, 50),
                        {
                            "actionId": "bb-option",
                            "sequence": 2,
                            "street": "preflop",
                            "actorSeat": 1,
                            "actionType": "check",
                        },
                    ]
                ),
                1,
                2,
                "BB option",
            ),
        ),
    )
    def test_hu_unsupported_nodes_return_specific_no_policy_reasons(
        self, scenario, seat_id, sequence, message
    ):
        with pytest.raises(NoPolicyError, match=message):
            PreflopPolicyProvider().get_action_frequencies(scenario, seat_id, sequence, ("AsAh",))
