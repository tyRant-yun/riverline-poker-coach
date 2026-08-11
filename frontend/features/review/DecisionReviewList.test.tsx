import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DecisionReviewList from "./DecisionReviewList";
import type { DecisionReview } from "../../types/handReview";

const review = (overrides: Partial<DecisionReview> = {}): DecisionReview => ({
  actionId: "a-1",
  eventSequence: 2,
  decisionSequence: 1,
  street: "flop",
  actorSeat: 0,
  actualAction: "Bet 50",
  rangeUpdate: { status: "available", source: "solver" },
  solverAssessment: {
    status: "primary",
    actualFrequency: 0.72,
    primaryAction: "Bet 50",
    source: "grounded solver",
  },
  teaching: { summary: "这个尺寸保持了对手范围的压力。" },
  ...overrides,
});

describe("DecisionReviewList", () => {
  it("shows an honest empty state", () => {
    render(<DecisionReviewList reviews={[]} />);
    expect(screen.getByText("这手牌还没有可复盘的玩家决策。")).toBeInTheDocument();
    expect(screen.getByText("0 个决策")).toBeInTheDocument();
  });

  it("shows range available and teaching summary", () => {
    render(<DecisionReviewList reviews={[review()]} />);
    expect(screen.getByText("已更新")).toBeInTheDocument();
    expect(screen.getByText("这个尺寸保持了对手范围的压力。")).toBeInTheDocument();
    expect(screen.getByText(/实际行动频率 72%/)).toBeInTheDocument();
  });

  it("shows solver unscored without presenting it as an error", () => {
    render(
      <DecisionReviewList
        reviews={[
          review({
            rangeUpdate: { status: "unavailable", reason: "该节点没有可用策略来源。" },
            solverAssessment: { status: "unscored", reason: "尚未提交 Solver。" },
          }),
        ]}
      />,
    );
    expect(screen.getByText("不可用")).toBeInTheDocument();
    expect(screen.getByText("未进行 Solver 评分")).toBeInTheDocument();
    expect(screen.getByText("尚未提交 Solver。")).toBeInTheDocument();
    expect(screen.queryByText("明显偏离常用策略")).not.toBeInTheDocument();
  });

  it("shows a mixed solver assessment", () => {
    render(
      <DecisionReviewList
        reviews={[review({ solverAssessment: { status: "mixed", actualFrequency: "18%" } })]}
      />,
    );
    expect(screen.getByText("可接受混频")).toBeInTheDocument();
    expect(screen.getByText(/实际行动频率 18%/)).toBeInTheDocument();
  });

  it.each([
    ["rare", "明显偏离常用策略", "source-tag"],
    ["absent", "Solver 不采用该行动", "danger-button"],
  ] as const)("maps %s to a non-positive status class", (status, label, expectedClass) => {
    render(<DecisionReviewList reviews={[review({ solverAssessment: { status } })]} />);
    const badge = screen.getByText(label);

    expect(badge).toHaveClass(expectedClass);
    expect(badge).not.toHaveClass("source-tag", "green");
  });
});
