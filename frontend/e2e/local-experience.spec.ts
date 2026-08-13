import { expect, test } from "@playwright/test";

test("default local service is healthy and creates a six-seat table with honest insight sections", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("health-status")).toContainText("服务状态：在线");
  await page.getByTestId("create-continuous-table").click();
  await expect(page.getByTestId("hero-legal-actions")).toBeVisible();
  await expect(page.locator(".seat")).toHaveCount(6);
  await expect(page.locator(".seat--hero .playing-card")).toHaveCount(2);
  await expect(page.getByTestId("table-insights")).toContainText("Advisor");
  await expect(page.getByTestId("table-insights")).toContainText("Range");
  await expect(page.getByTestId("table-insights")).toContainText("Stats");
  await expect(page.getByTestId("table-insights")).toContainText("Solver");
  await expect(page.getByTestId("table-insights")).toContainText("公式/启发式建议，不是 Solver 或 GTO 结果");
  await expect(page.getByTestId("table-insights")).toContainText("独立座位边际；不含对手私牌");
  await expect(page.getByTestId("table-insights")).toContainText("当前未连接/不可用");
});
