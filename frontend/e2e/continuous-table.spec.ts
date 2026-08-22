import { expect, test } from "@playwright/test";

const sessionId = "table-smoke";

function tableState(overrides: Record<string, unknown> = {}) {
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
      { action: "call", amountSemantics: "cost", minAmount: 100, maxAmount: 100 },
      { action: "fold", amountSemantics: "none" },
    ],
    actionHistory: [{ sequence: 8, street: "flop", actorSeat: 1, action: "bet", amount: 100 }],
    handComplete: false,
    fingerprint: "decision-smoke",
    result: null,
    botDecisionProvenance: [
      { sequence: 8, actorSeat: 1, profileId: "aggressive", provider: "lightweight-blueprint", degraded: false, fallbackReason: null },
    ],
    ...overrides,
  };
}

test("continuous table create, legal action, completion, next hand, reconnect, and error state", async ({ page }) => {
  let current = tableState();
  let actionError = true;
  const calls: string[] = [];

  await page.route("**/v1/tables**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push(`${request.method()} ${url.pathname}`);
    if (request.method() === "POST" && url.pathname === "/v1/tables") {
      const body = request.postDataJSON();
      expect(body.botProfile).toBe("aggressive");
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, idempotent: false, table: current }) });
      return;
    }
    if (request.method() === "GET" && url.pathname === `/v1/tables/${sessionId}`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, table: current }) });
      return;
    }
    if (request.method() === "GET" && url.pathname === `/v1/tables/${sessionId}/insights`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, insights: { available: true, seatBeliefs: [{ seatId: 1, available: true, rangeWidthPct: 28.5, rangeWidthCombos: 214, evidenceGrade: "B", coverageStatus: "covered", policyFingerprint: "sha256:0123456789abcdef", matrix169: { AA: { probabilityMass: "0.08", comboCount: 6 } } }], stats: { available: false, bySeat: [] } } }) });
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/actions`) {
      if (actionError) {
        actionError = false;
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, error: { code: "revision_conflict", message: "table revision is stale" } }) });
      } else {
        current = tableState({ handComplete: true, currentActor: null, revision: 19 });
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, table: current }) });
      }
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/hands`) {
      current = tableState({ handId: `${sessionId}:hand:2`, handSequence: 2, buttonSeat: 1, revision: 20, handComplete: false, currentActor: 0 });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, table: current }) });
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/reconciliation`) {
      const body = request.postDataJSON();
      expect(body.decisionFingerprint).toBe(current.fingerprint);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, reconciliation: { status: "ready", decision: { fingerprint: current.fingerprint, handId: current.handId, sequence: 8, street: "flop" }, ruleBaseline: { role: "rule_baseline", status: "ready", action: { action: "call", amountSemantics: "cost", amountChips: 100, potPct: "22.2" }, provenance: {}, limitations: [] }, simulationEstimate: { role: "simulation_estimate", status: "ready", action: { action: "call", amountSemantics: "cost", amountChips: 100, potPct: "22.2" }, provenance: {}, limitations: [] }, agreement: { kind: "exact_action", reasonCodes: [], confidenceInterval: { status: "available", overlap: false }, sizingRobustness: "robust" } } }) });
      return;
    }
    if (request.method() === "POST" && url.pathname === `/v1/tables/${sessionId}/theory-recommendation`) {
      const body = request.postDataJSON();
      expect(body.decisionFingerprint).toBe(current.fingerprint);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, recommendation: { status: "ready", available: true, decision: { fingerprint: current.fingerprint, handId: current.handId, sequence: 8, street: "flop", observerSeat: 0 }, evidence: { sourceKind: "policy_artifact", evidenceGrade: "B", version: "artifact/v1", policyFingerprint: "sha256:0123456789abcdef", provenance: "first-party", coverage: { status: "covered", players: 6, street: "preflop" } }, recommendedAction: { action: "call", amountSemantics: "cost", amount: 100, frequency: 0.7 }, actionFrequencies: [{ action: "call", amountSemantics: "cost", amount: 100, frequency: 0.7 }, { action: "fold", amountSemantics: "none", frequency: 0.3 }], sameOracleEvLoss: { unavailableReason: "source_has_no_same_oracle_identity" }, explanation: { formulaVersion: "formula/v1", potOdds: "0.2", assumptions: [], limitations: [] }, degradation: [] } }) });
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  await page.getByRole("button", { name: "牌桌", exact: true }).click();
  await page.getByTestId("bot-profile").selectOption("aggressive");
  await page.getByTestId("create-continuous-table").click();
  await expect(page.getByTestId("table-workspace-v2")).toBeVisible();
  await expect(page.getByLabel("底池与公共牌安全区")).toContainText("450");
  await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
  await expect(page.getByLabel("Q♥")).toBeVisible();
  await expect(page.getByLabel("Q♠")).toBeVisible();
  expect(await page.getByLabel("card back").count()).toBe(0);
  await expect(page.getByTestId("bot-provenance")).toContainText("aggressive");
  await expect(page.getByLabel("Decision Summary")).toContainText("策略真相来源");
  await expect(page.getByLabel("Theory 推荐")).toContainText("混合频率");
  for (const viewport of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 1024, height: 768 }]) {
    await page.setViewportSize(viewport);
    await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
    await expect(page.getByLabel("Theory 推荐")).toContainText("B 级");
    await expect(page.getByLabel("Theory 推荐")).toContainText("混合频率");
    await expect(page.getByLabel("Range Belief")).toContainText("B 级 · 同源 PolicyArtifact");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }

  await page.getByTestId("hero-action-call").click();
  await expect(page.locator("p.warning[role='alert']")).toContainText("table revision is stale");
  await page.getByTestId("hero-action-call").click();
  await expect(page.getByTestId("next-hand")).toBeVisible();
  await expect(page.getByTestId("training-feedback")).toBeVisible();
  for (const viewport of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 1024, height: 768 }]) {
    await page.setViewportSize(viewport);
    await expect(page.getByLabel("Hero 操作区")).toBeVisible();
    await expect(page.getByTestId("training-feedback")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
  await page.getByTestId("next-hand").click();
  await expect(page.getByTestId("continuous-table-status")).toContainText("第 2 手");

  await page.reload();
  await page.getByRole("button", { name: "牌桌", exact: true }).click();
  await expect(page.getByTestId("continuous-table-status")).toContainText("第 2 手");
  expect(calls).toContain(`GET /v1/tables/${sessionId}`);
  expect(calls).toContain("POST /v1/tables");
  expect(calls).toContain(`POST /v1/tables/${sessionId}/actions`);
  expect(calls).toContain(`POST /v1/tables/${sessionId}/hands`);
  expect(calls).toContain(`POST /v1/tables/${sessionId}/reconciliation`);
  expect(calls).toContain(`POST /v1/tables/${sessionId}/theory-recommendation`);
});
