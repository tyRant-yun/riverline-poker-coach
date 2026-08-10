// Test fixtures: seat view models (2/6/8-max) and a small solver node.
// These are pure frontend fixtures — the production backend still only
// accepts HU scenarios.

import type { SeatViewModel } from "../types/poker";
import type { SolverNodePayload } from "../types/api";

const POSITIONS = ["button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co"];

export function makeSeat(partial: Partial<SeatViewModel>): SeatViewModel {
  return {
    seatId: 0,
    position: "button",
    label: "BTN · Seat 0",
    stack: 9_900,
    bet: null,
    cards: [],
    isHero: false,
    isDealer: false,
    isActor: false,
    isFolded: false,
    isAllIn: false,
    isActive: true,
    ...partial,
  };
}

/** N seats around the table; hero at heroSeat, actor at actorSeat (optional). */
export function seatsFixture(count: 2 | 6 | 8, heroSeatId: number, actorSeatId?: number): SeatViewModel[] {
  return Array.from({ length: count }, (_, index) =>
    makeSeat({
      seatId: index,
      position: POSITIONS[index % POSITIONS.length],
      label: `${POSITIONS[index % POSITIONS.length].toUpperCase()} · Seat ${index}`,
      stack: 10_000 - index * 100,
      bet: index === 1 ? 100 : index === 0 ? 50 : 0,
      cards: index === heroSeatId ? [{ rank: "A", suit: "s" }, { rank: "K", suit: "d" }] : [],
      isHero: index === heroSeatId,
      isDealer: index === heroSeatId,
      isActor: index === actorSeatId,
      isFolded: index === 2,
      isAllIn: index === 3,
      isActive: actorSeatId === undefined ? true : index === actorSeatId || index === heroSeatId,
    }),
  );
}

export const BOARD_3 = ["2c", "7d", "Jh"] as const;

/** Small solver node with a few hand classes for grid/inspector tests. */
export function solverNodeFixture(): SolverNodePayload {
  return {
    actions: ["check", "bet50", "allin"],
    player: 0,
    hands: [
      { combo: "AsKs", weight: 1, equity: 0.62, ev: 12.4, strategy: { check: 0.7, bet50: 0.3 } },
      { combo: "AhKh", weight: 1, equity: 0.61, ev: 11.9, strategy: { check: 0.6, bet50: 0.4 } },
      { combo: "AdKd", weight: 1, equity: 0.6, ev: 11.5, strategy: { check: 0.5, bet50: 0.5 } },
      { combo: "AcKc", weight: 0.5, equity: 0.63, ev: 13.1, strategy: { check: 0.9, bet50: 0.1 } },
      { combo: "AsAh", weight: 1, equity: 0.85, ev: 22.0, strategy: { bet50: 0.8, allin: 0.2 } },
      { combo: "AsQd", weight: 1, equity: 0.55, ev: 8.2, strategy: { check: 1.0 } },
    ],
  };
}
