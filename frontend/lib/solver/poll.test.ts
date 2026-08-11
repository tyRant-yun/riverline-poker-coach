import { describe, expect, it } from "vitest";

import { applySolvePoll } from "./poll";
import type { SolveJob } from "../../types/api";

const SPOT = {
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
  assumptions: ["bunching_ignored"],
};

const RESULT: SolveJob["result"] = {
  metadata: {
    solver: "postflop-solver",
    version: "1",
    street: "flop",
    exploitabilityChips: 0.004,
    targetExploitabilityChips: 0.005,
    solveTimeMs: 1200,
    maxIterations: 400,
    memoryUsageGb: 0.2,
    memoryUsageCompressedGb: 0.1,
    compressed: false,
  },
  root: {
    actions: ["check", "bet50"],
    player: 0,
    hands: [{ combo: "AsKs", weight: 1, equity: 0.6, ev: 12.4, strategy: { check: 0.7, bet50: 0.3 } }],
  },
};

describe("applySolvePoll", () => {
  it("preserves the spot metadata across the queued -> running -> solved lifecycle", () => {
    const submitted: SolveJob = { jobId: "j1", status: "queued", spot: SPOT };

    const queued = applySolvePoll(submitted, {
      jobId: "j1",
      status: "queued",
      executionMs: 10,
    });
    const running = applySolvePoll(queued, {
      jobId: "j1",
      status: "running",
      executionMs: 4200,
    });
    const solved = applySolvePoll(running, {
      jobId: "j1",
      status: "solved",
      executionMs: 9100,
      result: RESULT,
    });

    expect(solved.spot?.assumptions).toEqual(["bunching_ignored"]);
    expect(solved.status).toBe("solved");
    expect(solved.executionMs).toBe(9100);
    expect(solved.result?.metadata?.solver).toBe("postflop-solver");
  });

  it("keeps the spot even when a poll response omits it entirely", () => {
    const submitted: SolveJob = { jobId: "j2", status: "queued", spot: SPOT };
    const next = applySolvePoll(submitted, { jobId: "j2", status: "running" });
    expect(next.spot).toEqual(SPOT);
  });

  it("works from a null previous job (defensive)", () => {
    const next = applySolvePoll(null, { jobId: "j3", status: "queued" });
    expect(next).toEqual({ jobId: "j3", status: "queued", spot: undefined });
  });

  it("keeps a newly solved result usable even when the initial closure had no job", () => {
    const next = applySolvePoll(null, {
      jobId: "j4",
      status: "solved",
      result: RESULT,
    });
    expect(next.jobId).toBe("j4");
    expect(next.result).toBe(RESULT);
  });
});
