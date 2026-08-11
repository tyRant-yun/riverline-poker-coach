"""Public contracts owned by the deterministic hand-review subsystem."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_serializer

from poker_coach.analysis.models import (
    BasicMetrics,
    BoardAnalysis,
    EquityResult,
    HandAnalysis,
    MultiwayEquityResult,
    RangeAnalysis,
    RangeComparison,
)
from poker_coach.domain.models import (
    ActionEvent,
    DomainModel,
    EvidenceBundle,
    SeatNumber,
    StateSnapshot,
    Street,
    TeachingText,
)
from poker_coach.strategy.models import StrategyMatch


class DecisionSnapshot(DomainModel):
    """The PokerKit-verified state immediately before one player decision."""

    action_id: str = Field(min_length=1, max_length=128)
    event_sequence: Annotated[StrictInt, Field(ge=1)]
    decision_sequence: Annotated[StrictInt, Field(ge=0)]
    street: Street
    actor_seat: SeatNumber
    state_before_action: StateSnapshot


class DecisionAnalysisSummary(DomainModel):
    """The node-local analysis result without a duplicate evidence bundle."""

    analysis_version: str = Field(min_length=1, max_length=128)
    metrics: BasicMetrics
    hand: HandAnalysis | None = None
    board: BoardAnalysis
    equity: EquityResult | None = None
    multiway_equity: MultiwayEquityResult | None = None
    range_analysis: RangeAnalysis | None = None
    range_comparison: RangeComparison | None = None
    strategy_match: StrategyMatch | None = None


class ReviewRangeUpdate(DomainModel):
    """Explicit BE-02 placeholder; action-conditioned range work is separate."""

    status: Literal["unavailable"] = "unavailable"
    reason: str = "range review is not available in deterministic hand-review v1"
    source: str | None = None


class ReviewSolverThresholdMetadata(DomainModel):
    """A product explanation threshold, never a poker-theory assertion."""

    mixed_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.05
    kind: Literal["product_interpretation"] = "product_interpretation"


class ReviewSolverActionMapping(DomainModel):
    """How an observed action relates to the artifact action vocabulary."""

    status: Literal["exact", "nearest_size", "unsupported"]
    policy_action: str = ""
    observed_size: Annotated[float, Field(ge=0.0)] | None = None
    mapped_size: Annotated[float, Field(ge=0.0)] | None = None
    off_tree: bool = False


class ReviewSolverAssessment(DomainModel):
    """Actual-action frequency from one grounded, exact-node solver artifact."""

    status: Literal["primary", "mixed", "rare", "absent", "unscored"] = "unscored"
    reason: str | None = "solver assessment is not available in deterministic hand-review v1"
    source: str | None = None
    confidence: str | None = None
    actual_frequency: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    primary_action: str | None = None
    threshold_metadata: ReviewSolverThresholdMetadata | None = None
    action_mapping: ReviewSolverActionMapping | None = None

    @model_serializer(mode="wrap")
    def serialize_compatibly(self, handler):
        """Keep the BE-02 no-solver response byte-shape stable.

        The original deterministic assessment had only ``status``, ``reason``
        and ``source``.  New facts are omitted until a persisted artifact was
        actually used, while ``source: null`` remains for compatibility.
        """

        data = handler(self)
        for field in (
            "confidence",
            "actualFrequency",
            "primaryAction",
            "thresholdMetadata",
            "actionMapping",
        ):
            if data.get(field) is None:
                data.pop(field, None)
        return data


class DecisionTeaching(DomainModel):
    """A node-local explanation that may cite only this review's evidence."""

    teaching_version: str = "hand-review-teaching-1"
    mode: Literal["solver_grounded", "principle_only"] = "principle_only"
    provider: Literal["local"] = "local"
    summary: TeachingText
    key_points: tuple[TeachingText, ...] = ()
    uncertainty: TeachingText
    mistake_tags: tuple[str, ...] = ()

    def validate_evidence_references(self, bundle: EvidenceBundle) -> None:
        references = list(self.summary.evidence_references)
        references.extend(self.uncertainty.evidence_references)
        for point in self.key_points:
            references.extend(point.evidence_references)
        missing = sorted({item.evidence_id for item in references} - bundle.ids())
        if missing:
            raise ValueError(f"decision teaching references unknown evidence: {missing}")


class PriorityFinding(DomainModel):
    """A stable, action-addressable review target for UI navigation/practice."""

    action_id: str = Field(min_length=1, max_length=128)
    category: Literal["solver_deviation"]
    mistake_tag: Literal["solver_rare_action", "solver_absent_action"]
    severity: Literal["review"] = "review"
    summary: TeachingText


class WholeHandTeaching(DomainModel):
    """Aggregate wording derived only from already-composed node teachings."""

    teaching_version: str = "hand-review-whole-hand-1"
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)


class DecisionReview(DomainModel):
    """One real player action, analyzed only from its pre-action state."""

    decision_review_version: str = "decision-review-1"
    action_id: str = Field(min_length=1, max_length=128)
    event_sequence: Annotated[StrictInt, Field(ge=1)]
    decision_sequence: Annotated[StrictInt, Field(ge=0)]
    street: Street
    actor_seat: SeatNumber
    actual_action: ActionEvent
    state_before_action: StateSnapshot
    analysis_summary: DecisionAnalysisSummary
    evidence_bundle_id: str = Field(min_length=1, max_length=256)
    evidence_bundle: EvidenceBundle
    warnings: tuple[str, ...] = ()
    range_update: ReviewRangeUpdate = Field(default_factory=ReviewRangeUpdate)
    solver_assessment: ReviewSolverAssessment = Field(default_factory=ReviewSolverAssessment)
    teaching: DecisionTeaching | None = None


class HandReviewSummary(DomainModel):
    """Deterministic aggregate that does not add cross-node recommendations."""

    decision_count: Annotated[StrictInt, Field(ge=0)]
    reviewed_action_ids: tuple[str, ...] = ()


class HandReviewResponse(DomainModel):
    """Versioned deterministic response for ``POST /v1/hand-reviews``."""

    hand_review_version: str = "hand-review-1"
    hand_summary: HandReviewSummary
    decision_reviews: tuple[DecisionReview, ...] = ()
    whole_hand_summary: WholeHandTeaching | None = None
    priority_findings: tuple[PriorityFinding, ...] = ()
    uncertainty: tuple[str, ...] = ()
