import { describe, expect, it } from "vitest";
import { adaptHandReviewResponse } from "./handReviewAdapter";
import { handReviewResponseFixture } from "../../test/handReviewFixtures";

describe("hand review adapter", () => {
  it("maps wire actions for the existing list and preserves backend facts", () => {
    const adapted = adaptHandReviewResponse(handReviewResponseFixture());
    const review = adapted.decisionReviews[0];

    expect(review.actualAction).toBe("Raise to 250");
    expect(review.actualActionEvent?.actionType).toBe("raise_to");
    expect(review.stateBeforeAction?.board).toEqual([]);
    expect(review.analysisSummary?.analysisVersion).toBe("analysis-1");
    expect(review.evidenceBundleId).toBe("evidence-a1");
    expect(adapted.uncertainty).toEqual(["solver assessment is not available"]);
  });

  it("does not compute solver or range conclusions", () => {
    const adapted = adaptHandReviewResponse(handReviewResponseFixture());
    expect(adapted.decisionReviews[0].solverAssessment.status).toBe("unscored");
    expect(adapted.decisionReviews[0].rangeUpdate.status).toBe("unavailable");
  });

  it("adapts BE-04 teaching, whole-hand summary, and action-addressable findings without changing evidence references", () => {
    const adapted = adaptHandReviewResponse(handReviewResponseFixture());

    expect(adapted.decisionReviews[0].teaching).toMatchObject({
      mode: "principle_only",
      summary: "基于本节点证据给出原则性说明。",
      evidenceReferences: ["state-a1"],
    });
    expect(adapted.wholeHandSummary).toEqual({
      teachingVersion: "hand-review-whole-hand-1",
      summary: "整手需要优先复盘翻牌圈行动。",
      uncertainty: "没有覆盖所有节点的 Solver 结果。",
    });
    expect(adapted.priorityFindings).toEqual([{
      actionId: "a1",
      category: "solver_deviation",
      mistakeTag: "solver_rare_action",
      severity: "review",
      summary: "翻牌圈行动值得优先复盘。",
      evidenceReferences: ["state-a1"],
    }]);
  });

  it("preserves grounded solver fields and action mapping", () => {
    const response = handReviewResponseFixture();
    response.review.decisionReviews[0].solverAssessment = {
      status: "mixed",
      reason: null,
      source: "solver",
      confidence: "grounded",
      actualFrequency: 0.05,
      primaryAction: "Bet(250)",
      thresholdMetadata: { mixedThreshold: 0.05, kind: "product_interpretation" },
      actionMapping: {
        status: "exact",
        policyAction: "Bet(250)",
        observedSize: 250,
        mappedSize: 250,
        offTree: false,
      },
    };

    const adapted = adaptHandReviewResponse(response);
    expect(adapted.decisionReviews[0].solverAssessment).toEqual(
      response.review.decisionReviews[0].solverAssessment,
    );
  });
});
