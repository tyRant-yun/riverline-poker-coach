import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WholeHandReviewState } from "../../lib/poker/wholeHandReview";
import { handReviewResponseFixture } from "../../test/handReviewFixtures";
import { adaptHandReviewResponse } from "../../lib/api/handReviewAdapter";
import WholeHandReviewPanel from "./WholeHandReviewPanel";

const successState: WholeHandReviewState = {
  status: "success",
  review: adaptHandReviewResponse(handReviewResponseFixture()),
  error: null,
};

describe("WholeHandReviewPanel", () => {
  it("renders backend summary, partial Solver/principle-only decision teaching, findings, and uncertainty", () => {
    render(<WholeHandReviewPanel state={successState} busy={false} onGenerate={vi.fn()} onNavigate={vi.fn()} />);

    expect(screen.getByText("整手需要优先复盘翻牌圈行动。")).toBeInTheDocument();
    expect(screen.getByText("翻牌圈行动值得优先复盘。")).toBeInTheDocument();
    expect(screen.getByText("基于本节点证据给出原则性说明。")).toBeInTheDocument();
    expect(screen.getByText(/教学模式：原则性说明/)).toBeInTheDocument();
    expect(screen.getAllByText("solver assessment is not available")).not.toHaveLength(0);
  });

  it("navigates from both a priority finding and a decision card by actionId", () => {
    const onNavigate = vi.fn();
    render(<WholeHandReviewPanel state={successState} busy={false} onGenerate={vi.fn()} onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: /翻牌圈行动值得优先复盘/ }));
    fireEvent.click(screen.getByLabelText("决策卡 a1"));
    expect(onNavigate).toHaveBeenNthCalledWith(1, "a1");
    expect(onNavigate).toHaveBeenNthCalledWith(2, "a1");
  });

  it("keeps completed empty hands useful and makes stale/error state explicit", () => {
    const empty = {
      ...successState,
      review: { ...successState.review!, decisionReviews: [], priorityFindings: [], wholeHandSummary: null },
    };
    const { rerender } = render(<WholeHandReviewPanel state={empty} busy={false} onGenerate={vi.fn()} onNavigate={vi.fn()} />);
    expect(screen.getByText("这手牌还没有可复盘的玩家决策。")).toBeInTheDocument();

    rerender(<WholeHandReviewPanel state={{ ...empty, status: "stale" }} busy={false} onGenerate={vi.fn()} onNavigate={vi.fn()} />);
    expect(screen.getByText(/场景已变化；以下整手复盘已过期/)).toBeInTheDocument();

    rerender(<WholeHandReviewPanel state={{ ...empty, status: "error", error: "request failed" }} busy={false} onGenerate={vi.fn()} onNavigate={vi.fn()} />);
    expect(screen.getByText("request failed")).toBeInTheDocument();
  });
});
