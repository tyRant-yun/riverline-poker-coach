/** Minimal presentation contract for the hand-review workbench shell.
 *
 * The list and card deliberately receive already-derived facts. They do not
 * replay a hand, call an API, or infer a solver/range conclusion.
 */

export type ReviewRangeUpdate = {
  status: "available" | "unavailable";
  source?: string | null;
  reason?: string | null;
};

export type ReviewSolverAssessment = {
  status: "primary" | "mixed" | "rare" | "absent" | "unscored";
  actualFrequency?: number | string | null;
  primaryAction?: string | null;
  source?: string | null;
  reason?: string | null;
};

export type DecisionReview = {
  actionId: string;
  eventSequence: number;
  decisionSequence: number;
  street: string;
  actorSeat: number;
  actualAction: string;
  rangeUpdate: ReviewRangeUpdate;
  solverAssessment: ReviewSolverAssessment;
  teaching?: { summary: string } | null;
};
