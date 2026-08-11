import type {
  DecisionReview,
  DecisionReviewResponse,
  HandReviewApiResponse,
  HandReviewResponse,
  PriorityFinding,
  PriorityFindingResponse,
  ReviewSolverAssessment,
  WholeHandSummary,
} from "../../types/handReview";

function actionText(action: DecisionReviewResponse["actualAction"]): string {
  const labels: Record<string, string> = {
    all_in: "All-in",
    raise_to: "Raise to",
    deal_flop: "Deal flop",
    deal_turn: "Deal turn",
    deal_river: "Deal river",
  };
  const label = labels[action.actionType] ?? action.actionType.replaceAll("_", " ");
  return action.amount === undefined ? label : `${label} ${action.amount}`;
}

function adaptSolverAssessment(assessment: ReviewSolverAssessment): ReviewSolverAssessment {
  return {
    status: assessment.status,
    reason: assessment.reason,
    source: assessment.source,
    confidence: assessment.confidence,
    actualFrequency: assessment.actualFrequency,
    primaryAction: assessment.primaryAction,
    thresholdMetadata: assessment.thresholdMetadata
      ? { ...assessment.thresholdMetadata }
      : assessment.thresholdMetadata,
    actionMapping: assessment.actionMapping ? { ...assessment.actionMapping } : assessment.actionMapping,
  };
}

function evidenceIds(references: Array<{ evidenceId: string }>): string[] {
  return references.map((reference) => reference.evidenceId);
}

function adaptPriorityFinding(finding: PriorityFindingResponse): PriorityFinding {
  return {
    actionId: finding.actionId,
    category: finding.category,
    mistakeTag: finding.mistakeTag,
    severity: finding.severity,
    summary: finding.summary.text,
    evidenceReferences: evidenceIds(finding.summary.evidenceReferences),
  };
}

/** Purely adapts the backend response; it does not infer poker facts. */
export function adaptDecisionReview(review: DecisionReviewResponse): DecisionReview {
  return {
    actionId: review.actionId,
    eventSequence: review.eventSequence,
    decisionSequence: review.decisionSequence,
    street: review.street,
    actorSeat: review.actorSeat,
    actualAction: actionText(review.actualAction),
    actualActionEvent: review.actualAction,
    stateBeforeAction: review.stateBeforeAction,
    analysisSummary: review.analysisSummary,
    evidenceBundleId: review.evidenceBundleId,
    evidenceBundle: review.evidenceBundle,
    warnings: review.warnings,
    rangeUpdate: review.rangeUpdate,
    solverAssessment: adaptSolverAssessment(review.solverAssessment),
    teaching: review.teaching
      ? {
        teachingVersion: review.teaching.teachingVersion,
        mode: review.teaching.mode,
        provider: review.teaching.provider,
        summary: review.teaching.summary.text,
        keyPoints: review.teaching.keyPoints.map((point) => point.text),
        uncertainty: review.teaching.uncertainty.text,
        mistakeTags: [...review.teaching.mistakeTags],
        evidenceReferences: [
          ...evidenceIds(review.teaching.summary.evidenceReferences),
          ...review.teaching.keyPoints.flatMap((point) => evidenceIds(point.evidenceReferences)),
          ...evidenceIds(review.teaching.uncertainty.evidenceReferences),
        ],
      }
      : null,
  };
}

export type AdaptedHandReview = Omit<HandReviewResponse, "decisionReviews" | "wholeHandSummary" | "priorityFindings"> & {
  decisionReviews: DecisionReview[];
  wholeHandSummary: WholeHandSummary | null;
  priorityFindings: PriorityFinding[];
};

export function adaptHandReviewResponse(response: HandReviewApiResponse): AdaptedHandReview {
  return {
    ...response.review,
    decisionReviews: response.review.decisionReviews.map(adaptDecisionReview),
    wholeHandSummary: response.review.wholeHandSummary
      ? { ...response.review.wholeHandSummary }
      : null,
    priorityFindings: response.review.priorityFindings.map(adaptPriorityFinding),
  };
}
