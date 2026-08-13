import { expect, test } from "@playwright/test";

const sessionId = "mvp-shell";

function table() {
  return {
    sessionId, handId: `${sessionId}:hand:1`, handSequence: 1, buttonSeat: 0, heroSeat: 0, revision: 4,
    board: [], pot: 150, street: "preflop",
    seats: Array.from({ length: 6 }, (_, seatId) => ({ seatId, stack: 10_000, status: "active", committed: seatId === 1 ? 100 : 0 })),
    heroHoleCards: ["As", "Kh"], currentActor: 0,
    heroLegalActions: [{ action: "fold", amountSemantics: "none" }, { action: "call", amountSemantics: "cost", minAmount: 100, maxAmount: 100 }],
    actionHistory: [{ sequence: 1, street: "preflop", actorSeat: 1, action: "blind", amount: 100 }],
    handComplete: false, result: null,
    botDecisionProvenance: [{ sequence: 1, actorSeat: 1, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null }],
  };
}

test("MVP shell reports local health and creates an honest continuous table experience", async ({ page }) => {
  await page.route("**/health", route => route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "ok" }) }));
  await page.route("**/v1/tables**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path === "/v1/tables") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, table: table() }) });
      return;
    }
    if (path.endsWith("/insights")) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, insights: {
        available: true,
        advisor: { available: true, result: { recommendedAction: { action: "call", reason: "price" }, source: "deterministic_formula", version: "v1" } },
        seatBeliefs: [{ seatId: 1, available: true, currentMass: "1", provenance: { provider: "heuristic", version: "v1", trustLevel: "low" } }],
        stats: { available: true, bySeat: [{ seatId: 0, vpip: 0, pfr: 0, threeBet: 0 }] },
      } }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, available: false, reviews: [] }) });
  });

  await page.goto("/");
  await expect(page.getByTestId("health-status")).toContainText("服务状态：在线");
  await page.getByTestId("create-continuous-table").click();
  await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
  await expect(page.getByText("A♠")).toBeVisible();
  expect(await page.locator(".seat:not(.seat--hero) .playing-card--back").count()).toBe(10);
  for (const heading of ["Advisor", "Range", "Stats", "Solver"]) await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  await expect(page.getByTestId("table-insights")).toContainText("deterministic_formula");
  await expect(page.getByTestId("table-insights")).toContainText("独立座位边际；不含对手私牌");
  await expect(page.getByTestId("table-insights")).toContainText("当前未连接/不可用");
});
