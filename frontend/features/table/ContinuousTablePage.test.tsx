import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContinuousTablePage from "./ContinuousTablePage";

const api = vi.hoisted(() => ({
  create: vi.fn(), get: vi.fn(), action: vi.fn(), nextHand: vi.fn(), insights: vi.fn(), solver: vi.fn(), reviews: vi.fn(),
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
  fingerprint: "decision-a",
};

describe("ContinuousTablePage", () => {
  beforeEach(() => {
    window.localStorage.clear(); vi.clearAllMocks();
    api.create.mockResolvedValue({ table }); api.action.mockResolvedValue({ table }); api.nextHand.mockResolvedValue({ table: { ...table, handSequence: 4 } });
    api.insights.mockResolvedValue({ insights: { available: true, advisor: { available: true, result: { recommendedAction: { action: "check", reason: "free" }, source: "deterministic_formula", version: "formula-advisor/v1" } }, seatBeliefs: [{ seatId: 1, available: true, provenance: { version: "heuristic_likelihood_v1" } }], stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] } } });
    api.solver.mockResolvedValue({ solver: { status: "ready", recommendedAction: { action: "call", amount: 100 }, candidates: [{ action: "fold", approximateEvChips: "0" }, { action: "call", amount: 100, approximateEvChips: "12.5" }], equity: "0.42", iterations: 80, source: "monte_carlo_uniform_opponents", version: "fast-ev-solver/v1", limitations: ["uniform opponents"] } });
    api.reviews.mockResolvedValue({ available: true, review: { handId: table.handId, heroSeat: 0, completionSequence: 12, heroDecisions: [], references: {} } });
  });

  it("creates a selected bot-profile table and shows only hero cards", async () => {
    render(<ContinuousTablePage />);
    fireEvent.change(screen.getByTestId("bot-profile"), { target: { value: "aggressive" } });
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ botProfile: "aggressive" })));
    expect(screen.getByTestId("table-workspace-v2")).toBeInTheDocument();
    expect(screen.getByLabelText("Q♥")).toBeInTheDocument();
    expect(screen.queryByLabelText("A♥")).not.toBeInTheDocument();
    expect(await screen.findByLabelText("Advisor 摘要")).toHaveTextContent("建议：过牌");
    expect(screen.getByLabelText("Range Belief")).toHaveTextContent("不含对手私牌");
    expect(screen.getByLabelText("Solver 结果")).toHaveTextContent("fast-ev-solver/v1");
  });

  it("uses the V2 workspace as the real table entry and renders backend table facts", async () => {
    render(<ContinuousTablePage />);
    fireEvent.click(screen.getByTestId("create-continuous-table"));

    expect(await screen.findByTestId("table-workspace-v2")).toBeInTheDocument();
    expect(screen.getByLabelText("底池与公共牌安全区")).toHaveTextContent("450");
    expect(screen.getByLabelText("Hero 操作区")).toHaveTextContent("Q♥ Q♠");
    expect(screen.queryByTestId("poker-table")).not.toBeInTheDocument();
  });

  it("keeps L0 visible while L1 loads and ignores an old solver response after a new decision", async () => {
    let resolveA: (value: unknown) => void;
    let resolveB: (value: unknown) => void;
    api.solver
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve; }));
    api.action.mockResolvedValueOnce({ table: { ...table, revision: 19, board: ["As", "Kd", "7c", "2h"] } });
    render(<ContinuousTablePage />);
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    await waitFor(() => expect(api.solver).toHaveBeenCalledWith("table-1", expect.objectContaining({ handId: table.handId, decisionFingerprint: expect.any(String), budgetTier: "standard" })));
    expect(await screen.findByLabelText("Advisor 摘要")).toHaveTextContent("建议：过牌");
    fireEvent.click(screen.getByTestId("hero-action-call"));
    await waitFor(() => expect(api.solver).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Solver 结果")).toHaveTextContent("Fast Solver（standard）计算中");

    resolveB!({ solver: { status: "degraded", recommendedAction: { action: "call", amount: 100 }, candidates: [{ action: "call", amount: 100, approximateEvChips: "4" }], equity: "0.4", iterations: 20, source: "monte_carlo_uniform_opponents", version: "fast-ev-solver/v1", limitations: ["partial"] } });
    await waitFor(() => expect(screen.getByTestId("table-insights")).toHaveTextContent("近似 EV 求解（降级）"));
    resolveA!({ solver: { status: "ready", recommendedAction: { action: "fold" }, candidates: [{ action: "fold", approximateEvChips: "0" }], equity: "0.1", iterations: 80, source: "monte_carlo_uniform_opponents", version: "fast-ev-solver/v1", limitations: [] } });
    await waitFor(() => expect(screen.getByTestId("table-insights")).not.toHaveTextContent("推荐 fold"));
  });

  it("releases Hero controls when the latest bot-transition snapshot returns the turn to Hero", async () => {
    api.action.mockResolvedValueOnce({ table: {
      ...table, revision: 19, fingerprint: "decision-b",
      actionHistory: [...table.actionHistory, { sequence: 9, street: "flop", actorSeat: 2, action: "call", amount: 100 }],
      botDecisionProvenance: [...table.botDecisionProvenance, { sequence: 9, actorSeat: 2, profileId: "balanced", provider: "lightweight-blueprint", degraded: false, fallbackReason: null }],
    } });
    render(<ContinuousTablePage />);
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    const call = await screen.findByTestId("hero-action-call");
    fireEvent.click(call);
    await waitFor(() => expect(api.action).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("hero-action-call")).toBeEnabled());
  });

  it("reconnects, submits only a backend legal action, and starts the next hand", async () => {
    window.localStorage.setItem("riverline-continuous-table-session", "table-1");
    api.get.mockResolvedValue({ table });
    render(<ContinuousTablePage />);
    await waitFor(() => expect(screen.getByTestId("hero-action-call")).toBeInTheDocument());
    api.action.mockResolvedValueOnce({ table: { ...table, handComplete: true, currentActor: null, heroLegalActions: [], result: { winnerSeats: [0], payouts: { "0": 450 } } } });
    fireEvent.click(screen.getByTestId("hero-action-call"));
    await waitFor(() => expect(api.action).toHaveBeenCalledWith("table-1", expect.objectContaining({ action: "call", amount: 100, amountSemantics: "cost" })));
    await waitFor(() => expect(screen.getByTestId("next-hand")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("next-hand"));
    await waitFor(() => expect(api.nextHand).toHaveBeenCalledWith("table-1", expect.objectContaining({ expectedRevision: 18 })));
  });

  it("shows terminal opponent reveals and clears them for the next hand", async () => {
    const completed = {
      ...table,
      handComplete: true,
      currentActor: null,
      heroLegalActions: [],
      result: { winnerSeats: [1], payouts: { "1": 450 } },
      seats: table.seats.map((seat) => seat.seatId === 1
        ? { ...seat, status: "complete", revealedHoleCards: ["Ah", "Kh"] }
        : { ...seat, status: seat.seatId === 3 ? "folded" : "complete" }),
    };
    const next = {
      ...table,
      handId: "table-1:hand:4",
      handSequence: 4,
      revision: 19,
      heroHoleCards: ["2c", "3d"],
    };
    api.action.mockResolvedValueOnce({ table: completed });
    api.nextHand.mockResolvedValueOnce({ table: next });

    render(<ContinuousTablePage />);
    fireEvent.click(screen.getByTestId("create-continuous-table"));
    fireEvent.click(await screen.findByTestId("hero-action-call"));

    await waitFor(() => expect(api.action).toHaveBeenCalledTimes(1));
    expect(await screen.findByLabelText("A♥")).toBeInTheDocument();
    expect(screen.getByLabelText("K♥")).toBeInTheDocument();
    expect(screen.queryByLabelText("card back")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("next-hand"));
    await screen.findByLabelText("2♣");
    expect(screen.queryByLabelText("A♥")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("card back")).not.toBeInTheDocument();
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
    expect(screen.getByLabelText("Advisor 摘要")).toHaveTextContent("Advisor 暂不可用；请以合法行动与桌面事实为准。");

    resolveB!({ insights: { available: true, advisor: { available: true, result: { recommendedAction: { action: "call", reason: "B" }, source: "deterministic_formula", version: "formula-advisor/v1" } }, seatBeliefs: [], stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] } } });
    await waitFor(() => expect(screen.getByLabelText("Advisor 摘要")).toHaveTextContent("建议：跟注"));
    resolveA!({ insights: { available: true, advisor: { available: true, result: { recommendedAction: { action: "check", reason: "A" }, source: "deterministic_formula", version: "formula-advisor/v1" } }, seatBeliefs: [], stats: { available: false, unavailableReason: "stats_not_ready", bySeat: [] } } });
    await waitFor(() => expect(screen.getByLabelText("Advisor 摘要")).toHaveTextContent("建议：跟注"));
  });

  it("clears the prior hand review and ignores an out-of-order terminal review", async () => {
    let resolveA: (value: unknown) => void;
    let resolveB: (value: unknown) => void;
    const completedA = { ...table, handComplete: true, currentActor: null, heroLegalActions: [], result: { winnerSeats: [0], payouts: { "0": 450 } } };
    const activeB = { ...table, handId: "table-1:hand:4", handSequence: 4, revision: 19 };
    const completedB = { ...activeB, handComplete: true, currentActor: null, revision: 20, heroLegalActions: [], result: { winnerSeats: [0], payouts: { "0": 450 } } };
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
