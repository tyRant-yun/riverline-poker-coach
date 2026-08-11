import type { ActionEvent } from "../../types/scenario";

/** A real player action has an action-before and action-after cursor. */
export type ActionSelection = {
  actionId: string;
  actorSeat: number;
  eventSequence: number;
  decisionSequence: number;
};

export function isPlayerAction(event: ActionEvent): boolean {
  return !event.actionType.startsWith("deal_");
}

/**
 * The action id is the durable selection key. Sequences are derived only
 * after finding that action in the current ScenarioSpec.
 */
export function selectionForAction(
  events: ActionEvent[],
  actionId: string | null,
): ActionSelection | null {
  if (!actionId) return null;
  const event = events.find((candidate) => candidate.actionId === actionId);
  if (!event || !isPlayerAction(event)) return null;
  return {
    actionId: event.actionId,
    actorSeat: event.actorSeat,
    eventSequence: event.sequence,
    decisionSequence: event.sequence - 1,
  };
}

/** Keep the id only while it still names a player action in this history. */
export function reconcileSelectedActionId(
  events: ActionEvent[],
  actionId: string | null,
): string | null {
  return selectionForAction(events, actionId)?.actionId ?? null;
}
