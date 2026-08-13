import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActionPlaybackQueue, HeroActionDockV2, InsightRailV2, PokerTableStageV2, type ActionDelta } from "./TableWorkspaceV2";

const actions: ActionDelta[] = [{ id: "a", actor: "A", label: "跟注", kind: "action" }, { id: "b", actor: "B", label: "全下", kind: "all-in" }];
describe("Table V2 visual contracts", () => {
  it("keeps a dedicated board/pot safe zone and renders six seats", () => { render(<PokerTableStageV2 />); expect(screen.getByLabelText("底池与公共牌安全区")).toBeInTheDocument(); expect(document.querySelectorAll("[data-seat]")).toHaveLength(6); });
  it("communicates folded and showdown seats", () => { render(<PokerTableStageV2 />); expect(screen.getByLabelText(/UTG 林舟 folded/)).toBeInTheDocument(); expect(screen.getByLabelText(/SB 小北 showdown/)).toBeInTheDocument(); });
  it("plays in order, honors speed, cancellation, and reduced motion without sleeping", () => { const setTimeout = vi.fn((fn) => { fn(); return 1; }); const clearTimeout = vi.fn(); const scheduler = { setTimeout, clearTimeout }; const seen: string[] = []; const queue = new ActionPlaybackQueue(scheduler, false); queue.play(actions, "fast", (a) => seen.push(a.id)); expect(seen).toEqual(["a", "b"]); expect(setTimeout).toHaveBeenCalledWith(expect.any(Function), 292.5); queue.cancel(); expect(clearTimeout).toHaveBeenCalled(); const reduced: string[] = []; new ActionPlaybackQueue(scheduler, true).play(actions, "slow", (a) => reduced.push(a.id)); expect(reduced).toEqual(["a", "b"]); });
  it("disables accessible hero controls while action is pending", () => { render(<HeroActionDockV2 disabled />); expect(screen.getByRole("button", { name: "弃牌" })).toBeDisabled(); expect(screen.getByLabelText("下注额")).toBeDisabled(); });
  it("shows honest range unavailable and solver degraded states", () => { render(<InsightRailV2 range={{ status: "unavailable", message: "范围暂不可用，请在下一决策后重试。" }} solver={{ status: "degraded", message: "求解超时，展示简化建议。" }} />); fireEvent.click(screen.getByRole("button", { name: "Range" })); expect(screen.getByText(/范围暂不可用/)).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Solver" })); expect(screen.getByText(/求解超时/)).toBeInTheDocument(); });
});
