from poker_coach.domain.models import ScenarioSpec
from poker_coach.learning import LearningService
from poker_coach.learning.models import LearningProfile


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


def test_practice_variant_is_reanalyzed_and_binds_expected_evidence():
    service = LearningService()
    question = service.generate_practice(
        scenario_at_flop(), profile_id="profile-1", mistake_tag="pot_odds"
    )

    assert question.question_id
    assert question.scenario.board != scenario_at_flop().board
    assert question.expected_action in {"check", "call", "fold"}
    assert {item.evidence_id for item in question.expected_evidence_references} >= {
        "rules.legal_actions",
        "math.required_equity",
        "equity.hero",
    }


def test_grading_updates_profile_and_returns_evidence_references():
    service = LearningService()
    profile = LearningProfile(profileId="profile-1", updatedAt="now")
    question = service.generate_practice(
        scenario_at_flop(), profile_id="profile-1", mistake_tag="pot_odds"
    )

    outcome = service.grade(
        question,
        selected_action="fold" if question.expected_action != "fold" else "check",
        rationale="test answer",
        profile=profile,
    )

    assert outcome.attempt.question_id == question.question_id
    assert outcome.attempt.evidence_references == question.expected_evidence_references
    assert outcome.profile.concept_attempts
    street = question.scenario.decision_point.street.value
    assert outcome.profile.street_attempts[street] == 1
    assert outcome.profile.street_correct.get(street, 0) == 0
    assert outcome.profile.texture_attempts
    assert all(count == 0 for count in outcome.profile.texture_correct.values())
    assert outcome.profile.recent_training == (question.question_id,)
