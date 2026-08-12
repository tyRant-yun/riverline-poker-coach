import type React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Scenario } from "../../types/scenario";

const api = vi.hoisted(() => ({
  state: vi.fn(),
  runAnalysis: vi.fn(),
}));

vi.mock("../../lib/api/client", () => ({
  analysisApi: { run: api.runAnalysis },
  coachApi: { explain: vi.fn() },
  practiceApi: { generate: vi.fn(), attempt: vi.fn() },
  rangesApi: { defaults: vi.fn().mockResolvedValue({ ranges: {} }), parse: vi.fn(), belief: vi.fn() },
  scenariosApi: { list: vi.fn().mockResolvedValue({ scenarios: [] }), state: api.state },
  solverApi: { submit: vi.fn(), get: vi.fn(), cancel: vi.fn() },
}));

vi.mock("../../components/AppShell", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../../components/poker/PokerTable", () => ({ default: () => null }));
vi.mock("../../components/poker/ActionBar", () => ({ default: () => null }));
vi.mock("../../features/scenario/ScenarioEditor", () => ({ default: () => null }));
vi.mock("../../features/range/RangeEditor", () => ({ default: () => null }));
vi.mock("../../features/history/ScenarioHistory", () => ({
  default: ({ onLoad }: { onLoad: (record: { scenarioId: string; title: string; scenario: Scenario; revisionNo: number }) => void }) => (
    <button onClick={() => onLoad({ scenarioId: "hand-1", title: "完整牌局", scenario: fullHand, revisionNo: 1 })}>
      载入完整牌局
    </button>
  ),
}));
vi.mock("../../features/workspace/ResultWorkspace", () => ({ default: () => null }));
vi.mock("../../features/coach/TeachingPanel", () => ({ default: () => null }));
vi.mock("../../features/practice/PracticePanel", () => ({ default: () => null }));
vi.mock("../../features/solver/SolverWorkspace", () => ({ default: () => null }));
vi.mock("../../features/workspace/AnalyzeActions", () => ({
  default: ({ onAnalyze }: { onAnalyze: () => void }) => <button onClick={onAnalyze}>分析节点</button>,
}));

import Home from "../../app/page";

const fullHand: Scenario = {
  schemaVersion: 1,
  gameVariant: "nlhe",
  tableSize: 2,
  smallBlind: 50,
  bigBlind: 100,
  buttonSeat: 0,
  heroSeat: 0,
  seats: [
    { seatId: 0, startingStack: 10_000, position: "button" },
    { seatId: 1, startingStack: 10_000, position: "big_blind" },
  ],
  heroHoleCards: ["As", "Kd"],
  villainHoleCards: ["Qh", "Jc"],
  board: ["2c", "7d", "Jh", "9s", "3h"],
  actionHistory: [
    { actionId: "call-1", sequence: 1, street: "preflop", actorSeat: 0, actionType: "call", amount: 50, amountType: "cost" },
    { actionId: "check-2", sequence: 2, street: "preflop", actorSeat: 1, actionType: "check" },
    { actionId: "deal-flop", sequence: 3, street: "flop", actorSeat: 0, actionType: "deal_flop" },
    { actionId: "check-4", sequence: 4, street: "flop", actorSeat: 1, actionType: "check" },
    { actionId: "deal-turn", sequence: 5, street: "turn", actorSeat: 0, actionType: "deal_turn" },
  ],
  decisionPoint: { street: "turn", actorSeat: 0, afterSequence: 5 },
  assumptions: {},
};

describe("selected decision workspace", () => {
  it("uses the action-before projection for legality and analysis without changing the editable hand", async () => {
    api.state.mockImplementation(async (scenario: Scenario) => ({
      finalState: {
        street: scenario.decisionPoint.street,
        actorSeat: scenario.decisionPoint.actorSeat,
        pot: 150,
        stacks: { "0": 9900, "1": 9900 },
        bets: { "0": 0, "1": 0 },
        legalActions: { actorSeat: scenario.decisionPoint.actorSeat, actions: ["check", "bet"] },
      },
    }));
    api.runAnalysis.mockResolvedValue({ analysis: {} });
    render(<Home />);

    fireEvent.click(screen.getByText("载入完整牌局"));
    const checkActions = await screen.findAllByRole("button", { name: /Seat 1 · check/i });
    fireEvent.click(checkActions[1]);
    await waitFor(() => expect(api.state).toHaveBeenCalledTimes(3));

    const legalityScenario = api.state.mock.calls.at(-1)?.[0] as Scenario;
    expect(legalityScenario.decisionPoint).toEqual({ street: "flop", actorSeat: 1, afterSequence: 3 });
    expect(legalityScenario.actionHistory.map((event) => event.actionId)).toEqual(["call-1", "check-2", "deal-flop"]);
    expect(legalityScenario.board).toEqual(["2c", "7d", "Jh"]);

    fireEvent.click(screen.getByRole("button", { name: "分析节点" }));
    await waitFor(() => expect(api.runAnalysis).toHaveBeenCalledTimes(1));
    const analysisScenario = api.runAnalysis.mock.calls[0][0] as Scenario;
    expect(analysisScenario).toEqual(legalityScenario);
    expect(fullHand.actionHistory).toHaveLength(5);
  });
});
