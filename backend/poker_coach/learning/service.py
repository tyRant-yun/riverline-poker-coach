"""Generate and grade only practice questions backed by a fresh analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from poker_coach.analysis import analyze_board, analyze_scenario
from poker_coach.domain.models import EvidenceReference, ScenarioSpec
from poker_coach.rules import PokerKitAdapter

from .models import LearningProfile, PracticeAttempt, PracticeOutcome, ValidatedPractice


class PracticeUnavailable(ValueError):
    """Raised when a practice answer cannot be validated from deterministic evidence."""


class LearningService:
    version = "learning-core-0.1"

    def __init__(self, adapter: PokerKitAdapter | None = None):
        self.adapter = adapter or PokerKitAdapter()

    def generate_practice(
        self,
        scenario: ScenarioSpec,
        *,
        profile_id: str,
        source_scenario_id: str | None = None,
        source_analysis_id: str | None = None,
        mistake_tag: str | None = None,
    ) -> ValidatedPractice:
        variant = _make_variant(scenario)
        analysis = analyze_scenario(variant, adapter=self.adapter)
        if analysis.equity is None:
            raise PracticeUnavailable(
                "practice requires a concrete villain hand or non-empty villain range"
            )
        expected_action = _validated_action(analysis)
        references = tuple(
            EvidenceReference(evidenceId=evidence_id)
            for evidence_id in (
                "rules.legal_actions",
                "math.required_equity",
                "equity.hero",
            )
            if evidence_id in analysis.evidence.ids()
        )
        concepts = tuple(
            sorted(
                {
                    "pot_odds",
                    "equity",
                    "decision_point",
                    *[draw.value for draw in analysis.hand.draws],
                }
            )
        )
        return ValidatedPractice(
            questionId=uuid4().hex,
            profileId=profile_id,
            sourceScenarioId=source_scenario_id,
            sourceAnalysisId=source_analysis_id,
            scenario=variant,
            prompt=(
                "这是一个经过规则和分析证据验证的变体。请选择当前最合适的合法行动，"
                "先说明你的判断，再查看依据。"
            ),
            expectedAction=expected_action,
            expectedEvidenceReferences=references,
            conceptTags=concepts,
            mistakeTag=mistake_tag,
            createdAt=_now(),
        )

    def grade(
        self,
        question: ValidatedPractice,
        *,
        selected_action: str,
        rationale: str | None = None,
        profile: LearningProfile,
    ) -> PracticeOutcome:
        correct = selected_action == question.expected_action
        attempt = PracticeAttempt(
            attemptId=uuid4().hex,
            questionId=question.question_id,
            selectedAction=selected_action,
            correct=correct,
            rationale=rationale,
            evidenceReferences=question.expected_evidence_references,
            createdAt=_now(),
        )
        updated = _update_profile(profile, question, correct)
        explanation = (
            f"你的选择是 {selected_action}；验证答案是 {question.expected_action}。"
            if not correct
            else f"你的选择 {selected_action} 与验证答案一致。"
        )
        return PracticeOutcome(
            attempt=attempt,
            expectedAction=question.expected_action,
            explanation=explanation,
            evidenceReferences=question.expected_evidence_references,
            profile=updated,
        )


def _validated_action(analysis) -> str:
    legal_item = next(
        item for item in analysis.evidence.items if item.evidence_id == "rules.legal_actions"
    )
    legal = set(legal_item.value)
    if analysis.metrics.call_cost == 0 and "check" in legal:
        return "check"
    if analysis.equity.hero_equity >= analysis.metrics.required_equity and "call" in legal:
        return "call"
    if "fold" in legal:
        return "fold"
    if "check" in legal:
        return "check"
    return sorted(legal)[0] if legal else "no_legal_action"


def _make_variant(scenario: ScenarioSpec) -> ScenarioSpec:
    known = set(scenario.hero_hole_cards)
    if scenario.villain_hole_cards:
        known.update(scenario.villain_hole_cards)
    known.update(scenario.board)
    deck = tuple(rank + suit for rank in "23456789TJQKA" for suit in "cdhs")
    if scenario.board:
        prefix = scenario.board[:-1]
        replacement = next(card for card in deck if card not in known and card not in prefix)
        board = prefix + (replacement,)
        return scenario.model_copy(update={"board": board})
    replacement = next(card for card in deck if card not in known)
    hole_cards = (scenario.hero_hole_cards[0], replacement)
    return scenario.model_copy(update={"hero_hole_cards": hole_cards})


def _update_profile(profile: LearningProfile, question: ValidatedPractice, correct: bool) -> LearningProfile:
    mistake_counts = dict(profile.mistake_counts)
    if question.mistake_tag and not correct:
        mistake_counts[question.mistake_tag] = mistake_counts.get(question.mistake_tag, 0) + 1
    attempts = dict(profile.concept_attempts)
    successes = dict(profile.concept_correct)
    for concept in question.concept_tags:
        attempts[concept] = attempts.get(concept, 0) + 1
        if correct:
            successes[concept] = successes.get(concept, 0) + 1
    street = question.scenario.decision_point.street.value
    street_attempts = dict(profile.street_attempts)
    street_correct = dict(profile.street_correct)
    street_attempts[street] = street_attempts.get(street, 0) + 1
    if correct:
        street_correct[street] = street_correct.get(street, 0) + 1
    texture = analyze_board(question.scenario.board)
    texture_attempts = dict(profile.texture_attempts)
    texture_correct = dict(profile.texture_correct)
    texture_labels = texture.labels or ("unclassified",)
    for label in texture_labels:
        texture_attempts[label] = texture_attempts.get(label, 0) + 1
        if correct:
            texture_correct[label] = texture_correct.get(label, 0) + 1
    recent_training = (question.question_id, *profile.recent_training)[:20]
    recommended = tuple(
        sorted(
            topic
            for topic, count in mistake_counts.items()
            if count > 0
        )
    )
    return profile.model_copy(
        update={
            "mistake_counts": mistake_counts,
            "concept_attempts": attempts,
            "concept_correct": successes,
            "street_attempts": street_attempts,
            "street_correct": street_correct,
            "texture_attempts": texture_attempts,
            "texture_correct": texture_correct,
            "recent_training": recent_training,
            "recommended_topics": recommended,
            "updated_at": _now(),
        }
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
