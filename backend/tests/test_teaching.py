from poker_coach.analysis import analyze_scenario
from poker_coach.coach import TeachingService
from poker_coach.domain.models import ScenarioSpec


def scenario(with_villain=True):
    payload = {
        "schemaVersion": 1,
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
        "heroHoleCards": ["As", "Kd"],
        "board": ["2c", "7d", "Jh"],
        "actionHistory": [
            {
                "actionId": "call",
                "sequence": 1,
                "street": "preflop",
                "actorSeat": 0,
                "actionType": "call",
                "amount": 50,
                "amountType": "cost",
            },
            {
                "actionId": "check",
                "sequence": 2,
                "street": "preflop",
                "actorSeat": 1,
                "actionType": "check",
            },
            {
                "actionId": "flop",
                "sequence": 3,
                "street": "flop",
                "actorSeat": 0,
                "actionType": "deal_flop",
            },
        ],
        "decisionPoint": {"street": "flop", "actorSeat": 1, "afterSequence": 3},
        "assumptions": {},
    }
    if with_villain:
        payload["villainHoleCards"] = ["Qh", "Jc"]
    return ScenarioSpec.model_validate(payload)


def test_teaching_response_is_grounded_in_analysis_evidence():
    scenario_spec = scenario()
    analysis = analyze_scenario(scenario_spec)
    response = TeachingService().explain(scenario_spec, analysis=analysis)

    response.validate_evidence_references(analysis.evidence)
    assert response.recommended_actions
    assert response.recommended_actions[0].frequency is None
    assert response.recommended_actions[0].ev is None
    assert response.uncertainty.evidence_references


def test_missing_villain_data_degrades_to_principle_teaching():
    scenario_spec = scenario(with_villain=False)
    analysis = analyze_scenario(scenario_spec)
    response = TeachingService().explain(scenario_spec, analysis=analysis)

    assert analysis.equity is None
    assert response.recommended_actions == ()
    assert "principle_only" in response.recommendation_basis[0].text
    response.validate_evidence_references(analysis.evidence)
