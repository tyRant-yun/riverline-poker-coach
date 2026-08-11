"""Compose time-correct snapshots into deterministic hand-review responses."""

from __future__ import annotations

from poker_coach.analysis import analyze_scenario
from poker_coach.analysis.models import AnalysisResult
from poker_coach.domain.models import DecisionPoint, ScenarioSpec
from poker_coach.rules import PokerKitAdapter

from .builder import build_decision_snapshots
from .models import (
    DecisionAnalysisSummary,
    DecisionReview,
    DecisionSnapshot,
    HandReviewResponse,
    HandReviewSummary,
)


def build_hand_review(
    scenario: ScenarioSpec,
    *,
    adapter: PokerKitAdapter | None = None,
    timeout_seconds: float | None = None,
) -> HandReviewResponse:
    """Analyze every real action from its independently replayed pre-action node.

    The original imported board can contain a finished runout.  Each analysis
    input is deliberately narrowed to the snapshot's visible board and action
    prefix before it enters the existing analysis core.
    """

    rules = adapter or PokerKitAdapter()
    events_by_id = {event.action_id: event for event in scenario.action_history}
    reviews: list[DecisionReview] = []
    for snapshot in build_decision_snapshots(scenario, adapter=rules):
        actual_action = events_by_id[snapshot.action_id]
        analysis = analyze_scenario(
            _scenario_for_snapshot(scenario, snapshot),
            adapter=rules,
            timeout_seconds=timeout_seconds,
        )
        reviews.append(
            DecisionReview(
                action_id=snapshot.action_id,
                event_sequence=snapshot.event_sequence,
                decision_sequence=snapshot.decision_sequence,
                street=snapshot.street,
                actor_seat=snapshot.actor_seat,
                actual_action=actual_action,
                state_before_action=snapshot.state_before_action,
                analysis_summary=_summary_from(analysis),
                evidence_bundle_id=f"decision:{snapshot.action_id}:evidence",
                evidence_bundle=analysis.evidence,
                warnings=analysis.warnings,
            )
        )
    uncertainty = tuple(dict.fromkeys(warning for review in reviews for warning in review.warnings))
    return HandReviewResponse(
        hand_summary=HandReviewSummary(
            decision_count=len(reviews),
            reviewed_action_ids=tuple(review.action_id for review in reviews),
        ),
        decision_reviews=tuple(reviews),
        uncertainty=uncertainty,
    )


def _scenario_for_snapshot(scenario: ScenarioSpec, snapshot: DecisionSnapshot) -> ScenarioSpec:
    """Return the actor-centric analysis input at exactly one decision node."""

    visible_board = snapshot.state_before_action.board
    actor_cards = scenario.known_hole_cards_by_seat.get(snapshot.actor_seat)
    opponent_seats = [seat.seat_id for seat in scenario.seats if seat.seat_id != snapshot.actor_seat]
    villain_cards = (
        scenario.known_hole_cards_by_seat.get(opponent_seats[0])
        if scenario.table_size == 2
        else None
    )
    return scenario.model_copy(
        update={
            "hero_seat": snapshot.actor_seat,
            "hero_hole_cards": actor_cards if len(actor_cards or ()) == 2 else None,
            "villain_hole_cards": villain_cards if len(villain_cards or ()) == 2 else None,
            "hero_range": scenario.ranges_by_seat.get(snapshot.actor_seat),
            "villain_range": (
                scenario.ranges_by_seat.get(opponent_seats[0])
                if scenario.table_size == 2
                else None
            ),
            "board": visible_board,
            "action_history": scenario.action_history[: snapshot.decision_sequence],
            "decision_point": DecisionPoint(
                street=snapshot.street,
                actor_seat=snapshot.actor_seat,
                after_sequence=snapshot.decision_sequence,
            ),
        }
    )


def _summary_from(analysis: AnalysisResult) -> DecisionAnalysisSummary:
    return DecisionAnalysisSummary(
        analysis_version=analysis.analysis_version,
        metrics=analysis.metrics,
        hand=analysis.hand,
        board=analysis.board,
        equity=analysis.equity,
        multiway_equity=analysis.multiway_equity,
        range_analysis=analysis.range_analysis,
        range_comparison=analysis.range_comparison,
        strategy_match=analysis.strategy_match,
    )
