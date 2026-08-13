import { fireEvent, render, screen } from "@testing-library/react";
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

  it("plays in order, honors speed, cancellation, and reduced motion without sleeping", () => {
    const setTimeout = vi.fn((fn) => { fn(); return 1; }); const clearTimeout = vi.fn(); const scheduler = { setTimeout, clearTimeout };
    const seen: string[] = []; const queue = new ActionPlaybackQueue(scheduler, false);
    queue.play(actions, "fast", (action) => seen.push(action.id));
    expect(seen).toEqual(["a", "b"]); expect(setTimeout).toHaveBeenCalledWith(expect.any(Function), 292.5);
    queue.cancel(); expect(clearTimeout).toHaveBeenCalled();
    const reduced: string[] = []; new ActionPlaybackQueue(scheduler, true).play(actions, "slow", (action) => reduced.push(action.id));
    expect(reduced).toEqual(["a", "b"]);
  });

  it("disables accessible hero controls and only submits backend legal actions", () => {
    const action = vi.fn(); render(<HeroActionDockV2 table={table} disabled onAction={action} />);
    expect(screen.getByRole("button", { name: "跟注" })).toBeDisabled(); expect(screen.getByLabelText("call amount")).toBeDisabled();
    fireEvent.keyDown(window, { key: "c" }); expect(action).not.toHaveBeenCalled();
  });

  it("keeps Range heatmap and Solver evidence visible together without a tab switch", () => {
    render(<InsightRailV2 insights={{ available: true, advisor: { available: true, result: { recommendedAction: { action: "call", reason: "price" }, source: "deterministic_formula", version: "v1" } }, seatBeliefs: [{ seatId: 1, available: true, rangeWidthPct: 28.5, confidence: "heuristic", source: "riverline.heuristic_seed", version: "heuristic_seed_v2", approximate: true, approximationReason: "nearest_stack_bucket:100bb", changeReason: "公开行动：加注", limitations: ["这是独立边际估计，不含对手私牌。"], decision: { handId: "h1", afterSequence: 3 }, matrix169: { AA: { probabilityMass: "0.08", comboCount: 6 }, AKs: { probabilityMass: "0.05", comboCount: 4 } }, topClasses: [{ hand: "AA", probabilityMass: "0.08" }] }], stats: { available: true, bySeat: [{ seatId: 1, vpip: 0.25, pfr: 0.18, threeBet: 0.07 }] } }} solver={{ status: "degraded", recommendedAction: null, candidates: [{ action: "call", approximateEvChips: "12.5" }], equity: "0.42", iterations: 80, source: "monte_carlo", version: "v1", limitations: ["uniform opponents"] }} solverElapsedMs={24} />);
    expect(screen.getByLabelText("Range Belief")).toBeVisible(); expect(screen.getByLabelText("Solver 结果")).toBeVisible();
    expect(screen.getByText(/范围宽度 28.5%/)).toBeInTheDocument(); expect(screen.getByText(/近似：100BB 最近档/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /座位 2/ })); expect(screen.getByLabelText("座位 2 Range 热图")).toBeInTheDocument(); expect(screen.getByTitle(/AA：概率质量 8.00%/)).toBeInTheDocument();
    expect(screen.getByText(/不是 GTO 或 Nash/)).toBeInTheDocument(); expect(screen.getByText(/耗时 24ms/)).toBeInTheDocument();
  });
});
