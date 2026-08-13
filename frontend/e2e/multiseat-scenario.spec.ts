import { expect, test } from "@playwright/test";

const sessionId = "six-seat-actions";

function table(revision: number, historyCount: number, handComplete = false) {
  return {
    sessionId, handId: `${sessionId}:hand:1`, handSequence: 1, buttonSeat: 2, heroSeat: 4, revision,
    board: ["7c", "8d", "Th"], pot: 600, street: "flop",
    seats: Array.from({ length: 6 }, (_, seatId) => ({ seatId, stack: 10_000 - seatId * 100, status: "active", committed: seatId === 3 ? 200 : 0 })),
    heroHoleCards: ["Qs", "Jd"], currentActor: handComplete ? null : 4,
    heroLegalActions: handComplete ? [] : [{ action: "fold", amountSemantics: "none" }, { action: "call", amountSemantics: "cost", minAmount: 200, maxAmount: 200 }],
    actionHistory: Array.from({ length: historyCount }, (_, index) => ({ sequence: index + 1, street: "flop", actorSeat: index % 6, action: index === 0 ? "bet" : "call", amount: 200 })),
    handComplete, result: handComplete ? { winnerSeats: [1], payouts: { "1": 600 } } : null,
    botDecisionProvenance: [{ sequence: 1, actorSeat: 3, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null }],
  };
}

test("six-seat continuous table keeps all seats and advances through multiple hero actions", async ({ page }) => {
  let actionCount = 0;
  await page.route("**/health", route => route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "ok" }) }));
  await page.route("**/v1/tables**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path === "/v1/tables") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, table: table(8, 1) }) });
      return;
    }
    if (request.method() === "POST" && path.endsWith("/actions")) {
      const body = request.postDataJSON();
      expect(body.expectedRevision).toBe(actionCount === 0 ? 8 : 9);
      expect(body.action).toBe(actionCount === 0 ? "call" : "fold");
      actionCount += 1;
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, table: table(8 + actionCount, 1 + actionCount, actionCount === 2) }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, insights: { available: false, unavailableReason: "fixture" } }) });
  });

  await page.goto("/");
  await page.getByTestId("create-continuous-table").click();
  await expect(page.locator(".seat")).toHaveCount(6);
  await expect(page.locator(".seat[data-seat-id='4']")).toContainText("HERO");
  await expect(page.getByTestId("continuous-table-status")).toContainText("Seat 4 行动");
  await page.getByTestId("hero-action-call").click();
  await expect(page.getByTestId("table-action-history").locator("li")).toHaveCount(2);
  await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
  await page.getByTestId("hero-action-fold").click();
  await expect(page.getByTestId("next-hand")).toBeVisible();
  expect(actionCount).toBe(2);
});
