import type { HandReviewApiResponse } from "../types/handReview";

export function handReviewResponseFixture(): HandReviewApiResponse {
  return {
    schemaVersion: 1,
    requestId: "req-review-1",
    executionMs: 3.5,
    review: {
      handReviewVersion: "hand-review-1",
      handSummary: { decisionCount: 1, reviewedActionIds: ["a1"] },
      wholeHandSummary: {
        teachingVersion: "hand-review-whole-hand-1",
        summary: "整手需要优先复盘翻牌圈行动。",
        uncertainty: "没有覆盖所有节点的 Solver 结果。",
      },
      priorityFindings: [{
        actionId: "a1",
        category: "solver_deviation",
        mistakeTag: "solver_rare_action",
        severity: "review",
        summary: {
          text: "翻牌圈行动值得优先复盘。",
          evidenceReferences: [{ evidenceId: "state-a1" }],
          containsNumbers: false,
        },
      }],
      uncertainty: ["solver assessment is not available"],
      decisionReviews: [{
        decisionReviewVersion: "decision-review-1",
        actionId: "a1",
        eventSequence: 1,
        decisionSequence: 0,
        street: "preflop",
        actorSeat: 0,
        actualAction: { actionId: "a1", sequence: 1, street: "preflop", actorSeat: 0, actionType: "raise_to", amount: 250, amountType: "by" },
        stateBeforeAction: {
          street: "preflop", actorSeat: 0, board: [], pot: 150,
          stacks: { "0": 9950, "1": 9900 }, bets: { "0": 50, "1": 100 }, foldedSeats: [], handInProgress: true,
          legalActions: { actorSeat: 0, actions: ["fold", "call", "raise_to"], callAmount: 50, minRaiseTo: 250, maxRaiseTo: 9950, explanations: {} },
        },
        analysisSummary: {
          analysisVersion: "analysis-1", metrics: {}, hand: null, board: { board: [] }, equity: null,
          multiwayEquity: null, rangeAnalysis: null, rangeComparison: null, strategyMatch: null,
        },
        evidenceBundleId: "evidence-a1",
        evidenceBundle: { items: [{ evidenceId: "state-a1", kind: "state", value: {}, sourceLevel: "deterministic", description: "state before action" }] },
        warnings: [],
        rangeUpdate: { status: "unavailable", reason: "range review is not available" },
        solverAssessment: { status: "unscored", reason: "solver assessment is not available" },
        teaching: {
          teachingVersion: "hand-review-teaching-1",
          mode: "principle_only",
          provider: "local",
          summary: {
            text: "基于本节点证据给出原则性说明。",
            evidenceReferences: [{ evidenceId: "state-a1" }],
            containsNumbers: false,
          },
          keyPoints: [],
          uncertainty: {
            text: "没有 Solver 覆盖。",
            evidenceReferences: [],
            containsNumbers: false,
          },
          mistakeTags: [],
        },
      }],
    },
  };
}
