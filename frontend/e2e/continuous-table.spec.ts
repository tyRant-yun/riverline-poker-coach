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

  await page.getByTestId("hero-action-call").click();
  await expect(page.locator("p.warning[role='alert']")).toContainText("table revision is stale");
  await page.getByTestId("hero-action-call").click();
  await expect(page.getByTestId("next-hand")).toBeVisible();
  await page.getByTestId("next-hand").click();
  await expect(page.getByTestId("continuous-table-status")).toContainText("第 2 手");

  await page.reload();
  await page.getByRole("button", { name: "牌桌", exact: true }).click();
  await expect(page.getByTestId("continuous-table-status")).toContainText("第 2 手");
  expect(calls).toContain(`GET /v1/tables/${sessionId}`);
  expect(calls).toContain("POST /v1/tables");
  expect(calls).toContain(`POST /v1/tables/${sessionId}/actions`);
  expect(calls).toContain(`POST /v1/tables/${sessionId}/hands`);
});
