import { describe, expect, it } from "vitest";

import { selectionForAction, reconcileSelectedActionId } from "./handReview";

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

  it("clears a selection that disappeared after undo, load, or reset", () => {
    expect(reconcileSelectedActionId(events.slice(0, 1), "bet-3")).toBeNull();
    expect(reconcileSelectedActionId(events, "bet-3")).toBe("bet-3");
  });
});
