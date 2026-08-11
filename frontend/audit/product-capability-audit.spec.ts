import { expect, test } from "@playwright/test";

test.describe("real user capability audit", () => {
  test("records the current HU-only editor surface and ActionBar continuity", async ({ page }) => {
    await page.goto("/");

    // Positive controls are driven on the real page; this does not use the
    // Range/Review/Solver mocks from the ordinary E2E suite.
    await expect(page.getByLabel("Hero 起始筹码")).toBeVisible();
    await expect(page.getByLabel("Villain 起始筹码")).toBeVisible();
    await expect(page.getByLabel("导入 JSON")).toBeAttached();
    await expect(page.getByRole("button", { name: "导出 JSON" })).toBeVisible();
    await page.getByRole("button", { name: /Raise to 200/ }).click();
    await expect(page.getByText("1 events")).toBeVisible({ timeout: 10_000 });
    await page.getByLabel("撤销").click();
    await expect(page.getByText("0 events")).toBeVisible({ timeout: 10_000 });
    await page.getByLabel("重做").click();
    await expect(page.getByText("1 events")).toBeVisible({ timeout: 10_000 });

    // Current negative inventory: this is a passing measurement so the two
    // red gate tests below remain the release signal for the missing journey.
    await expect(page.getByRole("combobox", { name: "桌型" })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "按钮位" })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "Hero 座位" })).toHaveCount(0);
    await expect(page.getByLabel(/Seat 2.*筹码/)).toHaveCount(0);
    await expect(page.getByLabel(/Seat 2.*范围/)).toHaveCount(0);
  });

  test("a user can construct an 8-max table and control positions from the UI", async ({ page }) => {
    await page.goto("/");

    const tableSize = page.getByRole("combobox", { name: "桌型" });
    await expect(tableSize).toBeVisible({ timeout: 3_000 });
    await tableSize.selectOption("8");

    await expect(page.getByRole("combobox", { name: "按钮位" })).toBeVisible();
    await expect(page.getByLabel(/Seat 7.*位置/)).toBeVisible();
  });

  test("a common HU open produces a usable Current range after the user sets a Prior", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("combobox", { name: "范围侧" }).selectOption({ label: "Hero 范围" });
    await page.getByRole("button", { name: "标准化范围", exact: true }).click();
    await expect(page.getByText(/范围已标准化为/)).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /Raise to 200/ }).click();
    await page.getByRole("button", { name: "belief mode current" }).click();

    await expect(page.getByLabel("current range unavailable")).toBeHidden({ timeout: 10_000 });
    await expect(page.getByLabel("belief view")).toContainText(/Current|当前范围/);
  });
});
