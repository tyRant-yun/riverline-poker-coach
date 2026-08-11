import type { ReviewSolverAssessment } from "../../types/handReview";

export const SOLVER_ASSESSMENT_STATUS: Record<
  ReviewSolverAssessment["status"],
  { label: string; className: string }
> = {
  primary: { label: "符合主策略", className: "source-tag green" },
  mixed: { label: "可接受混频", className: "status-pill" },
  rare: { label: "明显偏离常用策略", className: "source-tag" },
  absent: { label: "Solver 不采用该行动", className: "danger-button" },
  unscored: { label: "无 Solver 结论", className: "status-pill" },
};

export function formatSolverFrequency(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return `${Math.round(value * 100)}%`;
}

export function solverAssessmentDetails(assessment: ReviewSolverAssessment): string[] {
  const frequency = formatSolverFrequency(assessment.actualFrequency);
  const mapping = assessment.actionMapping;
  return [
    frequency ? `实际行动频率 ${frequency}` : null,
    assessment.primaryAction ? `主策略：${assessment.primaryAction}` : null,
    assessment.source ? `来源：${assessment.source}` : null,
    assessment.confidence ? `置信度：${assessment.confidence}` : null,
    mapping?.offTree
      ? `行动映射：${mapping.policyAction || "未匹配"}（off-tree，保持无 Solver 结论）`
      : null,
  ].filter((detail): detail is string => Boolean(detail));
}
