import { describe, expect, it } from "vitest";

import {
  changeButtonSeat,
  changeHeroSeat,
  resizeTable,
} from "./scenarioTopology";
import type { Scenario } from "../../types/scenario";

function scenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    schemaVersion: 2,
    gameVariant: "nlhe",
    tableSize: 6,
    smallBlind: 50,
    bigBlind: 100,
    buttonSeat: 0,
    heroSeat: 0,
    seats: [0, 1, 2, 3, 4, 5].map((seatId, index) => ({
      seatId,
      startingStack: 10_000 + index,
      position: ["button", "small_blind", "big_blind", "utg", "mp", "co"][index],
    })),
    heroHoleCards: ["As", "Kd"],
    board: [],
    actionHistory: [{ actionId: "open", sequence: 1, street: "preflop", actorSeat: 3, actionType: "raise_to", amount: 250, amountType: "to" }],
    decisionPoint: { street: "preflop", actorSeat: 4, afterSequence: 1 },
    assumptions: {},
    knownHoleCardsBySeat: { "0": ["As", "Kd"], "4": ["Qh", "Qc"] },
    rangesBySeat: {
      "0": { rangeId: "zero", name: "Zero", version: "1", source: "user_defined", matrix169: { "AKs": "1" } },
      "4": { rangeId: "four", name: "Four", version: "1", source: "user_defined", matrix169: { "QQ": "1" } },
    },
    ...overrides,
  };
}

describe("scenario topology transitions", () => {
  it("resizes to continuous seats, preserves compatible seat sources, and invalidates history", () => {
    const next = resizeTable(scenario(), 8);

    expect(next.seats.map((seat) => seat.seatId)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(next.seats.map((seat) => seat.position)).toEqual([
      "button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co",
    ]);
    expect(next.seats[4].startingStack).toBe(10_004);
    expect(next.seats[7].startingStack).toBe(10_000);
    expect(next.knownHoleCardsBySeat).toEqual({ "0": ["As", "Kd"], "4": ["Qh", "Qc"] });
    expect(next.rangesBySeat?.["4"]?.name).toBe("Four");
    expect(next.actionHistory).toEqual([]);
    expect(next.decisionPoint).toEqual({ street: "preflop", actorSeat: 3, afterSequence: 0 });
  });

  it("rederives every position and invalidates history when the button moves", () => {
    const next = changeButtonSeat(scenario(), 4);

    expect(next.seats.map((seat) => seat.position)).toEqual([
      "big_blind", "utg", "mp", "co", "button", "small_blind",
    ]);
    expect(next.actionHistory).toEqual([]);
    expect(next.decisionPoint.actorSeat).toBe(1);
  });

  it("changes the hero viewpoint without dropping known cards or ranges", () => {
    const next = changeHeroSeat(scenario(), 4);

    expect(next.heroSeat).toBe(4);
    expect(next.heroHoleCards).toEqual(["Qh", "Qc"]);
    expect(next.knownHoleCardsBySeat).toEqual({ "0": ["As", "Kd"], "4": ["Qh", "Qc"] });
    expect(next.rangesBySeat?.["0"]?.name).toBe("Zero");
    expect(next.actionHistory).toHaveLength(1);
  });

  it("promotes legacy HU cards and ranges before expanding the table", () => {
    const legacy = scenario({
      schemaVersion: 1,
      tableSize: 2,
      seats: [
        { seatId: 0, startingStack: 10_000, position: "button" },
        { seatId: 1, startingStack: 10_000, position: "big_blind" },
      ],
      heroRange: { rangeId: "hero", name: "Hero", version: "1", source: "user_defined", matrix169: { "AKs": "1" } },
      villainHoleCards: ["Jh", "Jc"],
      villainRange: { rangeId: "villain", name: "Villain", version: "1", source: "user_defined", matrix169: { "JJ": "1" } },
      knownHoleCardsBySeat: undefined,
      rangesBySeat: undefined,
    });

    const next = resizeTable(legacy, 6);

    expect(next.knownHoleCardsBySeat).toEqual({ "0": ["As", "Kd"], "1": ["Jh", "Jc"] });
    expect(next.rangesBySeat?.["0"]?.name).toBe("Hero");
    expect(next.rangesBySeat?.["1"]?.name).toBe("Villain");
  });
});
