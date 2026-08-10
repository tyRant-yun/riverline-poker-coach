import { describe, expect, it } from "vitest";

import { buildSeatViewModels } from "./table";
import type { FinalState } from "../../types/api";
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
    board: ["2c", "7d", "Jh"],
    actionHistory: [],
    decisionPoint: { street: "flop", actorSeat: 2, afterSequence: 0 },
    assumptions: {},
    ...overrides,
  };
}

function makeState(overrides: Partial<FinalState> = {}): FinalState {
  return {
    street: "flop",
    actorSeat: 2,
    board: ["2c", "7d", "Jh"],
    pot: 650,
    stacks: { "0": 9700, "1": 1950, "2": 9800, "3": 5000, "4": 10000, "5": 10000 },
    bets: { "0": 300, "2": 200 },
    foldedSeats: [1, 3, 4, 5],
    handInProgress: true,
    legalActions: {
      actorSeat: 2,
      actions: ["check", "bet", "all_in", "fold"],
      callAmount: null,
      minRaiseTo: null,
      maxRaiseTo: null,
      explanations: {},
    },
    ...overrides,
  };
}

describe("buildSeatViewModels", () => {
  it("marks folded seats from the backend foldedSeats and keeps others active", () => {
    const seats = buildSeatViewModels(makeScenario(), makeState());
    const byId = new Map(seats.map((seat) => [seat.seatId, seat]));
    expect(byId.get(1)?.isFolded).toBe(true);
    expect(byId.get(1)?.isActive).toBe(false);
    expect(byId.get(4)?.isFolded).toBe(true);
    expect(byId.get(4)?.isActive).toBe(false);
    // Live seats stay active even when they are not the current actor.
    expect(byId.get(0)?.isActive).toBe(true);
    expect(byId.get(2)?.isActive).toBe(true);
  });

  it("keeps isActor separate from isActive", () => {
    const seats = buildSeatViewModels(makeScenario(), makeState());
    const byId = new Map(seats.map((seat) => [seat.seatId, seat]));
    // Seat 2 is the current actor and live -> both flags set.
    expect(byId.get(2)?.isActor).toBe(true);
    expect(byId.get(2)?.isActive).toBe(true);
    // A live non-actor is active but not the actor.
    expect(byId.get(0)?.isActor).toBe(false);
    expect(byId.get(0)?.isActive).toBe(true);
  });

  it("falls back to all-active when the state has not loaded", () => {
    const seats = buildSeatViewModels(makeScenario(), null);
    expect(seats.every((seat) => seat.isActive && !seat.isFolded)).toBe(true);
  });

  it("reads each seat's cards from knownHoleCardsBySeat", () => {
    const scenario = makeScenario({
      knownHoleCardsBySeat: { "0": ["As", "Kd"], "3": ["7c", "7h"] },
    });
    const seats = buildSeatViewModels(scenario, null);
    const byId = new Map(seats.map((seat) => [seat.seatId, seat]));
    expect(byId.get(0)?.cards.map((card) => card?.rank)).toEqual(["A", "K"]);
    expect(byId.get(3)?.cards.map((card) => card?.rank)).toEqual(["7", "7"]);
    expect(byId.get(1)?.cards).toHaveLength(0);
  });
});
