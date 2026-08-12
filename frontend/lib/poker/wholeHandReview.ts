// Whole-hand review request/state helpers. They deliberately only move
// scenario, persisted solver-job identity, and backend-provided review facts;
// no poker conclusion is computed in the browser.

import type { AdaptedHandReview } from "../api/handReviewAdapter";
import type { ReviewSolverAssessment } from "../../types/handReview";
import type { Scenario } from "../../types/scenario";
import type { SolveJobRegistry } from "../solver/registry";

export type HandReviewRequest = {
  scenario: Scenario;
  solverJobs?: Record<string, string>;
};

export type WholeHandReviewState = {
  status: "idle" | "loading" | "success" | "error" | "stale";
  review: AdaptedHandReview | null;
  error: string | null;
};

export const emptyWholeHandReviewState: WholeHandReviewState = {
  status: "idle",
  review: null,
  error: null,
};

/** Only completed, non-stale jobs can identify a grounded review artifact. */
export function eligibleSolverJobs(registry: SolveJobRegistry): Record<string, string> {
  return Object.fromEntries(
    Object.entries(registry)
      .filter(([, entry]) => !entry.stale && entry.job.status === "solved" && Boolean(entry.job.jobId))
      .map(([actionId, entry]) => [actionId, entry.job.jobId]),
  );
}

/** Omit the mapping entirely when no persisted job is eligible. */
export function buildHandReviewRequest(scenario: Scenario, registry: SolveJobRegistry): HandReviewRequest {
  const solverJobs = eligibleSolverJobs(registry);
  return Object.keys(solverJobs).length ? { scenario, solverJobs } : { scenario };
}

export function invalidateWholeHandReview(state: WholeHandReviewState): WholeHandReviewState {
  return state.review
    ? { ...state, status: "stale", error: null }
    : { ...state, status: "idle", error: null };
}

/** Project only the selected action's backend assessment into Solver UI. */
export function selectedReviewAssessment(
  review: AdaptedHandReview | null,
  actionId: string | null,
): ReviewSolverAssessment | null {
  if (!review || !actionId) return null;
  return review.decisionReviews.find((decision) => decision.actionId === actionId)?.solverAssessment ?? null;
}
