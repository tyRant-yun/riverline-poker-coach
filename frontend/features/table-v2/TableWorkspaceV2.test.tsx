import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActionPlaybackQueue, HeroActionDockV2, InsightRailV2, PokerTableStageV2, type ActionDelta } from "./TableWorkspaceV2";

const actions: ActionDelta[] = [{ id: "a", actor: "Bot 2", label: "跟注", kind: "action" }, { id: "b", actor: "Bot 3", label: "全下", kind: "all-in" }];
const table = {
  handComplete: false, heroHoleCards: ["Qh", "Qs"], heroLegalActions: [{ action: "call", amountSemantics: "cost", minAmount: 100, maxAmount: 100 }, { action: "fold", amountSemantics: "none" }],
} as never;

describe("Table V2 visual contracts", () => {
  it("anchors Hero at the horizontal centre with primary cards below their identity, separated from pot and board", () => {
    render(<PokerTableStageV2 seats={[{ id: "hero", name: "Hero", stack: "筹码 100", position: "BTN", status: "current", cards: ["A♠", "K♦"] }, ...Array.from({ length: 5 }, (_, index) => ({ id: String(index), name: `Seat ${index}`, stack: "筹码 100", position: `P${index}`, status: "waiting" as const }))]} board={["A♠", "K♦", "7♣"]} pot="450" />);
    expect(screen.getByLabelText("底池与公共牌安全区")).toHaveTextContent("450");
    expect(screen.getByLabelText("公共牌")).toHaveTextContent("A♠K♦7♣");
    expect(document.querySelectorAll("[data-seat]")).toHaveLength(6);
    expect(document.querySelector('[data-seat="hero"]')).toHaveClass("tv2-hero-seat");
    expect(document.querySelector('[data-seat="hero"] .tv2-holecards')).not.toBeNull();
  });

  it("places the public Bot thought and action narrative beside its actor seat", () => {
    render(<PokerTableStageV2 seats={[{ id: "2", name: "Bot 3", stack: "筹码 9,200", position: "UTG", status: "waiting" }, ...Array.from({ length: 5 }, (_, index) => ({ id: String(index + 3), name: `Seat ${index}`, stack: "筹码 100", position: `P${index}`, status: "waiting" as const }))]} thinkingAction={{ id: "think", actor: "Bot 3", actorSeat: "2", label: "", kind: "action" }} currentAction={{ id: "act", actor: "Bot 3", actorSeat: "2", label: "下注 66% ·", potDelta: "560", kind: "action" }} />);
    expect(screen.getByTestId("bot-thinking")).toHaveTextContent("Bot 3 思考中");
    expect(screen.getByTestId("bot-action-bubble")).toHaveTextContent("下注 66% · 560");
    expect(document.querySelector('[data-seat="2"]')).toHaveClass("is-thinking");
  });

  it("plays public actions in order with a 750ms final dwell, cancellation, and reduced motion", () => {
    const tasks: (() => void)[] = []; const setTimeout = vi.fn((fn) => { tasks.push(fn); return tasks.length; }); const clearTimeout = vi.fn(); const scheduler = { setTimeout, clearTimeout };
    const seen: string[] = []; const queue = new ActionPlaybackQueue(scheduler, false);
    const thinking: string[] = []; queue.play(actions, "comfort", (action) => seen.push(action.id), undefined, (action) => thinking.push(action?.id ?? "done"));
    expect(seen).toEqual([]); expect(thinking).toEqual(["a"]); expect(setTimeout).toHaveBeenCalledWith(expect.any(Function), 450);
    tasks.shift()!(); expect(seen).toEqual(["a"]); expect(setTimeout).toHaveBeenLastCalledWith(expect.any(Function), 900);
    tasks.shift()!(); expect(thinking).toEqual(["a", "done", "b"]); tasks.shift()!(); expect(seen).toEqual(["a", "b"]); expect(setTimeout).toHaveBeenLastCalledWith(expect.any(Function), 900);
    tasks.shift()!(); expect(thinking.at(-1)).toBe("done");
    queue.cancel(); expect(clearTimeout).toHaveBeenCalled();
    const reducedTasks: (() => void)[] = []; const reducedScheduler = { setTimeout: vi.fn((fn) => { reducedTasks.push(fn); return reducedTasks.length; }), clearTimeout: vi.fn() };
    const reduced: string[] = []; new ActionPlaybackQueue(reducedScheduler, true).play(actions, "slow", (action) => reduced.push(action.id));
    expect(reduced).toEqual(["a"]); expect(reducedScheduler.setTimeout).toHaveBeenCalledWith(expect.any(Function), 750);
    reducedTasks.shift()!(); expect(reduced).toEqual(["a", "b"]); expect(reducedScheduler.setTimeout).toHaveBeenLastCalledWith(expect.any(Function), 750);
  });

  it("disables accessible hero controls and only submits backend legal actions", () => {
    const action = vi.fn(); render(<HeroActionDockV2 table={table} disabled onAction={action} />);
    expect(screen.getByRole("button", { name: "跟注" })).toBeDisabled(); expect(screen.getByLabelText("call amount")).toBeDisabled();
    fireEvent.keyDown(window, { key: "c" }); expect(action).not.toHaveBeenCalled();
  });

  it("keeps Range summary and Solver evidence visible together without a tab switch", () => {
    render(<InsightRailV2 insights={{ available: true, advisor: { available: true, result: { status: "ready", recommendedAction: { action: "call", amountSemantics: "cost", reason: "price" }, source: "deterministic_formula", version: "v1", confidence: "high", explanationKey: "price", limitations: [], decision: { fingerprint: "fp", handId: "h1", sequence: 3, street: "flop" } } }, seatBeliefs: [{ seatId: 1, available: true, rangeWidthPct: 28.5, confidence: "heuristic", source: "riverline.heuristic_seed", version: "heuristic_seed_v2", approximate: true, approximationReason: "nearest_stack_bucket:100bb", changeReason: "公开行动：加注", limitations: ["这是独立边际估计，不含对手私牌。"], decision: { handId: "h1", afterSequence: 3 }, matrix169: { AA: { probabilityMass: "0.08", comboCount: 6 }, AKs: { probabilityMass: "0.05", comboCount: 4 } }, topClasses: [{ hand: "AA", probabilityMass: "0.08" }] }], stats: { available: true, bySeat: [{ seatId: 1, vpip: 0.25, pfr: 0.18, threeBet: 0.07 }] } }} solver={{ status: "degraded", recommendedAction: null, candidates: [{ action: "call", approximateEvChips: "12.5" }], equity: "0.42", iterations: 80, source: "monte_carlo", version: "v1", limitations: ["uniform opponents"] }} solverElapsedMs={24} />);
    expect(screen.getByLabelText("Range Belief")).toBeVisible(); expect(screen.getByLabelText("Solver 结果")).toBeVisible(); expect(screen.getByLabelText("Decision Summary")).toHaveTextContent("规则基线");
    expect(screen.getByText(/范围宽度 28.5%/)).toBeInTheDocument(); expect(screen.getByText(/近似：100BB 最近档/)).toBeInTheDocument();
    expect(screen.getByLabelText("Range Belief")).toHaveTextContent("C 级 · 公开行动启发式");
    expect(screen.getByLabelText("Range Belief")).toHaveTextContent("覆盖：近似");
    fireEvent.click(screen.getByRole("button", { name: /座位 2/ })); expect(screen.getByLabelText("Range Belief")).toHaveTextContent("最近变化：公开行动：加注");
    expect(screen.getAllByText(/模拟估计/).length).toBeGreaterThanOrEqual(1); expect(screen.getAllByText(/跟注/).length).toBeGreaterThanOrEqual(1);
  });
  it("shows the additive Range V2 and Solver L1.5 provenance without requiring new fields from old responses", () => {
    render(<InsightRailV2 insights={{ available: true, seatBeliefs: [{ seatId: 1, available: true, rangeWidthPct: 28.5, rangeWidthCombos: 214, confidenceScore: 0.8, dataVersion: "range-v2.1", changeReason: "公开行动：加注", approximate: true, approximationReason: "nearest_stack_bucket:100bb", matrix169: { AA: { probabilityMass: "0.08", comboCount: 6 } } }] }} solver={{ status: "ready", recommendedAction: { action: "call", amount: 100 }, candidates: [{ action: "call", amount: 100, approximateEvChips: "12.5", showdownEquity: "0.42", foldEquity: "0", sampleCount: 80, effectiveSampleSize: "80", confidenceInterval95: { lower: "8", upper: "17" }, responseMix: { fold: "0", call: "1", raise: "0" } }], equity: "0.42", iterations: 80, sampleCount: 80, effectiveSampleSize: "80", budgetTier: "standard", budgetMs: 150, confidence: "coarse", source: "range_weighted_public_beliefs", rangeStatus: "ready", version: "fast-ev-solver/v1", modelVersion: "fast-ev-solver/v1.5", limitations: ["not GTO"] }} />);
    expect(screen.getByText(/214 weighted combos/)).toBeInTheDocument();
    expect(screen.getByLabelText("Range Belief")).toHaveTextContent("范围宽度 28.5%");
    expect(screen.getByLabelText("Decision Summary")).toHaveTextContent("Advisor：暂不可用");
    expect(screen.getByLabelText("Solver Action Ladder")).toHaveTextContent("跟注 100");
  });
  it("renders backend-calibrated ΔEV, uncertainty, close, and extreme sizing facts without declaring GTO", () => {
    render(<InsightRailV2 solver={{ status: "ready", recommendedAction: { action: "bet", amount: 300 }, candidates: [{ action: "bet", amount: 300, approximateEvChips: "12.5", potPercentage: "66.666", deltaEvChips: "0", deltaEvConfidenceInterval95: { lower: "-0.2", upper: "0.2" }, uncertaintyStatus: "available", recommendationTier: "close", sizingClass: "standard" }, { action: "all_in", amount: 1_000, approximateEvChips: "11.1", potPercentage: "222.2", deltaEvChips: "-1.4", uncertaintyStatus: "not_available", recommendationTier: "not_recommended", sizingClass: "jam" }], equity: "0.42", iterations: 80, source: "range_weighted_public_beliefs", version: "fast-ev-solver/v1", sizingRobustness: "close", recommendationReasonCodes: ["close_conservative_tiebreak"], limitations: ["not GTO"] }} />);
    const ladder = screen.getByLabelText("Solver Action Ladder");
    expect(ladder).toHaveTextContent("66.7% pot"); expect(ladder).toHaveTextContent("ΔEV CI -0.2–+0.2");
    expect(ladder).toHaveTextContent("接近最优"); expect(ladder).toHaveTextContent("极端尺度：全压"); expect(ladder).toHaveTextContent("不确定性不可用");
    expect(screen.getByLabelText("Solver 结果")).toHaveTextContent("不是 GTO、Nash 或最终行动裁决");
  });
  it("sorts an unsorted ladder by ΔEV, keeps the real best in the first three, and expands all sizes", () => {
    render(<InsightRailV2 solver={{ status: "ready", recommendedAction: null, candidates: [{ action: "fold", approximateEvChips: "1", deltaEvChips: "-3" }, { action: "bet", amount: 200, approximateEvChips: "4", deltaEvChips: "0", potPercentage: "50" }, { action: "call", amount: 100, approximateEvChips: "3", deltaEvChips: "-1" }, { action: "all_in", amount: 900, approximateEvChips: "2", deltaEvChips: "-2" }], equity: "0.4", iterations: 10, source: "range_weighted_public_beliefs", version: "v1", limitations: [] }} />);
    const ladder = screen.getByLabelText("Solver Action Ladder");
    expect(ladder).toHaveTextContent(/^下注 · 50.0% pot · 200/); expect(ladder).not.toHaveTextContent("弃牌");
    fireEvent.click(screen.getByRole("button", { name: "全部尺度（4）" })); expect(ladder).toHaveTextContent("弃牌");
  });
  it("shows reconciliation amountChips, pot percentage, and available SPR without browser arbitration", () => {
    render(<InsightRailV2 table={{ heroSeat: 0, pot: 500, seats: [{ seatId: 0, stack: 5_000 }] } as never} reconciliation={{ status: "ready", decision: { fingerprint: "f", handId: "h", sequence: 1, street: "flop" }, ruleBaseline: { role: "rule_baseline", status: "ready", action: { action: "bet", amountSemantics: "to", amountChips: 330, potPct: "66" }, provenance: {}, limitations: [] }, simulationEstimate: { role: "simulation_estimate", status: "ready", action: { action: "call", amountSemantics: "cost", amountChips: 100, potPct: "20" }, provenance: {}, limitations: [] }, agreement: { kind: "different_action", reasonCodes: ["model_limitations"], confidenceInterval: { status: "available" }, sizingRobustness: "close" } }} />);
    const summary = screen.getByLabelText("Decision Summary"); expect(summary).toHaveTextContent("下注 · 66.0% pot · 330"); expect(summary).toHaveTextContent("跟注 · 20.0% pot · 100"); expect(summary).toHaveTextContent("SPR 10.0"); expect(summary).toHaveTextContent("存在分歧 · 模型限制");
  });
  it("retains the previous same-hand snapshot for verifiable Top movers", async () => {
    const table = { sessionId: "s", handId: "h", fingerprint: "a", street: "flop", pot: 100 };
    const belief = (fingerprint: string, aa: string, aks: string) => ({ table: { ...table, fingerprint } as never, insights: { available: true, seatBeliefs: [{ seatId: 1, available: true, matrix169: { AA: { probabilityMass: aa, comboCount: 6 }, AKs: { probabilityMass: aks, comboCount: 4 } } }] } });
    const view = render(<InsightRailV2 {...belief("a", "0.1", "0.1")} />);
    await waitFor(() => expect(screen.getByText(/Top movers 暂不可用/)).toBeInTheDocument());
    view.rerender(<InsightRailV2 {...belief("b", "0.2", "0.05")} />);
    await waitFor(() => expect(screen.getByTestId("range-top-movers")).toHaveTextContent("AA +10.0%"));
    expect(screen.getByTestId("range-top-movers")).toHaveTextContent("AKs -5.0%");
  });
  it("opens an accessible 13×13 Explorer with topology filters, cell details, and an honest delta baseline", () => {
    render(<InsightRailV2 table={{ sessionId: "s", handId: "h", fingerprint: "a", street: "flop", pot: 100 } as never} insights={{ available: true, seatBeliefs: [{ seatId: 1, available: true, rangeWidthPct: 28.5, rangeWidthCombos: 214, confidence: "low", source: "riverline.heuristic_seed", matrix169: { AA: { probabilityMass: "0.08", comboCount: 6 }, AKs: { probabilityMass: "0.05", comboCount: 4 }, AKo: { probabilityMass: "0", comboCount: 0 } } }] }} />);
    fireEvent.click(screen.getByRole("button", { name: "展开矩阵" }));
    expect(screen.getByRole("dialog", { name: "Range Explorer" })).toBeVisible();
    expect(screen.getByTestId("range-cell-AA")).toHaveAttribute("data-kind", "pair");
    expect(screen.getByTestId("range-cell-AKs")).toHaveAttribute("data-kind", "suited");
    expect(screen.getByTestId("range-cell-AKo")).toHaveAttribute("data-kind", "offsuit");
    expect(screen.getByTestId("range-cell-AKo")).toHaveAccessibleName(/已阻断/);
    expect(screen.getByTestId("range-cell-AA")).toHaveAttribute("class", expect.stringMatching(/density-[0-6]/));
    fireEvent.click(screen.getByRole("button", { name: "相对上一公开行动" }));
    expect(screen.getByText(/变化基线不可用/)).toBeInTheDocument();
    expect(screen.getByText(/变化：负↓/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "同花" }));
    expect(screen.getByTestId("range-cell-AA")).toHaveClass("is-filtered");
    expect(screen.getByTestId("range-cell-AKs")).not.toHaveClass("is-filtered");
  });
});
