"""A deterministic local teacher that cannot invent quantitative facts."""

from __future__ import annotations

from decimal import Decimal

from poker_coach.analysis import AnalysisResult, analyze_scenario
from poker_coach.domain.models import (
    AnalysisLevel,
    EvidenceBundle,
    EvidenceReference,
    LegalActions,
    RecommendedAction,
    ScenarioSpec,
    TeachingResponse,
    TeachingText,
)
from poker_coach.rules import PokerKitAdapter
from poker_coach.strategy.models import MatchLevel

from .tools import TeachingToolGateway


class TeachingService:
    """Generate structured explanations from facts supplied by the analysis core.

    This is intentionally a local principle-teaching fallback. A future LLM
    adapter must consume the same read-only evidence methods and return the
    same TeachingResponse contract.
    """

    version = "teaching-core-0.1"
    prompt_version = "teaching-prompt-0.1"
    provider = "local"

    def __init__(self, adapter: PokerKitAdapter | None = None):
        self.adapter = adapter or PokerKitAdapter()

    def explain(
        self,
        scenario: ScenarioSpec,
        *,
        analysis: AnalysisResult | None = None,
        depth: str = "intermediate",
        user_question: str | None = None,
    ) -> TeachingResponse:
        if depth not in {"beginner", "intermediate", "advanced"}:
            raise ValueError("depth must be beginner, intermediate, or advanced")
        analysis = analysis or analyze_scenario(scenario, adapter=self.adapter)
        tools = TeachingToolGateway(scenario, analysis, adapter=self.adapter)
        scenario = tools.get_normalized_scenario()
        evidence = tools.get_evidence_bundle()
        legal_actions = tools.get_legal_actions()
        refs = _refs
        pot_ref = refs("rules.pot")
        equity_ref = refs("equity.hero") if analysis.equity else None
        required_ref = refs("math.required_equity")
        spr_ref = refs("math.spr") if analysis.metrics.spr is not None else None
        strategy_match = tools.get_strategy_match()
        strategy_level_ref = refs("strategy.match_level") if strategy_match else None
        strategy_difference_ref = refs("strategy.differences") if strategy_match else None
        strategy_recommendation_ref = refs("strategy.recommendations") if strategy_match else None

        if analysis.equity is None:
            summary = TeachingText(
                text="当前可以先从规则、底池结构和牌力理解这个节点；由于缺少可靠的对手具体牌或范围，不能给出数值 Equity 或精确策略频率。",
                evidenceReferences=[pot_ref],
            )
            recommendation = ()
            basis = (
                TeachingText(
                    text="这是 principle_only 教学：它解释已知事实和分析假设，不把启发式结论包装成 GTO。",
                    evidenceReferences=[refs("equity.status")],
                ),
            )
        else:
            hero_equity = analysis.equity.hero_equity
            required = analysis.metrics.required_equity
            action = self._principle_action(legal_actions, hero_equity, required)
            summary = TeachingText(
                text=(
                    f"当前底池为 {analysis.metrics.current_pot} 筹码；在给定牌面和对手假设下，"
                    f"Hero equity 为 {hero_equity:.3f}，跟注所需最低权益为 {required:.3f}。"
                ),
                containsNumbers=True,
                evidenceReferences=tuple(ref for ref in (pot_ref, equity_ref, required_ref) if ref),
            )
            recommendation = (
                RecommendedAction(
                    action=action,
                    evidenceReferences=tuple(ref for ref in (equity_ref, required_ref, refs("rules.legal_actions")) if ref),
                ),
            )
            basis = (
                TeachingText(
                    text="这个行动是基于底池赔率与摊牌 Equity 的原则比较，不是 Solver 频率，也没有隐含 EV 结论。",
                    evidenceReferences=tuple(ref for ref in (equity_ref, required_ref) if ref),
                ),
            )

        strategy_recommendations = ()
        legal_action_names = {action.value for action in legal_actions.actions}
        if (
            strategy_match
            and strategy_match.level in {MatchLevel.EXACT, MatchLevel.COMPATIBLE}
            and strategy_match.recommendations
        ):
            strategy_recommendations = tuple(
                RecommendedAction(
                    action=item.action,
                    frequency=item.frequency if strategy_match.can_quote_frequencies else None,
                    ev=item.ev if strategy_match.can_quote_frequencies else None,
                    evidenceReferences=(strategy_recommendation_ref,),
                )
                for item in strategy_match.recommendations
                if strategy_recommendation_ref is not None and item.action in legal_action_names
            )
            if strategy_recommendations:
                recommendation = strategy_recommendations
                basis = basis + (
                    TeachingText(
                        text=(
                            f"策略库返回 {strategy_match.level.value} 匹配；这些是带来源的策划建议，"
                            "不是未提供的 Solver 频率。"
                        ),
                        evidenceReferences=tuple(
                            ref
                            for ref in (
                                strategy_level_ref,
                                strategy_recommendation_ref,
                                strategy_difference_ref,
                            )
                            if ref is not None
                        ),
                    ),
                )

        key_reasons = [
            TeachingText(
                text=f"Hero 当前牌力分类为 {analysis.hand.made_hand}。",
                evidenceReferences=[refs("hand.made_hand")],
            ),
            TeachingText(
                text=f"牌面标签为：{', '.join(analysis.board.labels) or '未发公共牌'}。",
                evidenceReferences=[refs("board.labels")],
            ),
        ]
        if analysis.hand.draws:
            key_reasons.append(
                TeachingText(
                    text=f"检测到听牌：{', '.join(draw.value for draw in analysis.hand.draws)}；出路只在当前假设下成立。",
                    evidenceReferences=[refs("hand.draws"), refs("hand.out_count")],
                )
            )
        if spr_ref and depth != "beginner":
            key_reasons.append(
                TeachingText(
                    text=f"SPR 为 {analysis.metrics.spr:.3f}，它描述有效筹码相对于底池的结构，不单独决定行动。",
                    containsNumbers=True,
                    evidenceReferences=[spr_ref],
                )
            )
        if depth == "advanced" and analysis.range_analysis is not None:
            key_reasons.append(
                TeachingText(
                    text=(
                        f"范围包含 {analysis.range_analysis.total_combos} 个有效组合，"
                        f"其中价值组合分类为 {analysis.range_analysis.value_combos} 个；"
                        "这些分类是当前启发式范围分析，不是 Solver 频率。"
                    ),
                    containsNumbers=True,
                    evidenceReferences=(
                        refs("range.total_combos"),
                        refs("range.value_combos"),
                        refs("range.heuristic"),
                    ),
                )
            )

        uncertainty = TeachingText(
            text=(
                (
                    f"策略库匹配等级为 {strategy_match.level.value}；当前没有可引用的精确 Solver 频率，"
                    "建议仅作为带来源的原则或策划教学。"
                )
                if strategy_match
                else (
                    "没有匹配的 Solver 策略数据；所有行动建议都应理解为基于当前证据的原则教学。"
                    if analysis.equity is not None
                    else "缺少对手范围或具体底牌，策略结论不确定性较高。"
                )
            ),
            evidenceReferences=(
                [strategy_level_ref, strategy_difference_ref]
                if strategy_match and strategy_level_ref and strategy_difference_ref
                else [refs("equity.status")]
                if analysis.equity is None
                else [refs("assumptions.equity_algorithm")]
            ),
        )
        response = TeachingResponse(
            explanationDepth=depth,
            summary=summary,
            recommendedActions=recommendation,
            recommendationBasis=basis,
            assumptions=(
                TeachingText(
                    text="用户输入的牌面、行动历史和范围被视为事实输入；自由文本问题只作为教学问题，不会改写牌局。",
                    evidenceReferences=[refs("assumptions.equity_algorithm")],
                ),
            ),
            keyReasons=tuple(key_reasons),
            alternativeLines=(
                TeachingText(
                    text=f"可用合法行动包括：{', '.join(action.value for action in legal_actions.actions) or '无'}。",
                    evidenceReferences=[refs("rules.legal_actions")],
                ),
            ),
            futureStreetPlan=(
                TeachingText(
                    text="下一街应重新评估牌面结构、有效筹码和范围，而不是机械沿用当前结论。",
                    evidenceReferences=[refs("board.labels"), refs("math.effective_stack")],
                ),
            ),
            commonMistake=TeachingText(
                text="常见错误是把单个改善牌的数量直接当成干净出路，或把原理分析说成精确 GTO。",
                evidenceReferences=[refs("hand.out_count"), refs("assumptions.equity_algorithm")],
            ),
            conceptTags=tuple(sorted(set(("pot_odds", "range_assumptions", *[draw.value for draw in analysis.hand.draws])))),
            uncertainty=uncertainty,
            evidenceReferences=tuple(item for item in (equity_ref, required_ref, pot_ref) if item),
            followUpQuestion=user_question or "你想把哪个假设改成反事实场景？",
            practiceQuestion=None,
        )
        response.validate_evidence_references(evidence)
        return response

    def _legal_actions_at_node(self, scenario: ScenarioSpec) -> LegalActions:
        prefix = scenario.model_copy(
            update={"action_history": scenario.action_history[: scenario.decision_point.after_sequence]}
        )
        return self.adapter.replay(prefix).final_state.legal_actions

    @staticmethod
    def _principle_action(legal_actions: LegalActions, hero_equity: Decimal, required: Decimal) -> str:
        if hero_equity >= required and "call" in {action.value for action in legal_actions.actions}:
            return "call"
        if hero_equity < required and "fold" in {action.value for action in legal_actions.actions}:
            return "fold"
        if "check" in {action.value for action in legal_actions.actions}:
            return "check"
        return legal_actions.actions[0].value if legal_actions.actions else "no_legal_action"


def _refs(*evidence_ids: str | None) -> EvidenceReference:
    evidence_id = next((value for value in evidence_ids if value), None)
    if evidence_id is None:
        raise ValueError("an evidence reference requires an evidence id")
    return EvidenceReference(evidenceId=evidence_id)
