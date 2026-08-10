"""Read-only tool boundary for a future structured teaching Agent."""

from __future__ import annotations

from typing import Literal

from poker_coach.analysis import AnalysisResult
from poker_coach.domain.models import EvidenceBundle, LegalActions, RangeSpec, ScenarioSpec
from poker_coach.learning.models import ValidatedPractice
from poker_coach.learning.service import LearningService
from poker_coach.rules import PokerKitAdapter
from poker_coach.strategy.models import StrategyMatch


RangeSide = Literal["hero", "villain"]


class TeachingToolGateway:
    """Expose only facts and approved operations to teaching orchestration.

    The gateway deliberately has no setters for ScenarioSpec or AnalysisResult.
    A model adapter can call these methods, but rule replay, equity, combo
    counts, and strategy facts remain owned by the domain services.
    """

    tool_names = frozenset(
        {
            "get_normalized_scenario",
            "get_legal_actions",
            "get_evidence_bundle",
            "get_range",
            "get_strategy_match",
            "get_term",
            "create_practice",
        }
    )

    _TERMS = {
        "pot_odds": "底池赔率比较跟注成本与跟注后底池，不能单独替代范围分析。",
        "spr": "SPR 是有效筹码与当前底池的比例，用来描述后续下注空间。",
        "blocker": "Blocker 是已知手牌对对手组合构成的 card removal 影响。",
        "equity": "Equity 是在当前牌面、范围和算法假设下的获胜与平局份额。",
    }

    def __init__(
        self,
        scenario: ScenarioSpec,
        analysis: AnalysisResult,
        *,
        adapter: PokerKitAdapter | None = None,
    ):
        self._scenario = scenario.model_copy(deep=True)
        self._analysis = analysis
        self._adapter = adapter or PokerKitAdapter()

    def get_normalized_scenario(self) -> ScenarioSpec:
        return self._scenario.model_copy(deep=True)

    def get_legal_actions(self) -> LegalActions:
        node = self._scenario.model_copy(
            update={
                "action_history": self._scenario.action_history[
                    : self._scenario.decision_point.after_sequence
                ]
            }
        )
        return self._adapter.replay(node).final_state.legal_actions

    def get_evidence_bundle(self) -> EvidenceBundle:
        return self._analysis.evidence.model_copy(deep=True)

    def get_range(self, side: RangeSide) -> RangeSpec | None:
        if side not in {"hero", "villain"}:
            raise ValueError("side must be hero or villain")
        value = self._scenario.hero_range if side == "hero" else self._scenario.villain_range
        return value.model_copy(deep=True) if value is not None else None

    def get_strategy_match(self) -> StrategyMatch | None:
        return (
            self._analysis.strategy_match.model_copy(deep=True)
            if self._analysis.strategy_match is not None
            else None
        )

    def get_term(self, term: str) -> str:
        try:
            return self._TERMS[term]
        except KeyError as exc:
            raise ValueError(f"unknown teaching term: {term}") from exc

    def create_practice(
        self,
        *,
        profile_id: str,
        mistake_tag: str | None = None,
    ) -> ValidatedPractice:
        return LearningService(self._adapter).generate_practice(
            self._scenario,
            profile_id=profile_id,
            mistake_tag=mistake_tag,
        )
