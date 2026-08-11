"""Public contracts owned by the deterministic hand-review subsystem."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictInt

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


class ReviewSolverAssessment(DomainModel):
    """Explicitly unscored until BE-03 binds a verified solver artifact."""

    status: Literal["unscored"] = "unscored"
    reason: str = "solver assessment is not available in deterministic hand-review v1"
    source: str | None = None


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


class HandReviewSummary(DomainModel):
    """Deterministic aggregate that does not add cross-node recommendations."""

    decision_count: Annotated[StrictInt, Field(ge=0)]
    reviewed_action_ids: tuple[str, ...] = ()


class HandReviewResponse(DomainModel):
    """Versioned deterministic response for ``POST /v1/hand-reviews``."""

    hand_review_version: str = "hand-review-1"
    hand_summary: HandReviewSummary
    decision_reviews: tuple[DecisionReview, ...] = ()
    uncertainty: tuple[str, ...] = ()
