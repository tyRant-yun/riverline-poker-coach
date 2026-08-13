import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActionPlaybackQueue, HeroActionDockV2, InsightRailV2, PokerTableStageV2, type ActionDelta } from "./TableWorkspaceV2";

const actions: ActionDelta[] = [{ id: "a", actor: "Bot 2", label: "跟注", kind: "action" }, { id: "b", actor: "Bot 3", label: "全下", kind: "all-in" }];
const table = {
  handComplete: false, heroHoleCards: ["Qh", "Qs"], heroLegalActions: [{ action: "call", amountSemantics: "cost", minAmount: 100, maxAmount: 100 }, { action: "fold", amountSemantics: "none" }],
} as never;

describe("Table V2 visual contracts", () => {
  it("keeps a dedicated board/pot safe zone and renders supplied table facts", () => {
    render(<PokerTableStageV2 seats={Array.from({ length: 6 }, (_, index) => ({ id: String(index), name: `Seat ${index}`, stack: "筹码 100", position: `P${index}`, status: "waiting" as const }))} board={["A♠", "K♦", "7♣"]} pot="450" />);
    expect(screen.getByLabelText("底池与公共牌安全区")).toHaveTextContent("450");
    expect(screen.getByLabelText("公共牌")).toHaveTextContent("A♠K♦7♣");
    expect(document.querySelectorAll("[data-seat]")).toHaveLength(6);
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

  it("shows honest range data gaps, localized stats, and approximate solver limitations", () => {
    render(<InsightRailV2 insights={{ available: true, advisor: { available: true, result: { recommendedAction: { action: "call", reason: "price" }, source: "deterministic_formula", version: "v1" } }, seatBeliefs: [{ seatId: 1, available: false, unavailableReason: "stack_bucket_unsupported" }], stats: { available: true, bySeat: [{ seatId: 1, vpip: 0.25, pfr: 0.18, threeBet: 0.07 }] } }} solver={{ status: "degraded", recommendedAction: null, candidates: [{ action: "call", approximateEvChips: "12.5" }], equity: "0.42", iterations: 80, source: "monte_carlo", version: "v1", limitations: ["uniform opponents"] }} solverElapsedMs={24} />);
    fireEvent.click(screen.getByRole("button", { name: "Range" })); expect(screen.getByText(/当前筹码档位暂不支持/)).toBeInTheDocument(); expect(screen.getByText(/未伪造热图/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Solver" })); expect(screen.getByText(/不是 GTO 或 Nash/)).toBeInTheDocument(); expect(screen.getByText(/耗时 24ms/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stats" })); expect(screen.getByText(/入池率 25%/)).toBeInTheDocument();
  });
});
