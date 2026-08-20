import { expect, test, type Page } from "@playwright/test";

const sessionId = "r8-release-proxy";

function activeTable(overrides: Record<string, unknown> = {}) {
  return {
    sessionId,
    handId: `${sessionId}:hand:1`,
    handSequence: 1,
    buttonSeat: 0,
    heroSeat: 0,
    revision: 18,
    board: ["As", "Kd", "7c"],
    pot: 450,
    street: "flop",
    seats: Array.from({ length: 6 }, (_, seatId) => ({
      seatId,
      stack: seatId === 0 ? 9_500 : 10_000,
      status: "active",
      committed: seatId === 1 ? 100 : 0,
    })),
    heroHoleCards: ["Qh", "Qs"],
    currentActor: 0,
    heroLegalActions: [
      { action: "check", amountSemantics: "none" },
      { action: "fold", amountSemantics: "none" },
    ],
    actionHistory: [
      { sequence: 8, street: "flop", actorSeat: 1, action: "bet", amount: 100 },
    ],
    handComplete: false,
    fingerprint: "r8-decision-1",
    result: null,
    botDecisionProvenance: [
      { sequence: 8, actorSeat: 1, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
    ],
    ...overrides,
  };
}

function insights(decisionFingerprint: string) {
  return {
    schemaVersion: 1,
    insights: {
      available: true,
      advisor: {
        available: true,
        status: "ready",
        result: {
          status: "ready",
          recommendedAction: { action: "check", amountSemantics: "none", reason: "free_action" },
          source: "deterministic_formula",
          version: "formula-advisor/v1",
          confidence: "deterministic",
          explanationKey: "free_action",
          limitations: [],
          decision: { fingerprint: decisionFingerprint, handId: `${sessionId}:hand:1`, sequence: 8, street: "flop" },
        },
        provenance: { source: "deterministic_formula", version: "formula-advisor/v1", degraded: false },
      },
      seatBeliefs: [{
        seatId: 1,
        available: true,
        rangeWidthPct: 22.4,
        rangeWidthCombos: 298,
        confidence: "coarse",
        confidenceScore: 0.72,
        source: "heuristic_likelihood_v1",
        version: "range-belief/v2",
        dataVersion: "r8-release",
        approximate: false,
        changeReason: "public_action_update",
        limitations: ["public-events-only"],
        decision: { handId: `${sessionId}:hand:1`, afterSequence: 8 },
        matrix169: {
          AA: { probabilityMass: "0.08", comboCount: 6 },
          AKs: { probabilityMass: "0.06", comboCount: 4 },
          AKo: { probabilityMass: "0.04", comboCount: 12 },
        },
        topClasses: [
          { hand: "AA", probabilityMass: "0.08" },
          { hand: "AKs", probabilityMass: "0.06" },
          { hand: "AKo", probabilityMass: "0.04" },
        ],
      }],
      stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] },
    },
  };
}

function solver(decisionFingerprint: string) {
  const candidate = (action: string, amount: number | null, ev: string, potPercentage?: string) => ({
    action,
    amountSemantics: amount == null ? "none" : "raise_to",
    amount,
    approximateEvChips: ev,
    ...(potPercentage ? { potPercentage } : {}),
    deltaEvConfidenceInterval95: { lower: "-1.2", upper: "1.4", confidence: "95%" },
    uncertaintyStatus: "available",
    recommendationTier: ev === "12.5" ? "robust" : "close",
    sizingClass: amount != null && amount > 600 ? "overbet" : amount == null ? "non_sizing" : "standard",
  });
  return {
    schemaVersion: 1,
    solver: {
      status: "ready",
      recommendedAction: { action: "raise", amountSemantics: "raise_to", amount: 300, approximateEvChips: "12.5" },
      candidates: [
        candidate("raise", 300, "12.5", "66.7"),
        candidate("check", null, "11.9"),
        candidate("raise", 225, "11.5", "50.0"),
        candidate("raise", 450, "10.8", "100.0"),
        candidate("raise", 700, "8.2", "155.6"),
      ],
      equity: "0.437",
      iterations: 80,
      sampleCount: 80,
      effectiveSampleSize: "72.0",
      elapsedMicroseconds: 18_500,
      budgetMs: 50,
      hardBudgetMs: 75,
      budgetTier: "standard",
      source: "monte_carlo_uniform_opponents",
      version: "fast-ev-solver/v1",
      modelVersion: "solver-l1.5",
      confidence: "coarse",
      decision: { fingerprint: decisionFingerprint, handId: `${sessionId}:hand:1`, sequence: 8, street: "flop" },
      sizingRobustness: "robust",
      recommendationReasonCodes: ["solver_sizing_robust"],
      limitations: ["模拟估计，不是 GTO"],
    },
  };
}

function reconciliation(decisionFingerprint: string) {
  return {
    schemaVersion: 1,
    reconciliation: {
      status: "ready",
      decision: { fingerprint: decisionFingerprint, handId: `${sessionId}:hand:1`, sequence: 8, street: "flop" },
      ruleBaseline: {
        role: "rule_baseline",
        status: "ready",
        action: { action: "check", amountSemantics: "none" },
        provenance: { source: "deterministic_formula" },
        limitations: [],
      },
      simulationEstimate: {
        role: "simulation_estimate",
        status: "ready",
        action: { action: "raise", amountSemantics: "raise_to", amountChips: 300, potPct: "66.7" },
        provenance: { source: "monte_carlo_uniform_opponents" },
        limitations: ["not_gto"],
      },
      agreement: {
        kind: "different_action",
        reasonCodes: ["model_limitations"],
        confidenceInterval: { status: "available", overlap: false },
        sizingRobustness: "robust",
      },
    },
  };
}

async function installControlledTable(page: Page) {
  let current = activeTable();
  let actionCount = 0;

  await page.route("**/v1/tables**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

    if (request.method() === "POST" && url.pathname === "/v1/tables") {
      await json({ schemaVersion: 1, idempotent: false, table: current });
      return;
    }
    if (request.method() === "GET" && url.pathname === `/v1/tables/${sessionId}`) {
      await json({ schemaVersion: 1, table: current });
      return;
    }
    if (request.method() === "GET" && url.pathname === `/v1/tables/${sessionId}/insights`) {
      await json(insights(current.fingerprint));
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/solver`) {
      await json(solver(current.fingerprint));
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/reconciliation`) {
      await json(reconciliation(current.fingerprint));
      return;
    }
    if (request.method() === "GET" && url.pathname.startsWith(`/v1/tables/${sessionId}/reviews`)) {
      await json({ schemaVersion: 1, available: current.handComplete, review: current.handComplete ? { handId: current.handId, heroSeat: 0, completionSequence: 11, heroDecisions: [{ actionSequence: 9, street: "flop", action: "check" }], references: {} } : null });
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/actions`) {
      actionCount += 1;
      if (actionCount === 1) {
        current = activeTable({
          revision: 19,
          fingerprint: "r8-decision-2",
          actionHistory: [
            { sequence: 8, street: "flop", actorSeat: 1, action: "bet", amount: 100 },
            { sequence: 9, street: "flop", actorSeat: 2, action: "call", amount: 100 },
          ],
          botDecisionProvenance: [
            { sequence: 8, actorSeat: 1, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
            { sequence: 9, actorSeat: 2, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
          ],
        });
      } else {
        current = activeTable({
          revision: 20,
          currentActor: null,
          heroLegalActions: [],
          handComplete: true,
          fingerprint: "r8-showdown-1",
          seats: Array.from({ length: 6 }, (_, seatId) => ({
            seatId,
            stack: seatId === 0 ? 10_250 : 9_950,
            status: "active",
            committed: 0,
            ...(seatId === 1 ? { revealedHoleCards: ["Ah", "Kh"] } : {}),
          })),
          actionHistory: [
            { sequence: 8, street: "flop", actorSeat: 1, action: "bet", amount: 100 },
            { sequence: 9, street: "flop", actorSeat: 2, action: "call", amount: 100 },
            { sequence: 11, street: "river", actorSeat: 1, action: "call", amount: 250 },
          ],
          botDecisionProvenance: [
            { sequence: 8, actorSeat: 1, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
            { sequence: 9, actorSeat: 2, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
            { sequence: 11, actorSeat: 1, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
          ],
          result: { winnerSeats: [0], payouts: { "0": 800 } },
        });
      }
      await json({ schemaVersion: 1, table: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/hands`) {
      current = activeTable({
        handId: `${sessionId}:hand:2`,
        handSequence: 2,
        buttonSeat: 1,
        revision: 21,
        board: [],
        pot: 150,
        street: "preflop",
        heroHoleCards: ["2c", "3d"],
        fingerprint: "r8-decision-hand-2",
        actionHistory: [],
        botDecisionProvenance: [],
      });
      await json({ schemaVersion: 1, table: current });
      return;
    }
    await route.continue();
  });
}

async function measureProxy(label: string, operation: () => Promise<void>) {
  const started = Date.now();
  await operation();
  const elapsedMs = Date.now() - started;
  console.log(`[R8 automated interaction proxy] ${label}=${elapsedMs}ms`);
  expect(elapsedMs, `${label} must complete within the controlled 5-second proxy threshold`).toBeLessThanOrEqual(5_000);
  return elapsedMs;
}

test("R8 controlled product journey exposes decision evidence, readable Bot dwell, terminal reveal, next hand, and reconnect", async ({ page }) => {
  await installControlledTable(page);
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem("r8-release-clean")) {
      window.localStorage.clear();
      window.sessionStorage.setItem("r8-release-clean", "1");
    }
  });
  await page.goto("/");
  await page.getByTestId("create-continuous-table").click();

  await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
  await expect(page.getByLabel("Decision Summary")).toContainText("规则基线");
  await expect(page.getByLabel("Decision Summary")).toContainText("模拟估计");
  await expect(page.getByLabel("Solver Action Ladder").locator("article")).toHaveCount(3);
  await expect(page.getByLabel("Range Belief")).toContainText("范围宽度 22.4%");
  expect(await page.getByLabel("六人德州扑克牌桌").locator(".tv2-holecards").count()).toBe(1);
  expect(await page.getByLabel("A♥").count()).toBe(0);

  for (const [width, height] of [[1366, 768], [1440, 900], [1920, 1080], [1280, 720]] as const) {
    await page.setViewportSize({ width, height });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${width}x${height} must not horizontally scroll`).toBeTruthy();
  }

  const proxyTimings = {
    rangeExplorerMs: await measureProxy("locate/open Range Explorer", async () => {
      const range = page.getByLabel("Range Belief");
      await expect(range).toContainText("主要牌类");
      await range.getByRole("button", { name: "展开矩阵" }).click();
      await expect(page.getByRole("dialog", { name: "Range Explorer" })).toBeVisible();
    }),
    solverPreferredAndAllSizesMs: 0,
    reconciliationReasonMs: 0,
  };
  await page.getByRole("button", { name: "关闭矩阵" }).click();
  proxyTimings.solverPreferredAndAllSizesMs = await measureProxy("locate Solver preferred candidate/expand all sizes", async () => {
    const ladder = page.getByLabel("Solver Action Ladder");
    await expect(ladder.locator("article").first()).toContainText("加注 · 66.7% pot · 300");
    await page.getByRole("button", { name: "全部尺度（5）" }).click();
    await expect(ladder.locator("article")).toHaveCount(5);
  });
  proxyTimings.reconciliationReasonMs = await measureProxy("locate Advisor/Solver agreement or disagreement reason", async () => {
    const summary = page.getByLabel("Decision Summary");
    await expect(summary).toContainText("Advisor：过牌");
    await expect(summary).toContainText("Solver：加注 · 66.7% pot · 300");
    await expect(summary).toContainText("存在分歧 · 模型限制");
  });
  test.info().annotations.push({ type: "automated-interaction-proxy", description: JSON.stringify(proxyTimings) });

  await page.evaluate(() => {
    const observed = { shownAt: null as number | null, hiddenAt: null as number | null };
    (window as typeof window & { __r8Dwell?: typeof observed }).__r8Dwell = observed;
    const observer = new MutationObserver(() => {
      const visible = Boolean(document.querySelector('[data-testid="bot-action-bubble"]'));
      if (visible && observed.shownAt == null) observed.shownAt = performance.now();
      if (!visible && observed.shownAt != null && observed.hiddenAt == null) {
        observed.hiddenAt = performance.now();
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  await page.getByTestId("hero-action-check").click();
  await expect(page.getByTestId("bot-thinking")).toContainText("Bot 3 思考中");
  await expect(page.getByTestId("bot-action-bubble")).toContainText("跟注 100");
  await expect(page.getByTestId("bot-action-bubble")).toHaveCount(0, { timeout: 2_000 });
  const dwell = await page.evaluate(() => (window as typeof window & { __r8Dwell?: { shownAt: number | null; hiddenAt: number | null } }).__r8Dwell);
  expect(dwell?.shownAt).not.toBeNull();
  expect(dwell?.hiddenAt).not.toBeNull();
  expect(dwell!.hiddenAt! - dwell!.shownAt!, "Bot action pill must retain a perceptible dwell").toBeGreaterThanOrEqual(700);
  await expect(page.getByTestId("hero-action-check")).toBeEnabled({ timeout: 200 });

  await page.getByTestId("hero-action-check").click();
  await expect(page.getByTestId("bot-action-bubble")).toContainText("跟注 250");
  await expect(page.getByTestId("next-hand")).toBeVisible({ timeout: 2_000 });
  await expect(page.getByLabel("A♥")).toBeVisible();
  await expect(page.getByLabel("K♥")).toBeVisible();
  await expect(page.getByTestId("table-review-status")).toContainText("复盘可用");

  await page.getByTestId("next-hand").click();
  await expect(page.getByTestId("continuous-table-status")).toContainText("第 2 手");
  await expect(page.getByLabel("2♣")).toBeVisible();
  expect(await page.getByLabel("A♥").count()).toBe(0);
  expect(await page.getByLabel("六人德州扑克牌桌").locator(".tv2-holecards").count()).toBe(1);

  await page.reload();
  await page.getByRole("button", { name: "牌桌", exact: true }).click();
  await expect(page.getByTestId("continuous-table-status")).toContainText("第 2 手");
  expect(await page.getByLabel("A♥").count()).toBe(0);
  expect(await page.getByLabel("六人德州扑克牌桌").locator(".tv2-holecards").count()).toBe(1);
});
