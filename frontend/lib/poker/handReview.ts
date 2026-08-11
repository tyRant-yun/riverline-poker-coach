import type { ActionEvent, Scenario } from "../../types/scenario";

const PLAYER_ACTION_TYPES = new Set(["check", "call", "bet", "raise_to", "fold", "all_in"]);

/** A real player action has an action-before and action-after cursor. */
export type ActionSelection = {
  actionId: string;
  actorSeat: number;
  eventSequence: number;
  decisionSequence: number;
};

export function isPlayerAction(event: ActionEvent): boolean {
  return PLAYER_ACTION_TYPES.has(event.actionType);
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

/**
 * A read-only decision-node projection for the lower workspace. It retains
 * only the replay events already known before the selected action and trims
 * the board to cards that have been dealt by then. The editable ScenarioSpec
 * is never mutated or replaced by this value.
 */
export function projectSelectedDecisionScenario(
  scenario: Scenario,
  selection: ActionSelection,
): Scenario {
  const actionHistory = scenario.actionHistory.filter(
    (event) => event.sequence <= selection.decisionSequence,
  );
  const visibleBoardLength = actionHistory.reduce((length, event) => {
    if (event.actionType === "deal_flop") return Math.max(length, 3);
    if (event.actionType === "deal_turn") return Math.max(length, 4);
    if (event.actionType === "deal_river") return Math.max(length, 5);
    return length;
  }, 0);

  const selectedEvent = scenario.actionHistory.find((event) => event.actionId === selection.actionId);
  if (!selectedEvent) return scenario;

  return {
    ...scenario,
    board: scenario.board.slice(0, visibleBoardLength),
    actionHistory,
    decisionPoint: {
      street: selectedEvent.street,
      actorSeat: selectedEvent.actorSeat,
      afterSequence: selection.decisionSequence,
    },
  };
}
