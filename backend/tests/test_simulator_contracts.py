"""Public contract tests for the simulator foundation."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from poker_coach.simulator import (
    AmountSemanticsV1,
    BotDecisionV1,
    HandEventV1,
    LegalActionV1,
    ObservationV1,
    SimulatorActionV1,
)


def _hand_started_event() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "eventId": "evt-001",
        "handId": "hand-fixture-001",
        "sequence": 1,
        "timestamp": "2026-08-12T00:00:00Z",
        "source": "fixture",
        "provenance": {
            "producer": "riverline-tests",
            "producerVersion": "1.0.0",
            "correlationId": "session-fixture-001",
        },
        "payload": {
            "kind": "hand_started",
            "ruleset": "nlhe",
            "tableSize": 6,
            "buttonSeat": 0,
            "smallBlind": 50,
            "bigBlind": 100,
            "ante": 0,
            "rakeBps": 0,
            "startingStacks": {str(seat): 10_000 for seat in range(6)},
            "rngSeed": 20260812,
        },
    }


def test_hand_event_v1_is_versioned_immutable_and_deterministically_serialized():
    event = HandEventV1.model_validate(_hand_started_event())

    assert event.schema_version == 1
    assert event.payload.table_size == 6
    assert HandEventV1.model_validate_json(event.to_json()).to_json() == event.to_json()

    with pytest.raises(ValidationError, match="frozen"):
        event.sequence = 2

    future = {**_hand_started_event(), "schemaVersion": 2}
    with pytest.raises(ValidationError):
        HandEventV1.model_validate(future)


def test_hand_event_v1_requires_timezone_aware_timestamp_and_provenance():
    naive = {**_hand_started_event(), "timestamp": "2026-08-12T00:00:00"}
    with pytest.raises(ValidationError):
        HandEventV1.model_validate(naive)

    missing_provenance = _hand_started_event()
    missing_provenance.pop("provenance")
    with pytest.raises(ValidationError):
        HandEventV1.model_validate(missing_provenance)


def test_legal_action_v1_has_explicit_amount_semantics_and_bounds():
    fold = LegalActionV1(action="fold", amountSemantics="none")
    call = LegalActionV1(
        action="call", amountSemantics="cost", minAmount=150, maxAmount=150
    )
    bet = LegalActionV1(
        action="bet", amountSemantics="by", minAmount=100, maxAmount=9_750
    )
    raise_to = LegalActionV1(
        action="raise", amountSemantics="to", minAmount=600, maxAmount=10_000
    )

    assert fold.accepts(action=SimulatorActionV1.FOLD, amount=None)
    assert call.accepts(action=SimulatorActionV1.CALL, amount=150)
    assert not call.accepts(action=SimulatorActionV1.CALL, amount=149)
    assert bet.accepts(action=SimulatorActionV1.BET, amount=9_750)  # all-in endpoint
    assert raise_to.accepts(action=SimulatorActionV1.RAISE, amount=600)
    assert bet.amount_semantics is AmountSemanticsV1.BY

    with pytest.raises(ValidationError, match="bet requires amount_semantics=by"):
        LegalActionV1(
            action="bet", amountSemantics="to", minAmount=100, maxAmount=200
        )

    with pytest.raises(ValidationError, match="must not carry amount bounds"):
        LegalActionV1(
            action="check", amountSemantics="none", minAmount=0, maxAmount=0
        )


def _observation_payload() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "handId": "hand-fixture-001",
        "sequence": 9,
        "observerSeat": 2,
        "tableSize": 6,
        "buttonSeat": 0,
        "street": "flop",
        "ownHoleCards": ["Qh", "Qc"],
        "board": ["2c", "7d", "Jh"],
        "pot": 550,
        "stacks": {str(seat): 10_000 for seat in range(6)},
        "streetCommitments": {str(seat): 0 for seat in range(6)},
        "activeSeats": [0, 2],
        "foldedSeats": [1, 3, 4, 5],
        "publicActions": [
            {
                "sequence": 5,
                "street": "preflop",
                "actorSeat": 0,
                "action": "raise",
                "amount": 250,
                "amountSemantics": "to",
            }
        ],
        "legalActions": [
            {"action": "check", "amountSemantics": "none"},
            {
                "action": "bet",
                "amountSemantics": "by",
                "minAmount": 100,
                "maxAmount": 9_750,
            },
            {"action": "fold", "amountSemantics": "none"},
        ],
    }


def test_observation_v1_exposes_only_agent_visible_information():
    observation = ObservationV1.model_validate(_observation_payload())

    serialized = observation.to_json()
    assert observation.own_hole_cards == ("Qh", "Qc")
    assert "opponentHoleCards" not in serialized
    assert "rangeBelief" not in serialized

    leaked_cards = {
        **_observation_payload(),
        "opponentHoleCardsBySeat": {"0": ["As", "Kd"]},
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ObservationV1.model_validate(leaked_cards)

    leaked_belief = {**_observation_payload(), "rangeBelief": {"AA": 0.2}}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ObservationV1.model_validate(leaked_belief)


def test_bot_decision_v1_carries_provider_latency_and_fallback_provenance():
    decision = BotDecisionV1(
        action="call",
        amount=150,
        amountSemantics="cost",
        provider="local-blueprint",
        providerVersion="1.2.0",
        latencyMs=4.25,
        confidence=0.72,
        metadata={"policyNode": "bb-vs-btn-open"},
        attempts=[
            {
                "provider": "local-blueprint",
                "providerVersion": "1.2.0",
                "status": "success",
                "latencyMs": 4.25,
            }
        ],
    )

    assert decision.provider == "local-blueprint"
    assert decision.degraded is False
    assert BotDecisionV1.model_validate_json(decision.to_json()) == decision

    fallback = BotDecisionV1(
        action="check",
        amountSemantics="none",
        provider="fixed-policy",
        providerVersion="1.0.0",
        latencyMs=12.0,
        degraded=True,
        fallbackReason="timeout",
        attempts=[
            {
                "provider": "external-agent",
                "providerVersion": "2026-08",
                "status": "timeout",
                "latencyMs": 10.0,
                "errorCode": "provider_timeout",
            },
            {
                "provider": "fixed-policy",
                "providerVersion": "1.0.0",
                "status": "success",
                "latencyMs": 2.0,
            },
        ],
    )
    assert fallback.degraded is True
    assert fallback.attempts[0].error_code == "provider_timeout"

    with pytest.raises(ValidationError, match="fallback_reason"):
        BotDecisionV1(
            action="fold",
            amountSemantics="none",
            provider="fixed-policy",
            providerVersion="1",
            latencyMs=1,
            degraded=True,
        )
