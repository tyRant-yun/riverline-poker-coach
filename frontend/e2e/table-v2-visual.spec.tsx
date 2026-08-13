import { expect, test } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const css = readFileSync(path.resolve(__dirname, "../styles/table-v2.css"), "utf8");
const outputDir = path.resolve(__dirname, "../../docs/ux/r6-03b");
const viewports = [[1280, 720], [1366, 768], [1440, 900], [1920, 1080]] as const;
// Static fixture deliberately mirrors the public V2 class/ARIA contract so the
// visual gate needs no app route or running API; component behavior is covered by Vitest.
const fixture = `<div class="tv2-toolbar">第 1 手 · flop<label>Bot 播放<select><option>标准</option></select></label></div><main class="tv2-workspace"><section class="tv2-stage" aria-label="六人德州扑克牌桌"><div class="tv2-felt"></div><div class="tv2-safe-zone" aria-label="底池与公共牌安全区"><div class="tv2-pot">底池 <strong>¥ 1,240</strong></div><div class="tv2-board"><i>Q♠</i><i>J♥</i><i>4♣</i></div></div>${["utg", "hj", "co", "btn", "sb", "bb"].map((id, index) => `<article class="tv2-seat tv2-seat-${index} ${id === "btn" ? "is-current" : ""}" data-seat="${id}"><span class="tv2-position">${id.toUpperCase()}</span><div class="tv2-avatar">${id[0]}</div><div class="tv2-player"><b>${id === "btn" ? "Hero" : "Player"}</b><small>¥ 2,480</small></div></article>`).join("")}</section><aside class="tv2-rail" aria-label="分析洞察"><nav><button aria-selected="true">Advisor</button><button>Range</button><button>Solver</button><button>Stats</button></nav><div class="tv2-rail-content"><p>建议：保留跟注与小尺度加注两条线。</p></div></aside><section class="tv2-dock" aria-label="Hero 操作区"><div><small>轮到你</small><strong>按钮位</strong></div><div class="tv2-actions"><button>弃牌</button><button>跟注</button><button class="primary">加注</button></div><label>下注额<input value="¥ 360" /></label></section></main>`;

test("V2 workspace preserves table, rail, and dock geometry across desktop viewports", async ({ page }) => {
  mkdirSync(outputDir, { recursive: true });
  await page.setContent(`<style>${css}</style>${fixture}`);
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    const safe = await page.getByLabel("底池与公共牌安全区").boundingBox();
    const hero = await page.locator('[data-seat="btn"]').boundingBox();
    const dock = await page.getByLabel("Hero 操作区").boundingBox();
    const rail = await page.getByLabel("分析洞察").boundingBox();
    expect(safe).not.toBeNull(); expect(hero).not.toBeNull(); expect(dock).not.toBeNull(); expect(rail).not.toBeNull();
    expect(safe!.y + safe!.height).toBeLessThan(hero!.y - 8);
    expect(dock!.y).toBeGreaterThan(safe!.y + safe!.height);
    expect(rail!.x).toBeGreaterThan(safe!.x + safe!.width);
    expect(rail!.y).toBeGreaterThan(100);
    await page.screenshot({ path: path.join(outputDir, `workspace-${width}x${height}.png`), fullPage: false });
  }
});
