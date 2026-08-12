import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DecisionReviewCard from "../review/DecisionReviewCard";
import SolverAssessment from "./SolverAssessment";
import type { DecisionReview, ReviewSolverAssessment } from "../../types/handReview";

const assessment: ReviewSolverAssessment = {
  status: "mixed",
  actualFrequency: 0.18,
  primaryAction: "Check",
  source: "solver",
  confidence: "grounded",
  thresholdMetadata: { mixedThreshold: 0.05, kind: "product_interpretation" },
};

const review: DecisionReview = {
  actionId: "a-1",
  eventSequence: 2,
  decisionSequence: 1,
  street: "flop",
  actorSeat: 0,
  actualAction: "Bet 50",
  rangeUpdate: { status: "unavailable", reason: "no range" },
  solverAssessment: assessment,
};

describe("SolverAssessment", () => {
  it("uses the same status wording in the decision card and Solver workspace", () => {
    render(
      <>
        <DecisionReviewCard review={review} />
        <SolverAssessment assessment={assessment} />
      </>,
    );

    expect(screen.getAllByText("可接受混频")).toHaveLength(2);
    expect(screen.getAllByText(/实际行动频率 18%/)).toHaveLength(2);
    expect(screen.getAllByText(/来源：solver · 置信度：grounded/)).toHaveLength(2);
  });

  it("keeps absent and unscored explanations distinct from EV loss", () => {
    const { rerender } = render(<SolverAssessment assessment={{ status: "absent" }} />);
    expect(screen.getByText("Solver 不采用该行动")).toBeInTheDocument();
    expect(screen.queryByText(/EV loss|EV损失/)).not.toBeInTheDocument();

    rerender(<SolverAssessment assessment={{ status: "unscored", reason: "尚未提交 Solver。" }} />);
    expect(screen.getByText("无 Solver 结论")).toBeInTheDocument();
    expect(screen.getByText("尚未提交 Solver。")).toBeInTheDocument();
    expect(screen.queryByText("Solver 不采用该行动")).not.toBeInTheDocument();
  });
});
