import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContinuousTablePage from "./ContinuousTablePage";

const api = vi.hoisted(() => ({
  create: vi.fn(), get: vi.fn(), action: vi.fn(), nextHand: vi.fn(), insights: vi.fn(), reviews: vi.fn(),
}));
vi.mock("../../lib/api/client", () => ({ continuousTableApi: api }));

const table = {
  sessionId: "table-1", handId: "table-1:hand:3", handSequence: 3, buttonSeat: 2, heroSeat: 0, revision: 18,
  board: ["As", "Kd", "7c"], pot: 450, street: "flop", currentActor: 0, heroHoleCards: ["Qh", "Qs"],
  seats: Array.from({ length: 6 }, (_, seatId) => ({ seatId, stack: 10_000 - seatId * 100, status: "active", committed: seatId === 1 ? 100 : 0 })),
  heroLegalActions: [{ action: "call", amountSemantics: "cost", minAmount: 100, maxAmount: 100 }, { action: "fold", amountSemantics: "none" }],
  actionHistory: [{ sequence: 8, street: "flop", actorSeat: 1, action: "bet", amount: 100 }],
  handComplete: false, result: null,
  botDecisionProvenance: [{ sequence: 8, actorSeat: 1, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null }],
};

describe("ContinuousTablePage", () => {
  beforeEach(() => {
    window.localStorage.clear(); vi.clearAllMocks();
    api.create.mockResolvedValue({ table }); api.action.mockResolvedValue({ table }); api.nextHand.mockResolvedValue({ table: { ...table, handSequence: 4 } });
    api.insights.mockResolvedValue({ insights: { available: true, advisor: { available: true, result: { recommendedAction: { action: "check", reason: "free" }, source: "deterministic_formula", version: "formula-advisor/v1" } }, seatBeliefs: [{ seatId: 1, available: true, provenance: { version: "heuristic_likelihood_v1" } }], stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] } } });
    api.reviews.mockResolvedValue({ available: true, review: { handId: table.handId, heroSeat: 0, completionSequence: 12, heroDecisions: [], references: {} } });
  });

  it("creates a selected bot-profile table and shows only hero cards", async () => {
    render(<ContinuousTablePage />);
    fireEvent.change(screen.getByTestId("bot-profile"), { target: { value: "aggressive" } });
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ botProfile: "aggressive" })));
    expect(screen.getByTestId("poker-table")).toBeInTheDocument();
    expect(screen.getByLabelText("Q♥")).toBeInTheDocument();
    expect(screen.getAllByLabelText("card back")).toHaveLength(10);
    expect(screen.getByTestId("table-insights")).toHaveTextContent("deterministic_formula");
  });

  it("reconnects, submits only a backend legal action, and starts the next hand", async () => {
    window.localStorage.setItem("riverline-continuous-table-session", "table-1");
    api.get.mockResolvedValue({ table });
    render(<ContinuousTablePage />);
    await waitFor(() => expect(screen.getByTestId("hero-action-call")).toBeInTheDocument());
    api.action.mockResolvedValueOnce({ table: { ...table, handComplete: true, currentActor: null } });
    fireEvent.click(screen.getByTestId("hero-action-call"));
    await waitFor(() => expect(api.action).toHaveBeenCalledWith("table-1", expect.objectContaining({ action: "call", amount: 100, amountSemantics: "cost" })));
    await waitFor(() => expect(screen.getByTestId("next-hand")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("next-hand"));
    await waitFor(() => expect(api.nextHand).toHaveBeenCalledWith("table-1", expect.objectContaining({ expectedRevision: 18 })));
  });

  it("clears old insights and ignores an out-of-order response after a table transition", async () => {
    let resolveA: (value: unknown) => void;
    let resolveB: (value: unknown) => void;
    api.insights
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve; }));
    api.action.mockResolvedValueOnce({ table: { ...table, revision: 19, board: ["As", "Kd", "7c", "2h"] } });
    render(<ContinuousTablePage />);
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    await waitFor(() => expect(api.insights).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("hero-action-call"));
    await waitFor(() => expect(api.insights).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("table-insights")).toHaveTextContent("洞察未就绪");

    resolveB!({ insights: { available: true, advisor: { available: true, result: { recommendedAction: { action: "call", reason: "B" }, source: "deterministic_formula", version: "formula-advisor/v1" } }, seatBeliefs: [], stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] } } });
    await waitFor(() => expect(screen.getByTestId("table-insights")).toHaveTextContent("call · deterministic_formula"));
    resolveA!({ insights: { available: true, advisor: { available: true, result: { recommendedAction: { action: "check", reason: "A" }, source: "deterministic_formula", version: "formula-advisor/v1" } }, seatBeliefs: [], stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] } } });
    await waitFor(() => expect(screen.getByTestId("table-insights")).toHaveTextContent("call · deterministic_formula"));
  });

  it("clears the prior hand review and ignores an out-of-order terminal review", async () => {
    let resolveA: (value: unknown) => void;
    let resolveB: (value: unknown) => void;
    const completedA = { ...table, handComplete: true, currentActor: null };
    const activeB = { ...table, handId: "table-1:hand:4", handSequence: 4, revision: 19 };
    const completedB = { ...activeB, handComplete: true, currentActor: null, revision: 20 };
    api.action.mockResolvedValueOnce({ table: completedA }).mockResolvedValueOnce({ table: completedB });
    api.nextHand.mockResolvedValueOnce({ table: activeB });
    api.reviews
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve; }));
    render(<ContinuousTablePage />);
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    fireEvent.click(await screen.findByTestId("hero-action-call"));
    await waitFor(() => expect(api.reviews).toHaveBeenCalledWith("table-1", "table-1:hand:3"));
    fireEvent.click(screen.getByTestId("next-hand"));
    await screen.findByTestId("hero-action-call");
    fireEvent.click(screen.getByTestId("hero-action-call"));
    await waitFor(() => expect(api.reviews).toHaveBeenCalledWith("table-1", "table-1:hand:4"));
    expect(screen.getByTestId("table-review-status")).toHaveTextContent("复盘未就绪");
    resolveB!({ available: true, review: { handId: "table-1:hand:4", heroSeat: 0, completionSequence: 20, heroDecisions: [], references: {} } });
    await waitFor(() => expect(screen.getByTestId("table-review-status")).toHaveTextContent("复盘可用"));
    resolveA!({ available: true, review: { handId: "table-1:hand:3", heroSeat: 0, completionSequence: 18, heroDecisions: [], references: {} } });
    await waitFor(() => expect(screen.getByTestId("table-review-status")).toHaveTextContent("复盘可用"));
  });
});
