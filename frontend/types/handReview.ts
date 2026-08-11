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

export type ReviewSolverThresholdMetadata = {
  mixedThreshold: number;
  kind: "product_interpretation";
};

export type ReviewSolverActionMapping = {
  status: "exact" | "nearest_size" | "unsupported";
  policyAction: string;
  observedSize?: number | null;
  mappedSize?: number | null;
  offTree: boolean;
};

export type ReviewSolverAssessment = {
  status: "primary" | "mixed" | "rare" | "absent" | "unscored";
  reason?: string | null;
  source?: string | null;
  confidence?: string | null;
  actualFrequency?: number | null;
  primaryAction?: string | null;
  thresholdMetadata?: ReviewSolverThresholdMetadata | null;
  actionMapping?: ReviewSolverActionMapping | null;
};

export type HandReviewAction = {
  actionId: string;
  sequence: number;
  street: string;
  actorSeat: number;
  actionType: string;
  amount?: number;
  amountType?: string;
};

export type HandReviewState = {
  street: string;
  actorSeat: number | null;
  board: string[];
  pot: number;
  stacks: Record<string, number>;
  bets: Record<string, number>;
  foldedSeats: number[];
  handInProgress: boolean;
  legalActions: {
    actorSeat: number | null;
    actions: string[];
    callAmount: number | null;
    minRaiseTo: number | null;
    maxRaiseTo: number | null;
    explanations: Record<string, string>;
  };
};

export type HandReviewEvidenceBundle = {
  items: Array<{
    evidenceId: string;
    kind: string;
    value: unknown;
    sourceLevel: string;
    description: string;
  }>;
  [key: string]: unknown;
};

export type HandReviewAnalysisSummary = {
  analysisVersion: string;
  metrics: Record<string, unknown>;
  hand: Record<string, unknown> | null;
  board: Record<string, unknown>;
  equity: Record<string, unknown> | null;
  multiwayEquity: Record<string, unknown> | null;
  rangeAnalysis: Record<string, unknown> | null;
  rangeComparison: Record<string, unknown> | null;
  strategyMatch: Record<string, unknown> | null;
  [key: string]: unknown;
};

/** Evidence-addressed teaching returned by the whole-hand review endpoint. */
export type HandReviewTeachingText = {
  text: string;
  evidenceReferences: Array<{ evidenceId: string }>;
  containsNumbers: boolean;
};

export type DecisionTeachingResponse = {
  teachingVersion: string;
  mode: "solver_grounded" | "principle_only";
  provider: "local";
  summary: HandReviewTeachingText;
  keyPoints: HandReviewTeachingText[];
  uncertainty: HandReviewTeachingText;
  mistakeTags: string[];
};

export type PriorityFindingResponse = {
  actionId: string;
  category: "solver_deviation";
  mistakeTag: "solver_rare_action" | "solver_absent_action";
  severity: "review";
  summary: HandReviewTeachingText;
};

export type WholeHandSummaryResponse = {
  teachingVersion: string;
  summary: string;
  uncertainty: string;
};

/** Wire contract returned by POST /v1/hand-reviews (camelCase). */
export type DecisionReviewResponse = {
  decisionReviewVersion: string;
  actionId: string;
  eventSequence: number;
  decisionSequence: number;
  street: string;
  actorSeat: number;
  actualAction: HandReviewAction;
  stateBeforeAction: HandReviewState;
  analysisSummary: HandReviewAnalysisSummary;
  evidenceBundleId: string;
  evidenceBundle: HandReviewEvidenceBundle;
  warnings: string[];
  rangeUpdate: ReviewRangeUpdate;
  solverAssessment: ReviewSolverAssessment;
  teaching: DecisionTeachingResponse | null;
};

export type HandReviewResponse = {
  handReviewVersion: string;
  handSummary: { decisionCount: number; reviewedActionIds: string[] };
  decisionReviews: DecisionReviewResponse[];
  wholeHandSummary: WholeHandSummaryResponse | null;
  priorityFindings: PriorityFindingResponse[];
  uncertainty: string[];
};

export type HandReviewApiResponse = {
  schemaVersion: number;
  requestId: string;
  executionMs: number;
  review: HandReviewResponse;
};

export type DecisionReview = {
  actionId: string;
  eventSequence: number;
  decisionSequence: number;
  street: string;
  actorSeat: number;
  actualAction: string;
  actualActionEvent?: HandReviewAction;
  stateBeforeAction?: HandReviewState;
  analysisSummary?: HandReviewAnalysisSummary;
  evidenceBundleId?: string;
  evidenceBundle?: HandReviewEvidenceBundle;
  warnings?: string[];
  rangeUpdate: ReviewRangeUpdate;
  solverAssessment: ReviewSolverAssessment;
  teaching?: {
    teachingVersion?: string;
    mode?: "solver_grounded" | "principle_only";
    provider?: "local";
    summary: string;
    keyPoints?: string[];
    uncertainty?: string;
    mistakeTags?: string[];
    evidenceReferences?: string[];
  } | null;
};

export type PriorityFinding = {
  actionId: string;
  category: "solver_deviation";
  mistakeTag: "solver_rare_action" | "solver_absent_action";
  severity: "review";
  summary: string;
  evidenceReferences: string[];
};

export type WholeHandSummary = {
  teachingVersion: string;
  summary: string;
  uncertainty: string;
};
