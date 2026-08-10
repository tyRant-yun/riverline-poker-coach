import { describe, expect, it } from "vitest";

import { canSubmitSolve } from "./solve";
import type { FinalState } from "../../types/api";
import type { Scenario } from "../../types/scenario";

const HERO_RANGE = {
  rangeId: "h",
  name: "hero",
  version: "1",
  source: "user_defined",
  matrix169: { "22": "1" },
};
const VILLAIN_RANGE = {
  rangeId: "v",
  name: "villain",
  version: "1",
  source: "user_defined",
  matrix169: { "33": "1" },
};

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
    board: ["2c", "7d", "Jh"],
    actionHistory: [],
    decisionPoint: { street: "flop", actorSeat: 2, afterSequence: 0 },
    assumptions: {},
    ...overrides,
  };
}

function makeState(foldedSeats: number[]): FinalState {
  return {
    street: "flop",
    actorSeat: 2,
    board: ["2c", "7d", "Jh"],
    pot: 650,
    stacks: { "0": 9700, "1": 1950, "2": 9800 },
    bets: {},
    foldedSeats,
    handInProgress: true,
    legalActions: {
      actorSeat: 2,
      actions: ["check", "bet", "all_in", "fold"],
      callAmount: null,
      minRaiseTo: null,
      maxRaiseTo: null,
      explanations: {},
    },
  };
}

describe("canSubmitSolve", () => {
  it("rejects preflop decision points even with ranges present", () => {
    const scenario = makeScenario({ heroRange: HERO_RANGE, villainRange: VILLAIN_RANGE });
    expect(canSubmitSolve(scenario, null, "preflop", false)).toBe(false);
  });

  it("allows a postflop HU legacy spot with hero/villain ranges", () => {
    const scenario = makeScenario({
      tableSize: 2,
      heroSeat: 0,
      seats: [
        { seatId: 0, startingStack: 10000, position: "button" },
        { seatId: 1, startingStack: 10000, position: "big_blind" },
      ],
      heroRange: HERO_RANGE,
      villainRange: VILLAIN_RANGE,
    });
    // State not loaded yet: both HU seats count as active.
    expect(canSubmitSolve(scenario, null, "flop", false)).toBe(true);
  });

  it("allows a Schema v2 spot whose two active seats have rangesBySeat", () => {
    const scenario = makeScenario({
      rangesBySeat: { "0": HERO_RANGE, "2": VILLAIN_RANGE },
    });
    // Actives are seats 0 and 2 (folded: 1,3,4,5).
    const state = makeState([1, 3, 4, 5]);
    expect(canSubmitSolve(scenario, state, "flop", false)).toBe(true);
  });

  it("rejects when more than two players remain active", () => {
    const scenario = makeScenario({
      rangesBySeat: { "0": HERO_RANGE, "2": VILLAIN_RANGE, "4": HERO_RANGE },
    });
    const state = makeState([1, 3]);
    expect(canSubmitSolve(scenario, state, "flop", false)).toBe(false);
  });

  it("rejects when an active seat has no range", () => {
    const scenario = makeScenario({
      rangesBySeat: { "0": HERO_RANGE },
    });
    // Actives are seats 0 and 2; seat 2 has no range.
    const state = makeState([1, 3, 4, 5]);
    expect(canSubmitSolve(scenario, state, "flop", false)).toBe(false);
  });

  it("rejects while busy", () => {
    const scenario = makeScenario({ heroRange: HERO_RANGE, villainRange: VILLAIN_RANGE });
    expect(canSubmitSolve(scenario, null, "flop", true)).toBe(false);
  });
});
