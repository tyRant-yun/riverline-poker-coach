import { expect, test } from "@playwright/test";

test("constructs 6-max and 8-max tables with derived actors and seat-driven ranges", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("combobox", { name: "桌型" }).selectOption("6");
  await page.getByRole("combobox", { name: "按钮位" }).selectOption("2");
  await page.getByRole("combobox", { name: "Hero 座位" }).selectOption("4");
  await expect(page.getByLabel("Seat 5 位置")).toHaveText("UTG");
  await page.getByLabel("Seat 5 起始筹码").fill("9000");
  await expect(page.getByLabel("Seat 5 起始筹码")).toHaveValue("9000");
  await expect(page.locator(".action-box")).toContainText("UTG · Seat 5", { timeout: 10_000 });
  await page.getByRole("button", { name: "Fold", exact: true }).click();
  await expect(page.getByText("1 events")).toBeVisible();
  await expect(page.locator(".action-box")).toContainText("MP · Seat 0", { timeout: 10_000 });

  await page.getByRole("combobox", { name: "桌型" }).selectOption("8");
  await page.getByRole("combobox", { name: "按钮位" }).selectOption("4");
  await page.getByRole("combobox", { name: "Hero 座位" }).selectOption("5");
  await expect(page.getByLabel("Seat 7 位置")).toHaveText("UTG");
  await page.getByLabel("范围玩家", { exact: true }).selectOption("7");
  await expect(page.getByRole("heading", { name: "Seat 7 起始范围（Prior）" })).toBeVisible();
  await expect(page.locator(".action-box")).toContainText("UTG · Seat 7", { timeout: 10_000 });
  await page.getByRole("button", { name: "Fold", exact: true }).click();
  await expect(page.getByText("1 events")).toBeVisible();
  await expect(page.locator(".action-box")).toContainText("UTG+1 · Seat 0", { timeout: 10_000 });
});
