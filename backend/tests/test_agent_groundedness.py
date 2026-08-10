from poker_coach.coach import TeachingService, TeachingToolGateway
from poker_coach.analysis import analyze_scenario
from poker_coach.domain.models import ScenarioSpec


def scenario_at_flop() -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {
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
            "villainHoleCards": ["Qh", "Jc"],
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
        }
    )


def _all_teaching_texts(response):
    texts = [response.summary, response.uncertainty]
    for group in (
        response.recommendation_basis,
        response.assumptions,
        response.key_reasons,
        response.alternative_lines,
        response.future_street_plan,
    ):
        texts.extend(group)
    if response.common_mistake:
        texts.append(response.common_mistake)
    return tuple(texts)


def test_teaching_numbers_and_recommendations_are_evidence_bound():
    analysis = analyze_scenario(scenario_at_flop())
    response = TeachingService().explain(scenario_at_flop(), analysis=analysis)

    response.validate_evidence_references(analysis.evidence)
    assert response.evidence_references
    assert response.practice_question is None
    for text in _all_teaching_texts(response):
        if text.contains_numbers:
            assert text.evidence_references
    for action in response.recommended_actions:
        assert action.frequency is None
        assert action.ev is None
        assert action.evidence_references


def test_same_scene_produces_same_local_teaching_facts():
    service = TeachingService()
    first = service.explain(scenario_at_flop()).to_json()
    second = service.explain(scenario_at_flop()).to_json()

    assert first == second


def test_teaching_depth_is_explicit_and_changes_the_explanation_contract():
    service = TeachingService()
    beginner = service.explain(scenario_at_flop(), depth="beginner")
    advanced = service.explain(scenario_at_flop(), depth="advanced")

    assert beginner.explanation_depth == "beginner"
    assert advanced.explanation_depth == "advanced"
    assert beginner.to_json() != advanced.to_json()


def test_teaching_tool_gateway_exposes_facts_without_mutation_methods():
    scenario = scenario_at_flop()
    analysis = analyze_scenario(scenario)
    gateway = TeachingToolGateway(scenario, analysis)

    assert gateway.tool_names == frozenset(
        {
            "get_normalized_scenario",
            "get_legal_actions",
            "get_evidence_bundle",
            "get_range",
            "get_strategy_match",
            "get_term",
            "create_practice",
        }
    )
    assert gateway.get_normalized_scenario().to_json() == scenario.to_json()
    assert gateway.get_legal_actions().actions
    assert gateway.get_evidence_bundle().ids() == analysis.evidence.ids()
    assert gateway.get_range("villain") is None
    assert gateway.get_term("pot_odds")
    practice = gateway.create_practice(profile_id="tool-profile")
    assert practice.expected_evidence_references


def test_teaching_recommendations_are_legal_at_the_decision_node():
    scenario = scenario_at_flop()
    analysis = analyze_scenario(scenario)
    response = TeachingService().explain(scenario, analysis=analysis)
    legal = {
        action.value
        for action in TeachingToolGateway(scenario, analysis).get_legal_actions().actions
    }

    assert {action.action for action in response.recommended_actions} <= legal
