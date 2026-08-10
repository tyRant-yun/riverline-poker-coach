"""Solver evidence items: every number the teaching layer may cite."""

from __future__ import annotations

from poker_coach.domain.models import AnalysisLevel, EvidenceItem

from .analyzer import SolverAnalysis
from .types import SolveResult


def solver_evidence_items(
    result: SolveResult, analysis: SolverAnalysis
) -> tuple[EvidenceItem, ...]:
    """Evidence for the solver facts exposed through TeachingToolGateway.

    All ids use the ``solver.*`` prefix so reference validation covers them
    like any other evidence; the descriptions label the value/bluff
    classification as a deterministic heuristic.
    """
    version = result.metadata.version
    items = [
        EvidenceItem(
            evidence_id="solver.version",
            kind="solver",
            value=version,
            source_level=AnalysisLevel.SOLVER_BACKED,
            source_version=version,
            description="求解引擎版本（postflop-solver sidecar）",
        ),
        EvidenceItem(
            evidence_id="solver.exploitability",
            kind="solver",
            value=result.metadata.exploitability_chips,
            unit="chips",
            source_level=AnalysisLevel.SOLVER_BACKED,
            source_version=version,
            description="求解结果的不可利用性（exploitability），越低越接近均衡",
        ),
        EvidenceItem(
            evidence_id="solver.range_bet_frequency",
            kind="solver",
            value=analysis.root.range_bet_frequency,
            unit="ratio",
            source_level=AnalysisLevel.SOLVER_BACKED,
            source_version=version,
            description="OOP 根节点整范围下注频率（含下注/加注/全下）",
        ),
        EvidenceItem(
            evidence_id="solver.primary_action",
            kind="solver",
            value=analysis.root.primary_action,
            source_level=AnalysisLevel.SOLVER_BACKED,
            source_version=version,
            description="OOP 根节点整范围加权后的主导动作",
        ),
    ]
    return tuple(items)
