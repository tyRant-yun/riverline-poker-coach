import { expect, test } from "@playwright/test";

test("MVP shell opens the table with only product navigation and an honest offline state", async ({ page }) => {
  await page.route("**/health", (route) => route.abort());
  await page.goto("/");

  await expect(page.getByRole("button", { name: "牌桌", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "复盘" })).toBeVisible();
  await expect(page.getByTestId("continuous-table-page")).toBeVisible();
  await expect(page.getByTestId("health-status")).toContainText("服务状态：离线");
  await expect(page.getByText("启动后端后重试：本地 SQLite 数据保存在本机。")).toBeVisible();
  await expect(page.getByText("Hand Lab")).toHaveCount(0);
  await expect(page.getByText("Solver", { exact: true })).toHaveCount(0);
});
