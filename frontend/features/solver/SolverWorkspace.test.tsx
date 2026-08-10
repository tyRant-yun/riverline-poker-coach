import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import SolverWorkspace from "./SolverWorkspace";
import type { SolveJob } from "../../types/api";

function makeSpot() {
  return {
    schemaVersion: 1,
    street: "flop",
    board: ["2c", "7d", "Jh"],
    turn: null,
    river: null,
    oopRange: "22:1",
    ipRange: "99:1",
    startingPot: 650,
    effectiveStack: 7700,
    rakeRate: 0,
    rakeCap: 0,
    betSizes: "50%, e, a",
    raiseSizes: "2.5x",
    maxIterations: 200,
    targetExploitabilityFrac: 0.005,
  };
}

describe("SolverWorkspace assumptions", () => {
  it("surfaces the bunching_ignored approximation from the spot", () => {
    const solveJob: SolveJob = {
      jobId: "j1",
      status: "queued",
      spot: { ...makeSpot(), assumptions: ["bunching_ignored"] },
    };
    render(
      <SolverWorkspace
        solveJob={solveJob}
        canSubmit={false}
        heroHoleCards={[]}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText(/bunching_ignored/)).toBeInTheDocument();
    expect(screen.getByText(/已弃牌玩家的手牌对剩余牌堆的影响被忽略/)).toBeInTheDocument();
  });

  it("shows no assumption note when the spot has none", () => {
    const solveJob: SolveJob = {
      jobId: "j2",
      status: "queued",
      spot: { ...makeSpot(), assumptions: [] },
    };
    render(
      <SolverWorkspace
        solveJob={solveJob}
        canSubmit={false}
        heroHoleCards={[]}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByText(/bunching_ignored/)).not.toBeInTheDocument();
  });
});
