import type {
  DecisionReview,
  DecisionReviewResponse,
  HandReviewApiResponse,
  HandReviewResponse,
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
    solverAssessment: review.solverAssessment,
  };
}

export type AdaptedHandReview = Omit<HandReviewResponse, "decisionReviews"> & {
  decisionReviews: DecisionReview[];
};

export function adaptHandReviewResponse(response: HandReviewApiResponse): AdaptedHandReview {
  return {
    ...response.review,
    decisionReviews: response.review.decisionReviews.map(adaptDecisionReview),
  };
}
