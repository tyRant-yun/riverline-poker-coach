// Solver jobs belong to action-before decision nodes, not to the whole hand.
// The registry retains completed jobs while the user moves through the
// timeline, and marks a job stale when the node it was submitted for no
// longer matches the current action-before projection.

import type { SolveJob } from "../../types/api";
import { applySolvePoll, type SolvePollPayload } from "./poll";

export type SolveJobNode = {
  decisionSequence: number;
  actorSeat: number;
  projectionFingerprint: string;
};

export type SolveJobState = SolveJobNode & {
  actionId: string;
  job: SolveJob;
  scenarioFingerprint: string | null;
  spotFingerprint: string | null;
  stale: boolean;
};

export type SolveJobRegistry = Record<string, SolveJobState>;

export const emptySolveJobRegistry: SolveJobRegistry = {};

export type SolveJobRegistryAction =
  | ({ type: "submitted"; actionId: string; job: SolveJob } & SolveJobNode)
  | { type: "polled"; actionId: string; job: SolvePollPayload }
  | { type: "cancelled"; actionId: string; status: string }
  | { type: "reconcile"; actions: Record<string, SolveJobNode> };

function provenanceFor(job: SolveJob) {
  return job.provenance ?? {
    scenarioFingerprint: job.scenarioFingerprint ?? null,
    spotFingerprint: job.spotFingerprint ?? null,
    decisionSequence: job.policySequence ?? null,
    actorSeat: job.actorSeat ?? null,
  };
}

function matchesNode(entry: SolveJobState, node: SolveJobNode | undefined): boolean {
  if (!node) return false;
  const provenance = provenanceFor(entry.job);
  return (
    entry.decisionSequence === node.decisionSequence &&
    entry.actorSeat === node.actorSeat &&
    entry.projectionFingerprint === node.projectionFingerprint &&
    (provenance.decisionSequence == null || provenance.decisionSequence === node.decisionSequence) &&
    (provenance.actorSeat == null || provenance.actorSeat === node.actorSeat) &&
    (!entry.scenarioFingerprint || provenance.scenarioFingerprint === entry.scenarioFingerprint) &&
    (!entry.spotFingerprint || provenance.spotFingerprint === entry.spotFingerprint)
  );
}

export function solveJobRegistryReducer(
  registry: SolveJobRegistry,
  action: SolveJobRegistryAction,
): SolveJobRegistry {
  if (action.type === "submitted") {
    const provenance = provenanceFor(action.job);
    return {
      ...registry,
      [action.actionId]: {
        actionId: action.actionId,
        decisionSequence: action.decisionSequence,
        actorSeat: action.actorSeat,
        projectionFingerprint: action.projectionFingerprint,
        job: action.job,
        scenarioFingerprint: provenance.scenarioFingerprint ?? null,
        spotFingerprint: provenance.spotFingerprint ?? null,
        stale: false,
      },
    };
  }

  if (action.type === "reconcile") {
    let changed = false;
    const reconciled: SolveJobRegistry = {};
    for (const [actionId, current] of Object.entries(registry)) {
      const stale = !matchesNode(current, action.actions[actionId]);
      reconciled[actionId] = stale === current.stale ? current : { ...current, stale };
      changed ||= stale !== current.stale;
    }
    return changed ? reconciled : registry;
  }

  const entry = registry[action.actionId];
  if (!entry) return registry;

  if (action.type === "polled") {
    const job = applySolvePoll(entry.job, action.job);
    return { ...registry, [action.actionId]: { ...entry, job } };
  }

  return { ...registry, [action.actionId]: { ...entry, job: { ...entry.job, status: action.status } } };
}

/** The current workspace may only consume a compatible, non-stale node job. */
export function selectedSolveJob(
  registry: SolveJobRegistry,
  actionId: string | null,
  projectionFingerprint: string | null,
): SolveJob | null {
  if (!actionId || !projectionFingerprint) return null;
  const entry = registry[actionId];
  if (!entry || entry.stale || entry.projectionFingerprint !== projectionFingerprint) return null;
  return entry.job;
}

/** Stable enough for local projection identity; not a substitute for backend provenance hashes. */
export function projectionFingerprint(value: unknown): string {
  return JSON.stringify(value, (_key, candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return candidate;
    return Object.keys(candidate as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((sorted, key) => {
        sorted[key] = (candidate as Record<string, unknown>)[key];
        return sorted;
      }, {});
  });
}
