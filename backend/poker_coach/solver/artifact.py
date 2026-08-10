"""Solver-backed StrategyArtifact conversion and registration."""

from __future__ import annotations

from decimal import Decimal

from poker_coach.domain.models import AnalysisLevel, ScenarioSpec
from poker_coach.strategy.features import features_for_scenario
from poker_coach.strategy.models import StrategyArtifact, StrategyRecommendation

from .analyzer import SolverAnalysis
from .cache import solve_hash
from .types import SolverNode, SolverSpot, SolveResult

_SOLVER_LICENSE = "AGPL-3.0 (solver output data)"


def hero_node_of(result: SolveResult, *, hero_is_button: bool) -> SolverNode:
    """Pick the dumped node belonging to the hero player.

    The sidecar dumps OOP as root (player 0) and the IP response node as
    player 1; the button player is IP postflop in heads-up.
    """
    if hero_is_button:
        if result.response_node is None:
            raise ValueError("solver result has no IP response node")
        return result.response_node
    return result.root


def solve_result_to_artifact(
    result: SolveResult,
    scenario: ScenarioSpec,
    spot: SolverSpot,
    analysis: SolverAnalysis,
) -> StrategyArtifact:
    """Convert a solved result into a registerable solver_backed artifact.

    Constraints are derived with the same feature extraction used by the
    matcher, so the originating scenario matches this artifact EXACTLY and
    the frequency gate (ADR-0003) opens for it.
    """
    features = features_for_scenario(scenario)
    hero_is_button = scenario.hero_seat == scenario.button_seat
    hero_node = hero_node_of(result, hero_is_button=hero_is_button)

    recommendations = _recommendations_from_node(hero_node, result)
    return StrategyArtifact(
        artifact_id=f"solver-{solve_hash(spot)[:12]}",
        name=f"solver {spot.street.value} {'/'.join(spot.board)}",
        version=result.metadata.version,
        source="postflop-solver sidecar",
        license=_SOLVER_LICENSE,
        creator=f"postflop-solver {result.metadata.version}",
        game_variant=scenario.game_variant,
        table_size=scenario.table_size,
        stack_min_bb=features.stack_bb,
        stack_max_bb=features.stack_bb,
        rake_signature=features.rake_signature,
        hero_position=features.hero_position,
        villain_position=features.villain_position,
        street=features.street,
        action_signature=features.action_signature,
        board_labels=features.board_labels,
        hero_range_id=features.hero_range_id,
        villain_range_id=features.villain_range_id,
        bet_size_signature=features.bet_size_signature,
        source_level=AnalysisLevel.SOLVER_BACKED,
        compatible_frequency_approved=False,
        quantitative_basis=(
            f"postflop-solver {result.metadata.version}, "
            f"exploitability {result.metadata.exploitability_chips:.3f} chips"
        ),
        assumptions=(
            f"solver spot: {spot.street.value}, pot {spot.starting_pot}, "
            f"stack {spot.effective_stack}",
        ),
        recommendations=recommendations,
    )


def _recommendations_from_node(
    node: SolverNode, result: SolveResult
) -> tuple[StrategyRecommendation, ...]:
    """Top actions by weighted range frequency, with the solver as basis."""
    total_weight = sum(hand.weight for hand in node.hands) or 1.0
    weighted: dict[str, float] = {}
    for hand in node.hands:
        for action, frequency in hand.strategy.items():
            weighted[action] = weighted.get(action, 0.0) + hand.weight * frequency
    ranked = sorted(weighted.items(), key=lambda item: item[1], reverse=True)[:3]
    basis = (
        f"postflop-solver {result.metadata.version} "
        f"(exploitability {result.metadata.exploitability_chips:.3f} chips)"
    )
    return tuple(
        StrategyRecommendation(
            action=action,
            summary=f"solver 均衡频率：{action}",
            frequency=Decimal(f"{frequency / total_weight:.4f}"),
            source_level=AnalysisLevel.SOLVER_BACKED,
            quantitative_basis=basis,
        )
        for action, frequency in ranked
    )
