import { expect, test } from "@playwright/test";
import path from "node:path";

test("can validate, analyze, and explain the default HU scene", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "构造决策场景" })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验场景" })).toBeVisible();

  await page.getByPlaceholder("牌面 1").fill("2c");
  await page.getByPlaceholder("牌面 2").fill("7d");
  await page.getByPlaceholder("牌面 3").fill("Jh");
  await page.getByRole("button", { name: "Call 50" }).click();
  await expect(page.getByRole("button", { name: "Check" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByRole("button", { name: "Deal flop" })).toBeEnabled({ timeout: 15_000 });
  await page.getByRole("button", { name: "Deal flop" }).click();
  await expect(page.getByText("规则校验通过，当前状态已更新。"))
    .toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Call 50" })).toBeVisible();

  await page.getByRole("button", { name: "生成分析" }).click();
  await expect(page.getByText("分析完成。所有定量结果都来自结构化证据。"))
    .toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("结构化分析")).toBeVisible();
  await expect(page.getByText("enumerated")).toBeVisible();

  await page.getByLabel("教学问题").fill("为什么这里的跟注要结合底池赔率？");
  await page.getByRole("button", { name: "教学解释" }).click();
  const teachingPanel = page.locator("section.teaching-panel");
  await expect(teachingPanel.getByRole("heading", { name: "证据约束的教学解释" }))
    .toBeVisible({ timeout: 15_000 });
  await expect(teachingPanel.locator(".teaching-summary")).toBeVisible();
});

test("normalizes a range and keeps the editor evidence-bound", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "标准化范围" }).click();

  await expect(page.getByText(/范围已标准化为/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByLabel("169 格范围矩阵")).toBeVisible();
  await expect(page.getByText(/点击矩阵格循环设置/)).toBeVisible();
  await page.getByLabel("默认范围").selectOption({ label: "BTN open 100BB" });
  await expect(page.getByText(/Villain 范围已标准化为/)).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("范围侧").selectOption("heroRange");
  await page.getByRole("button", { name: "标准化范围" }).click();
  await expect(page.getByText(/Hero 范围已标准化为/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "AA weight" }).click();
  await expect(page.getByText(/有效组合：/)).toBeVisible();
});

test("saves a scenario and reanalyzes it into history", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("牌面 1").fill("2c");
  await page.getByPlaceholder("牌面 2").fill("7d");
  await page.getByPlaceholder("牌面 3").fill("Jh");
  await page.getByRole("button", { name: "Call 50" }).click();
  await expect(page.getByRole("button", { name: "Check" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Check" }).click();
  await page.getByRole("button", { name: "Deal flop" }).click();
  await expect(page.getByText("规则校验通过，当前状态已更新。"))
    .toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "保存场景" }).click();

  await expect(page.getByText("场景已保存，可在历史记录中复制和重新分析。"))
    .toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "重新分析" }).first().click();
  await expect(page.getByText(/已重新分析「Manual review」/))
    .toBeVisible({ timeout: 30_000 });

  await page.getByPlaceholder("牌面 3").fill("Qs");
  await page.getByRole("button", { name: "保存场景" }).click();
  await expect(page.getByText("场景已更新，已生成新的历史修订。"))
    .toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "历史" }).first().click();
  await expect(page.getByText("SCENARIO REVISIONS")).toBeVisible({ timeout: 15_000 });
  const firstRevision = page.locator(".revision-row").filter({ hasText: "rev 1" });
  await expect(firstRevision).toBeVisible();
  await firstRevision.getByRole("button", { name: "载入" }).click();
  await expect(page.getByText("已载入第 1 个历史版本。"))
    .toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "生成分析" }).click();
  await expect(page.getByText("分析完成。所有定量结果都来自结构化证据。"))
    .toBeVisible({ timeout: 30_000 });
  await firstRevision.getByRole("button", { name: "重新分析" }).click();
  await expect(page.getByText(/第 1 个版本；结果已写入历史/))
    .toBeVisible({ timeout: 30_000 });
});

test("imports a ScenarioSpec through the editor", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("导入 JSON").setInputFiles(
    path.resolve(__dirname, "../../examples/scenario-flop.json"),
  );

  await expect(page.getByText("规则校验通过，当前状态已更新。"))
    .toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("3 events")).toBeVisible();
});
