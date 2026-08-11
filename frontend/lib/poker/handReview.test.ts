import { describe, expect, it } from "vitest";

import type { Scenario } from "../../types/scenario";
import { isPlayerAction, projectSelectedDecisionScenario, reconcileSelectedActionId, selectionForAction } from "./handReview";

const events = [
  { actionId: "fold-1", sequence: 1, street: "preflop", actorSeat: 3, actionType: "fold" },
  { actionId: "deal-2", sequence: 2, street: "flop", actorSeat: 0, actionType: "deal_flop" },
  { actionId: "bet-3", sequence: 3, street: "flop", actorSeat: 1, actionType: "bet", amount: 100 },
];

describe("hand-review action selection", () => {
  it("derives both cursors from the selected player actionId", () => {
    expect(selectionForAction(events, "bet-3")).toEqual({
      actionId: "bet-3",
      actorSeat: 1,
      eventSequence: 3,
      decisionSequence: 2,
    });
  });

  it("does not turn a deal event into a solver decision", () => {
    expect(selectionForAction(events, "deal-2")).toBeNull();
  });

  it("only scores the backend's explicit player-action allowlist", () => {
    for (const actionType of ["check", "call", "bet", "raise_to", "fold", "all_in"]) {
      expect(isPlayerAction({ ...events[0], actionType })).toBe(true);
    }
    for (const actionType of ["deal_flop", "deal_turn", "deal_river", "post_blind", "showdown", "award_pot", "unknown"]) {
      expect(isPlayerAction({ ...events[0], actionType })).toBe(false);
    }
  });

  it("clears a selection that disappeared after undo, load, or reset", () => {
    expect(reconcileSelectedActionId(events.slice(0, 1), "bet-3")).toBeNull();
    expect(reconcileSelectedActionId(events, "bet-3")).toBe("bet-3");
  });

  it("projects a selected historical action to its action-before analysis and legal-state scenario", () => {
    const scenario: Scenario = {
      schemaVersion: 1,
      gameVariant: "nlhe",
      tableSize: 2,
      smallBlind: 50,
      bigBlind: 100,
      buttonSeat: 0,
      heroSeat: 0,
      seats: [
        { seatId: 0, startingStack: 10_000, position: "button" },
        { seatId: 1, startingStack: 10_000, position: "big_blind" },
      ],
      heroHoleCards: ["As", "Kd"],
      villainHoleCards: ["Qh", "Jc"],
      board: ["2c", "7d", "Jh", "9s", "3h"],
      actionHistory: [
        { actionId: "call-1", sequence: 1, street: "preflop", actorSeat: 0, actionType: "call", amount: 50, amountType: "cost" },
        { actionId: "check-2", sequence: 2, street: "preflop", actorSeat: 1, actionType: "check" },
        { actionId: "deal-flop", sequence: 3, street: "flop", actorSeat: 0, actionType: "deal_flop" },
        { actionId: "check-4", sequence: 4, street: "flop", actorSeat: 1, actionType: "check" },
        { actionId: "deal-turn", sequence: 5, street: "turn", actorSeat: 0, actionType: "deal_turn" },
        { actionId: "bet-6", sequence: 6, street: "turn", actorSeat: 0, actionType: "bet", amount: 200, amountType: "by" },
        { actionId: "call-7", sequence: 7, street: "turn", actorSeat: 1, actionType: "call", amount: 200, amountType: "cost" },
        { actionId: "deal-river", sequence: 8, street: "river", actorSeat: 0, actionType: "deal_river" },
      ],
      decisionPoint: { street: "river", actorSeat: 1, afterSequence: 8 },
      assumptions: {},
    };
    const selection = selectionForAction(scenario.actionHistory, "bet-6");
    const projected = projectSelectedDecisionScenario(scenario, selection!);

    expect(projected.decisionPoint).toEqual({ street: "turn", actorSeat: 0, afterSequence: 5 });
    expect(projected.actionHistory.map((event) => event.actionId)).toEqual([
      "call-1", "check-2", "deal-flop", "check-4", "deal-turn",
    ]);
    expect(projected.board).toEqual(["2c", "7d", "Jh", "9s"]);
    expect(scenario.actionHistory).toHaveLength(8);
    expect(scenario.board).toEqual(["2c", "7d", "Jh", "9s", "3h"]);
  });
});
