"""Deterministic, evidence-bounded teaching for an ordered hand review."""

from __future__ import annotations

from poker_coach.domain.models import EvidenceBundle, EvidenceReference, TeachingText

from .models import (
    DecisionReview,
    DecisionTeaching,
    HandReviewResponse,
    PriorityFinding,
    WholeHandTeaching,
)


def compose_hand_review_teaching(review: HandReviewResponse) -> HandReviewResponse:
    """Attach one local teaching object to each decision without cross-node facts.

    This deliberately consumes an individual ``DecisionReview`` only.  It is
    therefore safe for an imported finished board: an early teaching object
    cannot observe later cards, actions, evidence, or solver artifacts.
    """

    decisions = tuple(
        decision.model_copy(update={"teaching": compose_decision_teaching(decision)})
        for decision in review.decision_reviews
    )
    findings = tuple(
        finding
        for decision in decisions
        for finding in _priority_findings(decision)
    )
    summary = _whole_hand_summary(decisions, findings)
    return review.model_copy(
        update={
            "decision_reviews": decisions,
            "whole_hand_summary": summary,
            "priority_findings": findings,
        }
    )


def compose_decision_teaching(review: DecisionReview) -> DecisionTeaching:
    """Create useful Chinese templates from one decision's bounded facts."""

    refs = _refs(review.evidence_bundle)
    action = review.actual_action.action_type.value
    hand = review.analysis_summary.hand
    board = review.analysis_summary.board
    points: list[TeachingText] = []
    if hand is not None:
        points.append(
            TeachingText(
                text=f"行动前的牌力分类为 {hand.made_hand}；先围绕这一节点可见信息检查 {action} 的理由。",
                evidenceReferences=_one(refs, "hand.made_hand"),
            )
        )
    points.append(
        TeachingText(
            text=f"牌面结构标签为：{', '.join(board.labels) or '未发公共牌'}。教学只使用该行动发生前已可见的牌面。",
            evidenceReferences=_one(refs, "board.labels"),
        )
    )

    assessment = review.solver_assessment
    tags: tuple[str, ...] = ()
    if assessment.status in {"rare", "absent"}:
        tag = "solver_rare_action" if assessment.status == "rare" else "solver_absent_action"
        tags = (tag,)
        summary = TeachingText(
            text="该行动与已验证的此节点 Solver 策略存在需要优先复盘的差异；这里不推断或编造 EV 损失。",
            evidenceReferences=_one(refs, "rules.legal_actions"),
        )
        mode = "solver_grounded"
    elif assessment.status in {"primary", "mixed"}:
        summary = TeachingText(
            text="该行动在已验证的此节点 Solver 策略中有对应支持；它仍应结合当前范围与假设理解，不等同于通用结论。",
            evidenceReferences=_one(refs, "rules.legal_actions"),
        )
        mode = "solver_grounded"
    else:
        summary = TeachingText(
            text="此处没有可评分的精确 Solver 结论；以下内容是基于规则、牌力与当前假设的原则教学，策略数据缺失只表示该节点没有评分。",
            evidenceReferences=_one(refs, "rules.legal_actions"),
        )
        mode = "principle_only"

    if review.range_update.status == "unavailable":
        points.append(
            TeachingText(
                text="该行动没有可用的范围策略更新；这表示 no_policy 或覆盖不足，不代表对实际行动的策略评价。",
                evidenceReferences=_one(refs, "rules.legal_actions"),
            )
        )
    if review.warnings:
        points.append(
            TeachingText(
                text="分析存在已记录的不确定性；请把结论理解为当前输入和假设下的复盘提示。",
                evidenceReferences=_one(refs, "assumptions"),
            )
        )
    uncertainty = TeachingText(
        text=(
            "没有精确策略或范围政策时，保留为 principle-only，不对实际行动作 Solver 评分。"
            if mode == "principle_only"
            else "Solver 只覆盖这个已验证节点；没有 action-specific EV 输出，因此不报告 EV 损失。"
        ),
        evidenceReferences=_one(refs, "assumptions"),
    )
    teaching = DecisionTeaching(
        mode=mode,
        summary=summary,
        key_points=tuple(points),
        uncertainty=uncertainty,
        mistake_tags=tags,
    )
    teaching.validate_evidence_references(review.evidence_bundle)
    return teaching


def _priority_findings(review: DecisionReview) -> tuple[PriorityFinding, ...]:
    teaching = review.teaching
    if teaching is None or not teaching.mistake_tags:
        return ()
    tag = teaching.mistake_tags[0]
    return (
        PriorityFinding(
            action_id=review.action_id,
            category="solver_deviation",
            mistake_tag=tag,
            summary=teaching.summary,
        ),
    )


def _whole_hand_summary(
    decisions: tuple[DecisionReview, ...], findings: tuple[PriorityFinding, ...]
) -> WholeHandTeaching:
    if findings:
        action_ids = "、".join(item.action_id for item in findings)
        return WholeHandTeaching(
            summary=f"整手复盘已按行动顺序生成；优先从 {action_ids} 对应的节点开始回看。",
            uncertainty="优先项仅来自已验证节点的实际行动频率，不包含未提供的 EV 损失。",
        )
    if any(item.solver_assessment.status == "unscored" for item in decisions):
        return WholeHandTeaching(
            summary="整手复盘已按行动顺序生成；当前没有可确认的 Solver 偏离优先项。",
            uncertainty="部分节点没有精确策略或范围政策，已保留为原则教学而非策略错误。",
        )
    return WholeHandTeaching(
        summary="整手复盘已按行动顺序生成；当前没有需要优先复盘的已验证 Solver 偏离。",
        uncertainty="结论仅汇总各行动已存在的教学事实，不补充跨节点推断。",
    )


def _refs(bundle: EvidenceBundle) -> dict[str, EvidenceReference]:
    return {item.evidence_id: EvidenceReference(evidenceId=item.evidence_id) for item in bundle.items}


def _one(refs: dict[str, EvidenceReference], suffix: str) -> tuple[EvidenceReference, ...]:
    for evidence_id, reference in refs.items():
        if evidence_id.endswith(suffix):
            return (reference,)
    # Every analysis bundle supplies at least one fact.  This fallback is still
    # node-local and avoids inventing a reference when optional evidence is absent.
    return (next(iter(refs.values())),) if refs else ()
