"""Compose time-correct snapshots into deterministic hand-review responses."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from poker_coach.analysis import analyze_scenario
from poker_coach.analysis.models import AnalysisResult
from poker_coach.domain.models import DecisionPoint, ScenarioSpec
from poker_coach.ranges import (
    NoPriorRangeError,
    PreflopPolicyProvider,
    RangeBeliefError,
    build_belief_view,
    build_range_trace,
)
from poker_coach.rules import PokerKitAdapter

from .builder import build_decision_snapshots
from .models import (
    DecisionAnalysisSummary,
    DecisionReview,
    DecisionSnapshot,
    HandReviewResponse,
    HandReviewSummary,
    ReviewRangePolicy,
    ReviewRangeUpdate,
)
from .solver_assessment import (
    SolverAssessmentError,
    assess_solver_action,
    validated_solver_policy_provider,
)
from .teaching import compose_hand_review_teaching


def build_hand_review(
    scenario: ScenarioSpec,
    *,
    adapter: PokerKitAdapter | None = None,
    timeout_seconds: float | None = None,
    solver_job_ids: Mapping[str, str] | None = None,
    solver_job_lookup: Callable[[str], Mapping[str, Any]] | None = None,
) -> HandReviewResponse:
    """Analyze every real action from its independently replayed pre-action node.

    The original imported board can contain a finished runout.  Each analysis
    input is deliberately narrowed to the snapshot's visible board and action
    prefix before it enters the existing analysis core.
    """

    rules = adapter or PokerKitAdapter()
    events_by_id = {event.action_id: event for event in scenario.action_history}
    snapshots = build_decision_snapshots(scenario, adapter=rules)
    pot_before_by_sequence = {
        snapshot.event_sequence: int(snapshot.state_before_action.pot)
        for snapshot in snapshots
    }
    reviews: list[DecisionReview] = []
    for snapshot in snapshots:
        actual_action = events_by_id[snapshot.action_id]
        analysis = analyze_scenario(
            _scenario_for_snapshot(scenario, snapshot),
            adapter=rules,
            timeout_seconds=timeout_seconds,
        )
        review = DecisionReview(
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
            range_update=ReviewRangeUpdate(
                action_id=snapshot.action_id,
                seat_id=snapshot.actor_seat,
                after_sequence=snapshot.event_sequence,
                reason="range update has not been computed",
            ),
        )
        review = review.model_copy(
            update={
                "range_update": _range_update_for_action(
                    scenario,
                    review,
                    solver_job_id=(
                        solver_job_ids.get(snapshot.action_id)
                        if solver_job_ids is not None
                        else None
                    ),
                    solver_job_lookup=solver_job_lookup,
                    pot_before_by_sequence=pot_before_by_sequence,
                    adapter=rules,
                )
            }
        )
        if solver_job_ids is not None:
            review = review.model_copy(
                update={
                    "solver_assessment": assess_solver_action(
                        scenario,
                        review,
                        job_id=solver_job_ids.get(snapshot.action_id),
                        job_lookup=solver_job_lookup,
                        adapter=rules,
                    )
                }
            )
        reviews.append(review)
    uncertainty = tuple(dict.fromkeys(warning for review in reviews for warning in review.warnings))
    response = HandReviewResponse(
        hand_summary=HandReviewSummary(
            decision_count=len(reviews),
            reviewed_action_ids=tuple(review.action_id for review in reviews),
        ),
        decision_reviews=tuple(reviews),
        uncertainty=uncertainty,
    )
    return compose_hand_review_teaching(response)


def _range_update_for_action(
    scenario: ScenarioSpec,
    review: DecisionReview,
    *,
    solver_job_id: str | None,
    solver_job_lookup: Callable[[str], Mapping[str, Any]] | None,
    pot_before_by_sequence: Mapping[int, int],
    adapter: PokerKitAdapter,
) -> ReviewRangeUpdate:
    """Project the shared range trace onto the actor's post-action state."""

    prior_range = scenario.ranges_by_seat.get(review.actor_seat)
    if prior_range is None:
        return _unavailable_range_update(review, "no_prior_range: no prior range is available for this seat")

    # Curated policy is always first: it is the same versioned provider used
    # by the range endpoints. A persisted solver adapter is appended only for
    # the exact actionId-bound postflop node; it never covers another action.
    providers: list[Any] = [PreflopPolicyProvider()]
    if solver_job_id is not None and review.street.value != "preflop":
        try:
            solver_provider, _ = validated_solver_policy_provider(
                scenario,
                review,
                job_id=solver_job_id,
                job_lookup=solver_job_lookup,
                adapter=adapter,
            )
            providers.append(solver_provider)
        except (RangeBeliefError, SolverAssessmentError):
            # Range output degrades honestly. The existing solver-assessment
            # path still decides whether a supplied artifact is a contract
            # error (and preserves its legacy validation behavior).
            return _unavailable_range_update(
                review,
                f"no_policy: solver artifact cannot ground this action's range update",
            )

    try:
        trace = build_range_trace(
            scenario,
            review.actor_seat,
            prior_range=prior_range,
            providers=providers,
            max_sequence=review.event_sequence,
            pot_provider=lambda sequence: pot_before_by_sequence.get(sequence),
        )
    except NoPriorRangeError as exc:
        return _unavailable_range_update(review, f"no_prior_range: {exc}")

    view = build_belief_view(trace)
    if not view.available or view.after_sequence != review.event_sequence:
        return _unavailable_range_update(
            review,
            view.unavailable_reason
            or "no_policy: no grounded action policy produced this action's post-action range",
        )

    update = view.update
    assert view.source is not None and update is not None
    return ReviewRangeUpdate(
        status="available",
        action_id=review.action_id,
        seat_id=review.actor_seat,
        after_sequence=review.event_sequence,
        source=view.source,
        confidence=view.confidence,
        policy=ReviewRangePolicy(
            source=view.source,
            node=update.node,
            version=update.policy_version,
            assumptions=update.assumptions,
        ),
        uncertainty=(
            "This is a curated policy baseline, not Solver/GTO output."
            if view.source.value == "preflop_policy"
            else "This update is limited to the persisted solver artifact's exact node."
            if view.source.value == "solver"
            else None
        ),
        prior_mass=float(view.prior_mass) if view.prior_mass is not None else None,
        retained_mass=float(view.retained_mass) if view.retained_mass is not None else None,
        retained_fraction=(
            float(view.retained_fraction) if view.retained_fraction is not None else None
        ),
        combos=view.combos,
        matrix169=view.matrix169,
        update=update,
    )


def _unavailable_range_update(review: DecisionReview, reason: str) -> ReviewRangeUpdate:
    return ReviewRangeUpdate(
        status="unavailable",
        action_id=review.action_id,
        seat_id=review.actor_seat,
        after_sequence=review.event_sequence,
        reason=reason,
        uncertainty="No grounded policy covers this exact action-time node; no current range was fabricated.",
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
