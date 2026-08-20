import { expect, test, type Page } from "@playwright/test";

async function playHeroDecision(page: Page) {
  const actions = page.getByTestId("hero-legal-actions");
  await expect(actions).toBeVisible();
  await expect(actions.getByRole("button").first()).toBeEnabled({ timeout: 15_000 });
  await expect(page.getByLabel("Advisor 摘要")).toContainText(/建议：|暂不可用/);
  await expect(page.getByLabel("Range Belief")).toContainText("不含对手私牌");
  await expect(page.getByLabel("Solver 结果")).toContainText(/模拟估计|当前不是 Hero 决策/);

  const actionResponse = page.waitForResponse((response) => response.url().includes("/actions") && response.request().method() === "POST");
  const preferred = page.getByTestId("hero-action-check").or(page.getByTestId("hero-action-call"));
  if (await preferred.count()) await preferred.first().click();
  else await page.getByTestId("hero-legal-actions").getByRole("button").first().click();
  await actionResponse;
}

test("R7 golden journey: two run-local hands retain live insights without private-card or stale-state leaks", async ({ page }) => {
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem("r7-golden-clean")) {
      window.localStorage.clear();
      window.sessionStorage.setItem("r7-golden-clean", "1");
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("health-status")).toContainText("服务状态：在线");
  await page.getByTestId("create-continuous-table").click();
  await expect(page.getByLabel("六人德州扑克牌桌").locator(".tv2-seat")).toHaveCount(6);
  await page.getByLabel("Bot 播放速度").selectOption("instant");

  const firstCards = await page.getByLabel("Hero 手牌").locator("i").allTextContents();
  let completedHands = 0;
  let decisionChecks = 0;
  for (let turns = 0; turns < 24 && completedHands < 2; turns += 1) {
    if (await page.getByTestId("next-hand").count()) {
      const priorHand = await page.getByTestId("continuous-table-status").textContent();
      await page.getByTestId("next-hand").click();
      await expect(page.getByTestId("continuous-table-status")).not.toHaveText(priorHand ?? "");
      await expect(page.getByLabel("Range Belief")).toContainText(/当前暂无|座位/);
      completedHands += 1;
      continue;
    }
    await playHeroDecision(page);
    decisionChecks += 1;
  }

  expect(decisionChecks).toBeGreaterThan(0);
  expect(completedHands).toBeGreaterThanOrEqual(2);
  // A hand can end by folds, so the second completion is naturally attempted
  // rather than assumed. The next active hand must still be fresh and safe.
  if (completedHands >= 2) {
    const currentCards = await page.getByLabel("Hero 手牌").locator("i").allTextContents();
    expect(currentCards.join(" ")).not.toBe(firstCards.join(" "));
  }
  expect(await page.getByLabel("六人德州扑克牌桌").locator("[aria-label='Hero 手牌']").count()).toBe(1);
  await page.reload();
  await page.getByRole("button", { name: "牌桌", exact: true }).click();
  await expect(page.getByTestId("continuous-table-status")).toBeVisible();
});
