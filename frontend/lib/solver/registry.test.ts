import { describe, expect, it } from "vitest";

import type { SolveJob } from "../../types/api";
import {
  emptySolveJobRegistry,
  selectedSolveJob,
  solveJobRegistryReducer,
} from "./registry";

function job(jobId: string, status = "queued", scenarioFingerprint = `scenario-${jobId}`): SolveJob {
  return {
    jobId,
    status,
    provenance: {
      scenarioFingerprint,
      spotFingerprint: `spot-${jobId}`,
      decisionSequence: 4,
      policySequence: 4,
      actorSeat: 1,
      activeSeats: [0, 1],
      street: "flop",
    },
  };
}

describe("solve job registry", () => {
  it("keeps submitted jobs isolated by actionId", () => {
    const first = solveJobRegistryReducer(emptySolveJobRegistry, {
      type: "submitted",
      actionId: "check-5",
      decisionSequence: 4,
      actorSeat: 1,
      projectionFingerprint: "projection-check-5",
      job: job("job-check"),
    });
    const registry = solveJobRegistryReducer(first, {
      type: "submitted",
      actionId: "bet-8",
      decisionSequence: 7,
      actorSeat: 0,
      projectionFingerprint: "projection-bet-8",
      job: {
        ...job("job-bet"),
        provenance: { ...job("job-bet").provenance!, decisionSequence: 7, policySequence: 7, actorSeat: 0 },
      },
    });

    expect(registry["check-5"]?.job.jobId).toBe("job-check");
    expect(registry["bet-8"]?.job.jobId).toBe("job-bet");
  });

  it("projects the completed job for a selected action without restarting it", () => {
    const submitted = solveJobRegistryReducer(emptySolveJobRegistry, {
      type: "submitted",
      actionId: "check-5",
      decisionSequence: 4,
      actorSeat: 1,
      projectionFingerprint: "projection-check-5",
      job: job("job-check"),
    });
    const registry = solveJobRegistryReducer(submitted, {
      type: "polled",
      actionId: "check-5",
      job: job("job-check", "solved"),
    });

    expect(selectedSolveJob(registry, "check-5", "projection-check-5")?.status).toBe("solved");
    expect(selectedSolveJob(registry, "bet-8", "projection-bet-8")).toBeNull();
  });

  it("cancels only the selected action's job", () => {
    const registry = solveJobRegistryReducer(
      solveJobRegistryReducer(emptySolveJobRegistry, {
        type: "submitted",
        actionId: "check-5",
        decisionSequence: 4,
        actorSeat: 1,
        projectionFingerprint: "projection-check-5",
        job: job("job-check"),
      }),
      {
        type: "submitted",
        actionId: "bet-8",
        decisionSequence: 7,
        actorSeat: 0,
        projectionFingerprint: "projection-bet-8",
        job: {
          ...job("job-bet"),
          provenance: { ...job("job-bet").provenance!, decisionSequence: 7, policySequence: 7, actorSeat: 0 },
        },
      },
    );
    const cancelled = solveJobRegistryReducer(registry, {
      type: "cancelled",
      actionId: "check-5",
      status: "cancellation_requested",
    });

    expect(cancelled["check-5"]?.job.status).toBe("cancellation_requested");
    expect(cancelled["bet-8"]?.job.status).toBe("queued");
  });

  it("has no job until the user explicitly submits the selected action", () => {
    expect(selectedSolveJob(emptySolveJobRegistry, "check-5", "projection-check-5")).toBeNull();
  });

  it("marks only incompatible action projections stale after a scenario change", () => {
    const registry = solveJobRegistryReducer(
      solveJobRegistryReducer(emptySolveJobRegistry, {
        type: "submitted",
        actionId: "check-5",
        decisionSequence: 4,
        actorSeat: 1,
        projectionFingerprint: "stable-projection",
        job: job("job-check"),
      }),
      {
        type: "submitted",
        actionId: "bet-8",
        decisionSequence: 7,
        actorSeat: 0,
        projectionFingerprint: "changed-projection",
        job: {
          ...job("job-bet"),
          provenance: { ...job("job-bet").provenance!, decisionSequence: 7, policySequence: 7, actorSeat: 0 },
        },
      },
    );

    const reconciled = solveJobRegistryReducer(registry, {
      type: "reconcile",
      actions: {
        "check-5": { decisionSequence: 4, actorSeat: 1, projectionFingerprint: "stable-projection" },
        "bet-8": { decisionSequence: 7, actorSeat: 0, projectionFingerprint: "new-projection" },
      },
    });

    expect(reconciled["check-5"]?.stale).toBe(false);
    expect(reconciled["bet-8"]?.stale).toBe(true);
    expect(selectedSolveJob(reconciled, "bet-8", "new-projection")).toBeNull();
  });
});
