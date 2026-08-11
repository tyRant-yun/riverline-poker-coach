// Solve job polling merge. The submit response carries the SolverSpot
// (spot.assumptions -> bunching_ignored hint); every later poll response
// only carries status/error/executionMs/result. Merging instead of
// replacing keeps the spot metadata alive for the whole job lifetime.

import type { SolveJob } from "../../types/api";

export type SolvePollPayload = {
  jobId: string;
  status: string;
  error?: string | null;
  executionMs?: number | null;
  spot?: SolveJob["spot"];
  provenance?: SolveJob["provenance"];
  result?: SolveJob["result"] | null;
};

export function applySolvePoll(
  previous: SolveJob | null,
  payload: SolvePollPayload,
): SolveJob {
  const next = { ...(previous ?? { jobId: payload.jobId, status: payload.status }), ...payload };
  if (payload.spot === undefined && previous?.spot !== undefined) next.spot = previous.spot;
  if (payload.provenance === undefined && previous?.provenance !== undefined) {
    next.provenance = previous.provenance;
  }
  return next;
}
