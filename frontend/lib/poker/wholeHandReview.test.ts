import { describe, expect, it } from "vitest";

import type { Scenario } from "../../types/scenario";
import type { SolveJobRegistry } from "../solver/registry";
import {
  buildHandReviewRequest,
  eligibleSolverJobs,
  invalidateWholeHandReview,
  selectedReviewAssessment,
  type WholeHandReviewState,
} from "./wholeHandReview";

const scenario = { actionHistory: [] } as unknown as Scenario;

const registry: SolveJobRegistry = {
  eligible: {
    actionId: "eligible",
    decisionSequence: 3,
    actorSeat: 0,
    projectionFingerprint: "current",
    scenarioFingerprint: "scenario",
    spotFingerprint: "spot",
    stale: false,
    job: { jobId: "job-eligible", status: "solved" },
  },
  pending: {
    actionId: "pending",
    decisionSequence: 4,
    actorSeat: 1,
    projectionFingerprint: "current",
    scenarioFingerprint: "scenario",
    spotFingerprint: "spot",
    stale: false,
    job: { jobId: "job-pending", status: "running" },
  },
  stale: {
    actionId: "stale",
    decisionSequence: 5,
    actorSeat: 0,
    projectionFingerprint: "old",
    scenarioFingerprint: "scenario",
    spotFingerprint: "spot",
    stale: true,
    job: { jobId: "job-stale", status: "solved" },
  },
};

describe("whole-hand review state", () => {
  it("builds an API request from only eligible completed, non-stale jobs", () => {
    expect(eligibleSolverJobs(registry)).toEqual({ eligible: "job-eligible" });
    expect(buildHandReviewRequest(scenario, registry)).toEqual({
      scenario,
      solverJobs: { eligible: "job-eligible" },
    });
  });

  it("omits an empty mapping rather than fabricating solver coverage", () => {
    expect(buildHandReviewRequest(scenario, {})).toEqual({ scenario });
  });

  it("marks a completed response stale on scenario mutation while clearing a loading-only request", () => {
    const success = {
      status: "success",
      review: { decisionReviews: [] },
      error: null,
    } as unknown as WholeHandReviewState;
    expect(invalidateWholeHandReview(success)).toMatchObject({ status: "stale", review: success.review });

    const loading = { status: "loading", review: null, error: null } as WholeHandReviewState;
    expect(invalidateWholeHandReview(loading)).toEqual({ status: "idle", review: null, error: null });
  });

  it("projects only the selected action's backend solver assessment", () => {
    const review = {
      decisionReviews: [
        { actionId: "a1", solverAssessment: { status: "mixed" } },
        { actionId: "a2", solverAssessment: { status: "unscored" } },
      ],
    } as unknown as WholeHandReviewState["review"];
    expect(selectedReviewAssessment(review, "a1")).toEqual({ status: "mixed" });
    expect(selectedReviewAssessment(review, "missing")).toBeNull();
    expect(selectedReviewAssessment(review, null)).toBeNull();
  });
});
