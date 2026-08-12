import { describe, expect, it } from "vitest";

import {
  deadCardsForSeat,
  getKnownCardsForSeat,
  getRangeForSeat,
  syncSeatSourcesFromLegacy,
} from "./scenario";
import type { Scenario } from "../../types/scenario";

function makeScenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    schemaVersion: 2,
    gameVariant: "nlhe",
    tableSize: 6,
    smallBlind: 50,
    bigBlind: 100,
    buttonSeat: 0,
    heroSeat: 0,
    seats: [0, 1, 2, 3, 4, 5].map((seatId) => ({
      seatId,
      startingStack: 10000,
      position: ["button", "small_blind", "big_blind", "utg", "mp", "co"][seatId],
    })),
    heroHoleCards: [],
    board: [],
    actionHistory: [],
    decisionPoint: { street: "preflop", actorSeat: 0, afterSequence: 0 },
    assumptions: {},
    ...overrides,
  };
}

describe("getKnownCardsForSeat", () => {
  it("prefers the seat-based Schema v2 source over legacy fields", () => {
    const scenario = makeScenario({
      heroHoleCards: ["As", "Kd"],
      knownHoleCardsBySeat: { "0": ["Qh", "Qc"] },
    });
    expect(getKnownCardsForSeat(scenario, 0)).toEqual(["Qh", "Qc"]);
  });

  it("reads non-hero seats from knownHoleCardsBySeat", () => {
    const scenario = makeScenario({
      knownHoleCardsBySeat: { "3": ["7c", "7h"], "5": ["2s", "2d"] },
    });
    expect(getKnownCardsForSeat(scenario, 3)).toEqual(["7c", "7h"]);
    expect(getKnownCardsForSeat(scenario, 5)).toEqual(["2s", "2d"]);
    // Unknown seats render nothing.
    expect(getKnownCardsForSeat(scenario, 1)).toEqual([]);
  });

  it("falls back to the legacy hero/villain fields in heads-up", () => {
    const scenario = makeScenario({
      tableSize: 2,
      seats: [
        { seatId: 0, startingStack: 10000, position: "button" },
        { seatId: 1, startingStack: 10000, position: "big_blind" },
      ],
      heroSeat: 0,
      heroHoleCards: ["As", "Kd"],
      villainHoleCards: ["Qh", "Jc"],
    });
    expect(getKnownCardsForSeat(scenario, 0)).toEqual(["As", "Kd"]);
    expect(getKnownCardsForSeat(scenario, 1)).toEqual(["Qh", "Jc"]);
  });

  it("ignores malformed one-card entries instead of rendering half a hand", () => {
    const scenario = makeScenario({
      heroHoleCards: ["As", "Kd"],
      knownHoleCardsBySeat: { "0": ["As"] },
    });
    // A one-card entry is invalid data; the legacy hero cards win the fallback.
    expect(getKnownCardsForSeat(scenario, 0)).toEqual(["As", "Kd"]);
  });
});

describe("deadCardsForSeat", () => {
  it("keeps the target seat's known cards available while blocking other seats", () => {
    const scenario = makeScenario({
      knownHoleCardsBySeat: {
        "0": ["As", "Ks"],
        "3": ["Qh", "Qd"],
      },
      board: ["2c"],
    });
    expect(deadCardsForSeat(scenario, 0)).toEqual(["2c", "Qh", "Qd"]);
    expect(deadCardsForSeat(scenario, 3)).toEqual(["2c", "As", "Ks"]);
  });
});

describe("getRangeForSeat", () => {
  const heroRange = {
    rangeId: "h",
    name: "hero",
    version: "1",
    source: "user_defined",
    matrix169: { "22": "1" },
  };
  const villainRange = {
    rangeId: "v",
    name: "villain",
    version: "1",
    source: "user_defined",
    matrix169: { "33": "1" },
  };

  it("prefers rangesBySeat and covers non-hero seats", () => {
    const scenario = makeScenario({
      heroRange: undefined,
      rangesBySeat: { "2": villainRange, "4": heroRange },
    });
    expect(getRangeForSeat(scenario, 2)).toEqual(villainRange);
    expect(getRangeForSeat(scenario, 4)).toEqual(heroRange);
    // No legacy fallback for seat 0 (no heroRange): seat-based source wins.
    expect(getRangeForSeat(scenario, 0)).toBeNull();
  });

  it("falls back to legacy hero/villain ranges in heads-up", () => {
    const scenario = makeScenario({
      tableSize: 2,
      seats: [
        { seatId: 0, startingStack: 10000, position: "button" },
        { seatId: 1, startingStack: 10000, position: "big_blind" },
      ],
      heroSeat: 0,
      heroRange,
      villainRange,
    });
    expect(getRangeForSeat(scenario, 0)).toEqual(heroRange);
    expect(getRangeForSeat(scenario, 1)).toEqual(villainRange);
  });
});

describe("syncSeatSourcesFromLegacy", () => {
  it("mirrors hero card edits into knownHoleCardsBySeat", () => {
    const scenario = makeScenario({ heroSeat: 4 });
    const sync = syncSeatSourcesFromLegacy(scenario, { heroHoleCards: ["As", "Kd"] });
    expect(sync.knownHoleCardsBySeat?.["4"]).toEqual(["As", "Kd"]);
  });

  it("clears the seat entry when cards are removed", () => {
    const scenario = makeScenario({
      knownHoleCardsBySeat: { "0": ["As", "Kd"] },
      heroSeat: 0,
    });
    const sync = syncSeatSourcesFromLegacy(scenario, { heroHoleCards: [] });
    expect(sync.knownHoleCardsBySeat).toEqual({});
  });

  it("mirrors villain edits onto the heads-up opponent seat", () => {
    const scenario = makeScenario({
      tableSize: 2,
      seats: [
        { seatId: 0, startingStack: 10000, position: "button" },
        { seatId: 1, startingStack: 10000, position: "big_blind" },
      ],
      heroSeat: 0,
    });
    const sync = syncSeatSourcesFromLegacy(scenario, { villainHoleCards: ["Qh", "Jc"] });
    expect(sync.knownHoleCardsBySeat?.["1"]).toEqual(["Qh", "Jc"]);
  });

  it("returns no seat sync for unrelated patches", () => {
    const scenario = makeScenario();
    const sync = syncSeatSourcesFromLegacy(scenario, { smallBlind: 75 });
    expect(sync.knownHoleCardsBySeat).toBeUndefined();
    expect(sync.rangesBySeat).toBeUndefined();
  });
});
