"""Contracts for anonymous learning state and evidence-bound practice."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, StrictInt

from poker_coach.domain.models import DomainModel, EvidenceReference, ScenarioSpec


class MistakeTag(str, Enum):
    """Canonical mistake tags; imported user tags may still use plain strings."""

    PREFLOP_TOO_WIDE = "preflop_range_too_wide"
    PREFLOP_TOO_NARROW = "preflop_range_too_narrow"
    POSITION = "position_ignored"
    POT_ODDS = "pot_odds"
    SPR = "spr"
    BET_SIZING = "bet_sizing"
    UNDER_VALUE = "under_value_bet"
    OVER_BLUFF = "over_bluff"
    BLUFF_CATCHER = "bluff_catcher"
    BLOCKER = "blocker"
    STREET_PLAN = "turn_river_plan"
    RANGE_ASSUMPTION = "range_assumption"


class LearningProfile(DomainModel):
    profile_id: str = Field(min_length=1, max_length=128)
    mistake_counts: dict[str, StrictInt] = Field(default_factory=dict)
    concept_attempts: dict[str, StrictInt] = Field(default_factory=dict)
    concept_correct: dict[str, StrictInt] = Field(default_factory=dict)
    street_attempts: dict[str, StrictInt] = Field(default_factory=dict)
    street_correct: dict[str, StrictInt] = Field(default_factory=dict)
    texture_attempts: dict[str, StrictInt] = Field(default_factory=dict)
    texture_correct: dict[str, StrictInt] = Field(default_factory=dict)
    recent_training: tuple[str, ...] = ()
    recommended_topics: tuple[str, ...] = ()
    updated_at: str


class ValidatedPractice(DomainModel):
    question_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=128)
    source_scenario_id: str | None = None
    source_analysis_id: str | None = None
    scenario: ScenarioSpec
    prompt: str = Field(min_length=1, max_length=1024)
    expected_action: str = Field(min_length=1, max_length=64)
    expected_evidence_references: tuple[EvidenceReference, ...] = ()
    concept_tags: tuple[str, ...] = ()
    mistake_tag: str | None = None
    created_at: str


class PracticeAttempt(DomainModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    question_id: str = Field(min_length=1, max_length=128)
    selected_action: str = Field(min_length=1, max_length=64)
    correct: bool
    rationale: str | None = Field(default=None, max_length=2048)
    evidence_references: tuple[EvidenceReference, ...] = ()
    created_at: str


class PracticeOutcome(DomainModel):
    attempt: PracticeAttempt
    expected_action: str
    explanation: str = Field(min_length=1, max_length=1024)
    evidence_references: tuple[EvidenceReference, ...] = ()
    profile: LearningProfile
