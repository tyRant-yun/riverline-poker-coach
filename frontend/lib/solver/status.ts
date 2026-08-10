// Solver job status machine (mirrors the backend queue lifecycle:
// queued -> running -> solved | failed | cancelled, with the transient
// cancellation_requested state). "idle" is a frontend-only state meaning
// no job has been submitted yet. The frontend never derives status.

export type SolveStatus =
  | "idle"
  | "queued"
  | "running"
  | "cancellation_requested"
  | "cancelled"
  | "solved"
  | "failed";

export type StatusTone = "neutral" | "active" | "success" | "danger" | "warning";

export const SOLVE_STATUS_META: Record<SolveStatus, { label: string; tone: StatusTone }> = {
  idle: { label: "idle", tone: "neutral" },
  queued: { label: "queued", tone: "active" },
  running: { label: "running", tone: "active" },
  cancellation_requested: { label: "cancelling…", tone: "warning" },
  cancelled: { label: "cancelled", tone: "warning" },
  solved: { label: "solved", tone: "success" },
  failed: { label: "failed", tone: "danger" },
};

export function solveStatus(status: string | undefined | null): SolveStatus {
  if (!status) return "idle";
  return (Object.prototype.hasOwnProperty.call(SOLVE_STATUS_META, status) ? status : "failed") as SolveStatus;
}

export const ACTIVE_SOLVE_STATUSES: ReadonlySet<string> = new Set([
  "queued",
  "running",
  "cancellation_requested",
]);

export const TERMINAL_SOLVE_STATUSES: ReadonlySet<string> = new Set([
  "solved",
  "failed",
  "cancelled",
]);
