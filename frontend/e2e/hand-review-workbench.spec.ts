import { expect, test } from "@playwright/test";

type Action = {
  actionId: string;
  sequence: number;
  street: string;
  actorSeat: number;
  actionType: string;
  amount?: number;
  amountType?: string;
};

// This is a real, backend-validated partial hand. The test appends the rest
// through ActionBar, rather than reimplementing any poker state transitions.
const FLOP_CHECKDOWN_START = {
  schemaVersion: 1,
  gameVariant: "nlhe",
  tableSize: 2,
  smallBlind: 50,
  bigBlind: 100,
  buttonSeat: 0,
  heroSeat: 0,
  seats: [
    { seatId: 0, startingStack: 10_000, position: "button" },
    { seatId: 1, startingStack: 10_000, position: "big_blind" },
  ],
  heroHoleCards: ["As", "Kd"],
  villainHoleCards: ["Qh", "Jc"],
  board: ["2c", "7d", "Jh", "9s", "3h"],
  heroRange: {
    rangeId: "button-range",
    name: "Button range",
    version: "1",
    source: "user_defined",
    matrix169: { "76s": "1" },
  },
  villainRange: {
    rangeId: "bb-range",
    name: "BB range",
    version: "1",
    source: "user_defined",
    matrix169: { "T8s": "1" },
  },
  actionHistory: [
    { actionId: "a1", sequence: 1, street: "preflop", actorSeat: 0, actionType: "call", amount: 50, amountType: "cost" },
    { actionId: "a2", sequence: 2, street: "preflop", actorSeat: 1, actionType: "check" },
    { actionId: "a3", sequence: 3, street: "flop", actorSeat: 0, actionType: "deal_flop" },
    { actionId: "a4", sequence: 4, street: "flop", actorSeat: 1, actionType: "check" },
  ],
  decisionPoint: { street: "flop", actorSeat: 0, afterSequence: 4 },
  assumptions: { equityAlgorithm: "monte_carlo", simulationTrials: 50, randomSeed: 17 },
};

function beliefFixture(afterSequence: number, seatId: number) {
  return {
    seatId,
    street: "flop",
    afterSequence,
    available: true,
    unavailableReason: null,
    source: "fixture",
    confidence: "deterministic",
    priorMass: "1",
    retainedMass: "0.55",
    retainedFraction: "0.55",
    combos: null,
    matrix169: {
      T8s: {
        reachMass: "0.55",
        probabilityMass: "1",
        comboCount: 4,
        priorProbabilityMass: "1",
        delta: "0",
        multiplier: "0.55",
      },
    },
    update: {
      actionType: "check",
      actionLabel: "Check",
      observedSize: null,
      mappedSize: null,
      offTree: false,
      policySource: "fixture",
      node: "flop-check",
    },
  };
}

function reviewFixture(actions: Action[]) {
  const playerActions = actions.filter((action) => !action.actionType.startsWith("deal_"));
  const decisionReviews = playerActions.map((action) => {
    const solverGrounded = action.actionId === "a4";
    const evidenceId = `state-${action.actionId}`;
    return {
      decisionReviewVersion: "decision-review-1",
      actionId: action.actionId,
      eventSequence: action.sequence,
      decisionSequence: action.sequence - 1,
      street: action.street,
      actorSeat: action.actorSeat,
      actualAction: action,
      stateBeforeAction: {
        street: action.street,
        actorSeat: action.actorSeat,
        board: action.street === "preflop" ? [] : ["2c", "7d", "Jh"],
        pot: 200,
        stacks: { "0": 9_900, "1": 9_900 },
        bets: { "0": 0, "1": 0 },
        foldedSeats: [],
        handInProgress: true,
        legalActions: { actorSeat: action.actorSeat, actions: ["check", "bet"], callAmount: null, minRaiseTo: 100, maxRaiseTo: 9_900, explanations: {} },
      },
      analysisSummary: {
        analysisVersion: "fixture-1",
        metrics: {}, hand: null, board: { board: [] }, equity: null,
        multiwayEquity: null, rangeAnalysis: null, rangeComparison: null, strategyMatch: null,
      },
      evidenceBundleId: `evidence-${action.actionId}`,
      evidenceBundle: { items: [{ evidenceId, kind: "state", value: {}, sourceLevel: "deterministic", description: "action-before state" }] },
      warnings: [],
      rangeUpdate: solverGrounded ? { status: "available", source: "fixture" } : { status: "unavailable", reason: "no_policy" },
      solverAssessment: solverGrounded
        ? {
          status: "mixed",
          source: "solver",
          confidence: "grounded",
          actualFrequency: 0.05,
          primaryAction: "Bet(250)",
          thresholdMetadata: { mixedThreshold: 0.05, kind: "product_interpretation" },
          actionMapping: { status: "exact", policyAction: "Check", offTree: false },
        }
        : { status: "unscored", reason: "No grounded Solver artifact covers this decision." },
      teaching: {
        teachingVersion: "hand-review-teaching-1",
        mode: solverGrounded ? "solver_grounded" : "principle_only",
        provider: "local",
        summary: {
          text: solverGrounded ? "翻牌圈 Check 是可接受混频。" : "此节点只有原则性教学，未伪造 Solver 结论。",
          evidenceReferences: [{ evidenceId }],
          containsNumbers: false,
        },
        keyPoints: [],
        uncertainty: { text: solverGrounded ? "覆盖仅限这个节点。" : "no_policy", evidenceReferences: [], containsNumbers: false },
        mistakeTags: [],
      },
    };
  });
  return {
    schemaVersion: 1,
    requestId: "workbench-e2e-review",
    executionMs: 1,
    review: {
      handReviewVersion: "hand-review-1",
      handSummary: { decisionCount: decisionReviews.length, reviewedActionIds: decisionReviews.map((review) => review.actionId) },
      decisionReviews,
      wholeHandSummary: {
        teachingVersion: "hand-review-whole-hand-1",
        summary: "整手按真实行动顺序复盘；只有一个节点具备 Solver 覆盖。",
        uncertainty: "其余节点保持原则性说明。",
      },
      priorityFindings: [{
        actionId: "a4",
        category: "solver_deviation",
        mistakeTag: "solver_rare_action",
        severity: "review",
        summary: { text: "翻牌圈 Check 值得优先复盘。", evidenceReferences: [{ evidenceId: "state-a4" }], containsNumbers: false },
      }],
      uncertainty: ["unscored nodes retain no_policy coverage"],
    },
  };
}

test("reviews a completed hand across belief, action-before solver, teaching, navigation, and staleness", async ({ page }) => {
  test.setTimeout(60_000);
  const beliefRequests: Array<{ seatId: number; afterSequence: number }> = [];
  const solverSubmissions: Action[][] = [];
  const reviewRequests: Array<{ solverJobs?: Record<string, string> }> = [];

  // Importing normally persists a saved scenario. Keep this test's fixture
  // ephemeral so it cannot affect the legacy E2E suite's saved-history UI.
  await page.route("**/v1/scenarios", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const request = route.request().postDataJSON() as { scenario: typeof FLOP_CHECKDOWN_START; title: string };
    await route.fulfill({ contentType: "application/json", json: {
      scenario: {
        scenarioId: "workbench-e2e",
        title: request.title,
        scenario: request.scenario,
        revisionNo: 1,
        updatedAt: "2026-08-11T00:00:00Z",
      },
    } });
  });
  await page.route("**/v1/ranges/belief", async (route) => {
    const request = route.request().postDataJSON() as { seatId: number; afterSequence: number };
    beliefRequests.push({ seatId: request.seatId, afterSequence: request.afterSequence });
    await route.fulfill({ contentType: "application/json", json: beliefFixture(request.afterSequence, request.seatId) });
  });
  await page.route("**/v1/solve/jobs**", async (route) => {
    if (route.request().method() === "POST") {
      const request = route.request().postDataJSON() as { scenario: { actionHistory: Action[] } };
      solverSubmissions.push(request.scenario.actionHistory);
      await route.fulfill({ status: 202, contentType: "application/json", json: { jobId: "workbench-a4", status: "queued" } });
      return;
    }
    await route.fulfill({ contentType: "application/json", json: {
      jobId: "workbench-a4",
      status: "solved",
      result: {
        metadata: { solver: "fixture", version: "1", street: "flop", exploitabilityChips: 0, targetExploitabilityChips: 0, solveTimeMs: 1, maxIterations: 1, memoryUsageGb: 0, memoryUsageCompressedGb: 0, compressed: false },
        root: { actions: ["Check", "Bet(250)"], player: 0, hands: [{ combo: "QhJc", weight: 1, equity: 0.5, ev: 0, strategy: { Check: 0.05, "Bet(250)": 0.95 } }] },
      },
    } });
  });
  await page.route("**/v1/hand-reviews", async (route) => {
    const request = route.request().postDataJSON() as { scenario: { actionHistory: Action[] }; solverJobs?: Record<string, string> };
    reviewRequests.push({ solverJobs: request.solverJobs });
    await route.fulfill({ contentType: "application/json", json: reviewFixture(request.scenario.actionHistory) });
  });

  await page.goto("/");
  await page.getByLabel("导入 JSON").setInputFiles({
    name: "workbench-checkdown.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(FLOP_CHECKDOWN_START)),
  });
  await expect(page.getByText("规则校验通过，当前状态已更新。")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("4 events")).toBeVisible();

  // Complete the loaded hand with real ActionBar transitions. Deal events
  // alter rule state but never become review decisions.
  async function appendCheck(eventCount: number) {
    await page.getByRole("button", { name: "Check", exact: true }).click();
    await expect(page.getByText(`${eventCount} events`)).toBeVisible();
  }

  await appendCheck(5);
  await page.getByRole("button", { name: "Deal turn" }).click();
  await appendCheck(7);
  await appendCheck(8);
  await page.getByRole("button", { name: "Deal river" }).click();
  await appendCheck(10);
  await appendCheck(11);
  await expect(page.getByLabel("状态事件 deal_turn")).toBeVisible();
  await expect(page.getByLabel("状态事件 deal_river")).toBeVisible();

  // A historical preflop action uses its action-before projection and exposes
  // the disabled per-node gate rather than submitting an invalid solve.
  await page.locator("#action-timeline-a1").click();
  await page.getByRole("tab", { name: "Solver" }).click();
  const submit = page.getByRole("button", { name: "提交 Solver 求解（独立容器）" });
  await expect(submit).toBeDisabled();
  await expect(page.getByLabel("solver 提交条件")).toContainText("✗ 翻后节点（flop / turn / river）");

  const projectedState = page.waitForRequest((request) => {
    if (!request.url().endsWith("/v1/scenarios/state") || request.method() !== "POST") return false;
    const scenario = request.postDataJSON() as { actionHistory: Action[] };
    return scenario.actionHistory?.length === 3;
  });
  await page.locator("#action-timeline-a4").click();
  const projection = await projectedState;
  const projectionScenario = projection.postDataJSON() as { actionHistory: Action[]; board: string[] };
  expect(projectionScenario.actionHistory.map((action) => action.actionId)).toEqual(["a1", "a2", "a3"]);
  expect(projectionScenario.board).toEqual(["2c", "7d", "Jh"]);
  await expect(page.getByLabel("行动游标")).toHaveText("行动后 #4 · 决策前 #3");
  await expect(submit).toBeEnabled();

  await expect(page.getByLabel("belief view")).toContainText("fixture / manual policy");
  expect(beliefRequests).toContainEqual({ seatId: 1, afterSequence: 4 });

  await submit.click();
  await expect(page.locator("section.solve-panel")).toContainText("queued");
  await expect(page.locator("section.solve-panel")).toContainText("solved", { timeout: 8_000 });
  expect(solverSubmissions).toHaveLength(1);
  expect(solverSubmissions[0].map((action) => action.actionId)).toEqual(["a1", "a2", "a3"]);

  // The solved a4 job must not leak to another actionId, and must return when
  // the original action is selected again.
  await page.locator("#action-timeline-a2").click();
  await expect(page.locator("section.solve-panel")).toContainText("idle");
  await page.locator("#action-timeline-a4").click();
  await expect(page.locator("section.solve-panel")).toContainText("solved");

  await page.getByRole("button", { name: "生成整手复盘" }).first().click();
  await expect(page.getByLabel("整手总结")).toContainText("整手按真实行动顺序复盘");
  const cards = page.locator('[aria-label^="决策卡 "]');
  await expect(cards).toHaveCount(8);
  await expect(page.getByLabel("决策卡 a4")).toContainText("可接受混频");
  await expect(page.getByLabel("决策卡 a4")).toContainText("实际行动频率 5%");
  await expect(page.getByLabel("决策卡 a1")).toContainText("无 Solver 结论");
  await expect(page.getByLabel("决策卡 a1")).toContainText("原则性教学");
  expect(reviewRequests).toEqual([{ solverJobs: { a4: "workbench-a4" } }]);

  await page.getByRole("button", { name: /翻牌圈 Check 值得优先复盘/ }).click();
  await expect(page.locator("#action-timeline-a4")).toBeFocused();

  await page.getByLabel("board-4").fill("4h");
  await expect(page.getByRole("region", { name: "整手复盘" })).toContainText("场景已变化；以下整手复盘已过期，请重新生成。");
});
