"""Grounded solver-artifact assessment for one historical decision."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from poker_coach.domain.models import ScenarioSpec, Street
from poker_coach.ranges import SolverPolicyAdapter
from poker_coach.ranges.belief import combo_key
from poker_coach.ranges.policy import ActionMatch, ActionMatchStatus, resolve_action_match
from poker_coach.rules import PokerKitAdapter, ReplayError
from poker_coach.solver import (
    SolverUnsupportedError,
    build_spot,
    postflop_seat_pair,
    scenario_at_policy_sequence,
    scenario_fingerprint,
    solver_spot_fingerprint,
)

from .models import (
    DecisionReview,
    ReviewSolverActionMapping,
    ReviewSolverAssessment,
    ReviewSolverThresholdMetadata,
)


MIXED_FREQUENCY_THRESHOLD = 0.05


class SolverAssessmentError(ValueError):
    """Stable API-facing failure for a supplied persisted artifact."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        self.code = code
        self.details = details
        super().__init__(message)


def assess_solver_action(
    scenario: ScenarioSpec,
    review: DecisionReview,
    *,
    job_id: str | None,
    job_lookup: Callable[[str], Mapping[str, Any]] | None,
    adapter: PokerKitAdapter | None = None,
) -> ReviewSolverAssessment:
    """Score one action only when its job proves the exact decision node.

    This deliberately consumes the normalized ``SolverNode`` through
    ``SolverPolicyAdapter``.  It never invokes a solver or derives EV loss.
    """

    if job_id is None:
        return _unscored("no persisted solver job is bound to this action")
    if review.street is Street.PREFLOP:
        return _unscored("solver assessment supports postflop decisions only")
    actor_cards = scenario.known_hole_cards_by_seat.get(review.actor_seat, ())
    if len(actor_cards) != 2:
        return _unscored("the acting seat has no known concrete hole-card combo")

    rules = adapter or PokerKitAdapter()
    try:
        policy, pot_before = validated_solver_policy_provider(
            scenario,
            review,
            job_id=job_id,
            job_lookup=job_lookup,
            adapter=rules,
        )
    except (SolverUnsupportedError, ReplayError) as exc:
        return _unscored(str(exc))
    combo = combo_key((actor_cards[0], actor_cards[1]))
    action_policy = policy.get_action_frequencies(
        scenario_at_policy_sequence(scenario, review.event_sequence),
        review.actor_seat,
        review.event_sequence,
        (combo,),
    )
    frequencies = action_policy.frequencies.get(combo)
    if frequencies is None:
        return _unscored(
            "solver artifact has no strategy row for the acting seat's known combo",
            source="solver",
            confidence=action_policy.confidence,
        )
    action_match = resolve_action_match(review.actual_action, action_policy, pot_before=pot_before)
    mapping = _mapping_from(action_match)
    if action_match.status is not ActionMatchStatus.EXACT or action_match.off_tree:
        return _unscored(
            "observed action is off-tree or unsupported by this solver artifact",
            source="solver",
            confidence=action_policy.confidence,
            action_mapping=mapping,
        )

    actual_frequency = float(frequencies[action_match.policy_action])
    primary_action = max(action_policy.actions, key=lambda action: frequencies[action])
    primary_frequency = float(frequencies[primary_action])
    status = (
        "primary"
        if actual_frequency == primary_frequency
        else "mixed"
        if actual_frequency >= MIXED_FREQUENCY_THRESHOLD
        else "rare"
        if actual_frequency > 0
        else "absent"
    )
    return ReviewSolverAssessment(
        status=status,
        reason=None,
        source="solver",
        confidence=action_policy.confidence,
        actual_frequency=actual_frequency,
        primary_action=primary_action,
        threshold_metadata=ReviewSolverThresholdMetadata(
            mixed_threshold=MIXED_FREQUENCY_THRESHOLD
        ),
        action_mapping=mapping,
    )


def validated_solver_policy_provider(
    scenario: ScenarioSpec,
    review: DecisionReview,
    *,
    job_id: str,
    job_lookup: Callable[[str], Mapping[str, Any]] | None,
    adapter: PokerKitAdapter | None = None,
) -> tuple[SolverPolicyAdapter, int]:
    """Return an existing exact-node solver policy, never a newly solved one."""

    rules = adapter or PokerKitAdapter()
    node_scenario = scenario_at_policy_sequence(scenario, review.event_sequence)
    node_replay = rules.replay_to_decision(node_scenario)
    oop_seat, ip_seat = postflop_seat_pair(node_scenario, replay=node_replay)
    if job_lookup is None:
        raise SolverAssessmentError("solver_unavailable", "solver job lookup is unavailable")

    job = job_lookup(job_id)
    if job.get("status") != "solved" or job.get("result") is None:
        raise SolverAssessmentError(
            "no_policy", f"solver job {job_id!r} is not solved and cannot score an action"
        )
    provenance = job.get("provenance")
    if provenance is None:
        raise SolverAssessmentError(
            "solver_artifact_mismatch",
            "solver job has no exact-node provenance metadata",
        )
    if (
        provenance.policy_sequence != review.event_sequence
        or provenance.decision_sequence != review.decision_sequence
        or provenance.actor_seat != review.actor_seat
        or provenance.street is not review.street
    ):
        raise SolverAssessmentError(
            "solver_artifact_mismatch",
            "solver artifact provenance does not match the reviewed action",
        )
    try:
        expected_spot = build_spot(node_scenario, replay=node_replay)
    except (SolverUnsupportedError, ReplayError) as exc:
        raise SolverAssessmentError("solver_artifact_mismatch", str(exc)) from exc
    requested_scenario_fingerprint = scenario_fingerprint(node_scenario)
    requested_spot_fingerprint = solver_spot_fingerprint(expected_spot)
    if (
        requested_scenario_fingerprint != provenance.scenario_fingerprint
        or requested_spot_fingerprint != provenance.spot_fingerprint
    ):
        raise SolverAssessmentError(
            "solver_artifact_mismatch",
            "solver artifact does not match the requested scenario/node",
            details={
                "expectedScenarioFingerprint": provenance.scenario_fingerprint,
                "requestedScenarioFingerprint": requested_scenario_fingerprint,
                "expectedSpotFingerprint": provenance.spot_fingerprint,
                "requestedSpotFingerprint": requested_spot_fingerprint,
            },
        )
    if tuple(sorted((oop_seat, ip_seat))) != tuple(sorted(provenance.active_seats)):
        raise SolverAssessmentError(
            "solver_artifact_mismatch",
            "solver artifact active seats do not match the requested node",
        )

    return SolverPolicyAdapter(
        job["result"],
        oop_seat=oop_seat,
        ip_seat=ip_seat,
        reference_pot=int(node_replay.final_state.pot),
        policy_sequence=provenance.policy_sequence,
        actor_seat=provenance.actor_seat,
        confidence="grounded",
    ), int(node_replay.final_state.pot)


def _unscored(
    reason: str,
    *,
    source: str | None = None,
    confidence: str | None = None,
    action_mapping: ReviewSolverActionMapping | None = None,
) -> ReviewSolverAssessment:
    return ReviewSolverAssessment(
        status="unscored",
        reason=reason,
        source=source,
        confidence=confidence,
        action_mapping=action_mapping,
    )


def _mapping_from(action_match: ActionMatch) -> ReviewSolverActionMapping:
    return ReviewSolverActionMapping(
        status=action_match.status.value,
        policy_action=action_match.policy_action,
        observed_size=(
            float(action_match.observed_size) if action_match.observed_size is not None else None
        ),
        mapped_size=(
            float(action_match.mapped_size) if action_match.mapped_size is not None else None
        ),
        off_tree=action_match.off_tree,
    )
