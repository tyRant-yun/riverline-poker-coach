import { expect, test } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const css = readFileSync(path.resolve(__dirname, "../styles/table-v2.css"), "utf8");
const outputDir = path.resolve(__dirname, "../test-results/r8-01-visual");
const viewports = [[1280, 720], [1366, 768], [1440, 900], [1920, 1080]] as const;
function contrast(hexA: string, hexB: string) {
  const luminance = (hex: string) => hex.match(/\w\w/g)!.map((part) => Number.parseInt(part, 16) / 255).map((value) => value <= .03928 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
  const [a, b] = [luminance(hexA), luminance(hexB)]; return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}
// Static fixture deliberately mirrors the public V2 class/ARIA contract so the
// visual gate needs no app route or running API; component behavior is covered by Vitest.
const fixture = `<main class="tv2-workspace"><section class="tv2-stage" aria-label="六人德州扑克牌桌"><div class="tv2-felt"></div><div class="tv2-safe-zone" aria-label="底池与公共牌安全区"><div class="tv2-pot">底池 <strong>¥ 1,240</strong></div><div class="tv2-board"><i>Q♠</i><i>J♥</i><i>4♣</i></div></div>${["hero", "hj", "co", "btn", "sb", "bb"].map((id, index) => `<article class="tv2-seat tv2-seat-${index} ${id === "hero" ? "tv2-hero-seat is-current" : id === "hj" ? "is-thinking" : ""}" data-seat="${id}"><span class="tv2-position">${id.toUpperCase()}</span><div class="tv2-avatar">${id[0]}</div><div class="tv2-player"><b>${id === "hero" ? "Hero" : "Player"}</b><small>¥ 2,480</small></div>${id === "hj" ? '<span class="tv2-seat-narrative">Player 思考中…</span>' : ""}${id === "hero" ? '<div class="tv2-holecards" aria-label="Hero 手牌"><i>A♠</i><i>K♦</i></div>' : ""}</article>`).join("")}</section><aside class="tv2-rail" aria-label="决策驾驶舱"><section class="tv2-summary" aria-label="Decision Summary"><p>轮到 Hero · Flop · Pot 1,240</p><div><span>规则基线</span><strong>Advisor：过牌</strong></div><div><span>模拟估计</span><strong>Solver：下注 66% pot · 820</strong></div><b class="disagreement">存在分歧 · 原因尚未确定</b></section><section class="tv2-analysis-panel" aria-label="Solver 结果"><h2>模拟估计</h2><div class="tv2-ladder" aria-label="Solver Action Ladder"><article class="tv2-ladder-row"><strong>下注 66% pot · 820</strong><span>ΔEV +0.0</span><span>EV +12.5</span></article></div></section><section class="tv2-analysis-panel tv2-range-summary" aria-label="Range Belief"><h2>Range 摘要</h2><p>范围宽度 21.3% · 启发式</p></section></aside><section class="tv2-dock" aria-label="Hero 操作区"><div><small>轮到你</small><strong>按钮位</strong></div><div class="tv2-actions"><button>弃牌</button><button>跟注</button><button class="primary">加注</button></div></section></main>`;

test("V2 workspace preserves table, rail, and dock geometry across desktop viewports", async ({ page }) => {
  mkdirSync(outputDir, { recursive: true });
  await page.setContent(`<style>${css}</style>${fixture}`);
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    const safe = await page.getByLabel("底池与公共牌安全区").boundingBox();
    const stage = await page.getByLabel("六人德州扑克牌桌").boundingBox();
    const hero = await page.locator('[data-seat="hero"]').boundingBox();
    const cards = await page.getByLabel("Hero 手牌").locator("i").first().boundingBox();
    const dock = await page.getByLabel("Hero 操作区").boundingBox();
    const rail = await page.getByLabel("决策驾驶舱").boundingBox();
    const board = await page.locator(".tv2-board").boundingBox();
    expect(safe).not.toBeNull(); expect(stage).not.toBeNull(); expect(hero).not.toBeNull(); expect(cards).not.toBeNull(); expect(dock).not.toBeNull(); expect(rail).not.toBeNull(); expect(board).not.toBeNull();
    expect(Math.abs(hero!.x + hero!.width / 2 - (stage!.x + stage!.width / 2))).toBeLessThanOrEqual(8);
    expect(cards!.width).toBeGreaterThanOrEqual(width === 1366 ? 72 : 68); expect(cards!.height).toBeGreaterThanOrEqual(width === 1366 ? 100 : 94);
    expect(safe!.y + safe!.height + 16).toBeLessThan(hero!.y);
    expect(board!.y + board!.height + 16).toBeLessThan(hero!.y);
    expect(dock!.y).toBeGreaterThan(cards!.y + cards!.height + 8);
    expect(rail!.x).toBeGreaterThan(safe!.x + safe!.width);
    expect(await page.getByLabel("Decision Summary").isVisible()).toBeTruthy(); expect(await page.getByLabel("Solver Action Ladder").isVisible()).toBeTruthy(); expect(await page.getByText("Player 思考中…").isVisible()).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const tokens = await page.evaluate(() => ["--tv2-text", "--tv2-ink", "--tv2-line", "--tv2-graphite"].map((token) => getComputedStyle(document.documentElement).getPropertyValue(token).trim().replace("#", "")));
    expect(contrast(tokens[0], tokens[1])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(tokens[2], tokens[3])).toBeGreaterThanOrEqual(3);
    await page.screenshot({ path: path.join(outputDir, `workspace-${width}x${height}.png`), fullPage: false });
  }
});
