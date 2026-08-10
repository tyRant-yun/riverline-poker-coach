// Solve submission gate. The sidecar is a heads-up POSTFLOP solver, so a
// spot is submittable only when the decision point is postflop, exactly two
// players remain active, and ranges exist for them — legacy hero/villain
// ranges (v1) or Schema v2 rangesBySeat. The backend re-validates every
// spot; this gate only prevents obviously invalid submissions.

import type { FinalState } from "../../types/api";
import type { Scenario } from "../../types/scenario";

const POSTFLOP_STREETS = new Set(["flop", "turn", "river"]);

export type SolveGateReasons = {
  postflop: boolean;
  twoActive: boolean;
  ranges: boolean;
};

/** Per-condition check for the solve gate (drives the disabled explanation). */
export function solveGateReasons(
  scenario: Scenario,
  state: FinalState | null,
  street: string,
): SolveGateReasons {
  const foldedSeats = state?.foldedSeats ?? [];
  const activeSeats = scenario.seats
    .map((seat) => seat.seatId)
    .filter((seatId) => !foldedSeats.includes(seatId));
  const rangesBySeat = scenario.rangesBySeat ?? {};
  const ranges =
    Boolean(scenario.heroRange && scenario.villainRange) ||
    (Object.keys(rangesBySeat).length >= 2 &&
      activeSeats.every((seatId) => Boolean(rangesBySeat[String(seatId)])));
  return {
    postflop: POSTFLOP_STREETS.has(street),
    twoActive: activeSeats.length === 2,
    ranges,
  };
}

export function canSubmitSolve(
  scenario: Scenario,
  state: FinalState | null,
  street: string,
  busy: boolean,
): boolean {
  if (busy) return false;
  const reasons = solveGateReasons(scenario, state, street);
  return reasons.postflop && reasons.twoActive && reasons.ranges;
}
