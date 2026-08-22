import { expect, test } from "@playwright/test";

test("default local service is healthy and creates a six-seat table with honest insight sections", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("health-status")).toContainText("服务状态：在线");
  await page.getByTestId("create-continuous-table").click();
  await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
  await expect(page.getByLabel("六人德州扑克牌桌").locator(".tv2-seat")).toHaveCount(6);
  await expect(page.getByLabel("Hero 手牌").locator("i")).toHaveCount(2);
  await expect(page.getByLabel("Advisor 摘要")).toContainText("建议：");
  await expect(page.getByLabel("Decision Summary")).toContainText("策略真相来源");
  await expect(page.getByLabel("Theory 推荐")).toContainText("B 级 · policy_artifact");
  await expect(page.getByLabel("Theory 推荐")).toContainText("covered");
  await expect(page.getByLabel("Solver 结果")).toContainText("模拟估计");
  await expect(page.getByLabel("Solver 结果")).toContainText("不是 GTO");
  await expect(page.getByLabel("Range Belief")).toContainText("座位独立边际估计，不含对手私牌");
  await expect(page.getByLabel("Range Belief")).toContainText("B 级 · 同源 PolicyArtifact");
});
