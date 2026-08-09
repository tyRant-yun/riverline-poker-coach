from decimal import Decimal

import pytest
from pydantic import ValidationError

from poker_coach.domain.models import (
    ActionEvent,
    ActionType,
    AmountType,
    AnalysisLevel,
    EvidenceBundle,
    EvidenceItem,
    RangeCombo,
    RangeSource,
    RangeSpec,
    ScenarioSpec,
    Street,
    TeachingResponse,
    TeachingText,
    ValidationReport,
)


def minimal_scenario(**overrides):
    payload = {
        "schemaVersion": 1,
        "gameVariant": "nlhe",
        "tableSize": 2,
        "smallBlind": 50,
        "bigBlind": 100,
        "ante": 0,
        "buttonSeat": 0,
        "heroSeat": 0,
        "seats": [
            {"seatId": 0, "startingStack": 10_000, "position": "button"},
            {"seatId": 1, "startingStack": 10_000, "position": "big_blind"},
        ],
        "heroHoleCards": ["as", "kd"],
        "board": [],
        "actionHistory": [],
        "decisionPoint": {"street": "preflop", "actorSeat": 0, "afterSequence": 0},
        "allowedBetSizes": [],
        "assumptions": {},
        "source": "manual",
        "tags": [],
    }
    payload.update(overrides)
    return payload


def test_scenario_normalizes_cards_and_serializes_deterministically():
    first = ScenarioSpec.model_validate(minimal_scenario())
    second = ScenarioSpec.model_validate({**minimal_scenario(), "tags": ["z", "a"]})

    assert first.hero_hole_cards == ("Kd", "As")
    assert second.tags == ("a", "z")
    assert first.to_json() == ScenarioSpec.from_json(first.to_json()).to_json()


def test_scenario_rejects_unknown_fields_and_unsupported_version():
    with pytest.raises(ValidationError):
        ScenarioSpec.model_validate({**minimal_scenario(), "notAField": True})

    with pytest.raises(ValueError, match="unsupported or missing schemaVersion"):
        ScenarioSpec.from_json('{"schemaVersion": 2}')


def test_raise_to_and_bet_amount_semantics_are_distinct():
    bet = ActionEvent(
        actionId="a1",
        sequence=1,
        street=Street.PREFLOP,
        actorSeat=0,
        actionType=ActionType.BET,
        amount=300,
        amountType=AmountType.BY,
    )
    raise_to = ActionEvent(
        actionId="a2",
        sequence=2,
        street=Street.PREFLOP,
        actorSeat=1,
        actionType=ActionType.RAISE_TO,
        amount=900,
        amountType=AmountType.TO,
    )
    assert bet.amount_type is AmountType.BY
    assert raise_to.amount_type is AmountType.TO

    with pytest.raises(ValidationError, match="requires amount_type=to"):
        ActionEvent(
            actionId="a3",
            sequence=3,
            street=Street.PREFLOP,
            actorSeat=0,
            actionType=ActionType.RAISE_TO,
            amount=600,
            amountType=AmountType.BY,
        )


def test_range_rejects_float_weights_and_dead_card_combos():
    with pytest.raises(ValidationError, match="weights must be decimal strings"):
        RangeCombo(cards=("As", "Kd"), weight=0.5)

    with pytest.raises(ValidationError, match="contains a dead card"):
        RangeSpec(
            rangeId="r1",
            name="test",
            version="1",
            source=RangeSource.USER_DEFINED,
            combos=[{"cards": ["As", "Kd"], "weight": "1"}],
            deadCards=["As"],
        )


def test_known_cards_are_excluded_from_scenario_concrete_ranges():
    range_spec = {
        "rangeId": "r1",
        "name": "test",
        "version": "1",
        "source": "user_defined",
        "combos": [{"cards": ["As", "Qd"], "weight": "1"}],
    }
    with pytest.raises(ValidationError, match="contains a known card"):
        ScenarioSpec.model_validate(minimal_scenario(villainRange=range_spec))


def test_both_hole_cards_and_board_cannot_repeat_known_cards():
    with pytest.raises(ValidationError, match="hero, villain, and board cards cannot overlap"):
        ScenarioSpec.model_validate(
            minimal_scenario(villainHoleCards=["As", "Qh"])
        )

    with pytest.raises(ValidationError, match="hero, villain, and board cards cannot overlap"):
        ScenarioSpec.model_validate(
            minimal_scenario(board=["As"], villainHoleCards=["Qh", "Jc"])
        )


def test_action_ids_must_be_unique_in_a_replay_history():
    with pytest.raises(ValidationError, match="action_id values must be unique"):
        ScenarioSpec.model_validate(
            minimal_scenario(
                actionHistory=[
                    {
                        "actionId": "same",
                        "sequence": 1,
                        "street": "preflop",
                        "actorSeat": 0,
                        "actionType": "call",
                        "amount": 50,
                        "amountType": "cost",
                    },
                    {
                        "actionId": "same",
                        "sequence": 2,
                        "street": "preflop",
                        "actorSeat": 1,
                        "actionType": "check",
                    },
                ]
            )
        )


def test_evidence_references_are_checked_against_bundle():
    bundle = EvidenceBundle(
        items=[
            EvidenceItem(
                evidenceId="pot",
                kind="pot",
                value=Decimal("10.00"),
                unit="chips",
                sourceLevel=AnalysisLevel.DETERMINISTIC,
                sourceVersion="rules-1",
                description="Current pot",
            )
        ]
    )
    response = TeachingResponse(
        summary=TeachingText(text="Pot is established.", evidenceReferences=[{"evidenceId": "pot"}]),
        uncertainty=TeachingText(text="No strategy data was matched."),
    )
    response.validate_evidence_references(bundle)

    bad = response.model_copy(
        update={
            "summary": TeachingText(
                text="This cites missing data.", evidenceReferences=[{"evidenceId": "missing"}]
            )
        }
    )
    with pytest.raises(ValueError, match="unknown evidence"):
        bad.validate_evidence_references(bundle)


def test_validation_report_returns_first_class_errors():
    report = ScenarioSpec.model_validate(minimal_scenario()).model_dump()
    report["action_history"] = [{"sequence": 2}]
    validation = ValidationReport.for_payload(report)
    assert not validation.valid
    assert validation.errors[0].severity.value == "error"
