import { describe, expect, it } from "vitest";
import {
  ACTIVE_SOLVE_STATUSES,
  SOLVE_STATUS_META,
  solveStatus,
  TERMINAL_SOLVE_STATUSES,
} from "./status";

describe("solver status machine", () => {
  it("maps backend statuses to the frontend status set", () => {
    expect(solveStatus("queued")).toBe("queued");
    expect(solveStatus("running")).toBe("running");
    expect(solveStatus("cancellation_requested")).toBe("cancellation_requested");
    expect(solveStatus("cancelled")).toBe("cancelled");
    expect(solveStatus("solved")).toBe("solved");
    expect(solveStatus("failed")).toBe("failed");
  });

  it("treats missing status as idle", () => {
    expect(solveStatus(undefined)).toBe("idle");
    expect(solveStatus(null)).toBe("idle");
    expect(solveStatus("")).toBe("idle");
  });

  it("falls back to failed for unknown statuses", () => {
    expect(solveStatus("weird")).toBe("failed");
  });

  it("exposes active and terminal status sets for cancel/poll logic", () => {
    expect(ACTIVE_SOLVE_STATUSES.has("queued")).toBe(true);
    expect(ACTIVE_SOLVE_STATUSES.has("running")).toBe(true);
    expect(ACTIVE_SOLVE_STATUSES.has("cancellation_requested")).toBe(true);
    expect(TERMINAL_SOLVE_STATUSES.has("solved")).toBe(true);
    expect(TERMINAL_SOLVE_STATUSES.has("failed")).toBe(true);
    expect(TERMINAL_SOLVE_STATUSES.has("cancelled")).toBe(true);
  });

  it("provides a display label + tone for every status", () => {
    for (const status of Object.keys(SOLVE_STATUS_META)) {
      const meta = SOLVE_STATUS_META[status as keyof typeof SOLVE_STATUS_META];
      expect(meta.label.length).toBeGreaterThan(0);
      expect(["neutral", "active", "success", "danger", "warning"]).toContain(meta.tone);
    }
  });
});
