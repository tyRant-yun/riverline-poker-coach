import type React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { handReviewResponseFixture } from "../../test/handReviewFixtures";

const api = vi.hoisted(() => ({
  review: vi.fn(),
  state: vi.fn().mockResolvedValue({ finalState: {
    street: "preflop", actorSeat: 0, pot: 150, stacks: {}, bets: {},
    legalActions: { actorSeat: 0, actions: [] },
  } }),
}));

vi.mock("../../lib/api/client", () => ({
  analysisApi: { run: vi.fn() },
  coachApi: { explain: vi.fn() },
  handReviewApi: { review: api.review },
  practiceApi: { generate: vi.fn(), attempt: vi.fn() },
  rangesApi: { defaults: vi.fn().mockResolvedValue({ ranges: {} }), parse: vi.fn(), belief: vi.fn() },
  scenariosApi: { list: vi.fn().mockResolvedValue({ scenarios: [] }), state: api.state },
  solverApi: { submit: vi.fn(), get: vi.fn(), cancel: vi.fn() },
}));

vi.mock("../../components/AppShell", () => ({ default: ({ children }: { children?: React.ReactNode }) => <>{children}</> }));
vi.mock("../../components/poker/PokerTable", () => ({ default: () => null }));
vi.mock("../../components/poker/ActionBar", () => ({ default: () => null }));
vi.mock("../../features/scenario/ScenarioEditor", () => ({
  default: ({ onUpdateScenario }: { onUpdateScenario: (patch: unknown) => void }) => (
    <>
      <button onClick={() => onUpdateScenario({ smallBlind: 60 })}>修改场景</button>
      <button onClick={() => onUpdateScenario({
        actionHistory: [{ actionId: "a1", sequence: 1, street: "preflop", actorSeat: 0, actionType: "fold" }],
        decisionPoint: { street: "preflop", actorSeat: 1, afterSequence: 1 },
      })}>载入已完成手牌</button>
    </>
  ),
}));
vi.mock("../../features/range/RangeEditor", () => ({ default: () => null }));
vi.mock("../../features/history/ScenarioHistory", () => ({ default: () => null }));
vi.mock("../../features/workspace/ResultWorkspace", () => ({ default: () => null }));
vi.mock("../../features/coach/TeachingPanel", () => ({ default: () => null }));
vi.mock("../../features/practice/PracticePanel", () => ({ default: () => null }));
vi.mock("../../features/solver/SolverWorkspace", () => ({ default: () => null }));
vi.mock("../../features/workspace/AnalyzeActions", () => ({
  default: ({ onHandReview }: { onHandReview: () => void }) => (
    <button onClick={onHandReview}>生成整手复盘（页面入口）</button>
  ),
}));

import Home from "../../app/page";

describe("whole-hand review page integration", () => {
  it("sends a raw request through the explicit adapter and displays the adapted result", async () => {
    api.review.mockResolvedValueOnce(handReviewResponseFixture());
    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: "生成整手复盘（页面入口）" }));
    expect(screen.getByText("正在生成整手复盘…")).toBeInTheDocument();
    expect(await screen.findByText("整手需要优先复盘翻牌圈行动。")).toBeInTheDocument();
    expect(screen.getByText("Raise to 250")).toBeInTheDocument();
    expect(api.review).toHaveBeenCalledWith(expect.objectContaining({ scenario: expect.any(Object) }));
    expect(api.review.mock.calls[0][0].solverJobs).toBeUndefined();
  });

  it("keeps the newest response when an older request resolves afterwards", async () => {
    let resolveOld!: (value: ReturnType<typeof handReviewResponseFixture>) => void;
    let resolveNew!: (value: ReturnType<typeof handReviewResponseFixture>) => void;
    api.review
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: "生成整手复盘（页面入口）" }));
    fireEvent.click(screen.getByRole("button", { name: "生成整手复盘（页面入口）" }));
    const newest = handReviewResponseFixture();
    newest.review.wholeHandSummary!.summary = "新请求结果";
    resolveNew(newest);
    expect(await screen.findByText("新请求结果")).toBeInTheDocument();
    resolveOld(handReviewResponseFixture());
    await waitFor(() => expect(screen.getByText("新请求结果")).toBeInTheDocument());
  });

  it("reports errors and marks a successful review stale when the editable scenario changes", async () => {
    api.review.mockResolvedValueOnce(handReviewResponseFixture()).mockRejectedValueOnce(new Error("review unavailable"));
    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: "生成整手复盘（页面入口）" }));
    await screen.findByText("整手需要优先复盘翻牌圈行动。");
    fireEvent.click(screen.getByRole("button", { name: "修改场景" }));
    expect(screen.getByText(/场景已变化；以下整手复盘已过期/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "生成整手复盘（页面入口）" }));
    expect(await screen.findByText("review unavailable")).toBeInTheDocument();
  });

  it("keeps a completed hand reviewable and navigates a review card to its actionId timeline row", async () => {
    api.review.mockResolvedValueOnce(handReviewResponseFixture());
    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: "载入已完成手牌" }));
    fireEvent.click(screen.getByRole("button", { name: "生成整手复盘（页面入口）" }));
    await screen.findByText("Raise to 250");
    fireEvent.click(screen.getByLabelText("决策卡 a1"));

    await waitFor(() => expect(document.getElementById("action-timeline-a1")).toHaveClass("selected"));
  });
});
