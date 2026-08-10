// Solve submission gate. The sidecar is a heads-up POSTFLOP solver, so a
// spot is submittable only when the decision point is postflop, exactly two
// players remain active, and ranges exist for them — legacy hero/villain
// ranges (v1) or Schema v2 rangesBySeat. The backend re-validates every
// spot; this gate only prevents obviously invalid submissions.

import type { FinalState } from "../../types/api";
import type { Scenario } from "../../types/scenario";

const POSTFLOP_STREETS = new Set(["flop", "turn", "river"]);

export function canSubmitSolve(
  scenario: Scenario,
  state: FinalState | null,
  street: string,
  busy: boolean,
): boolean {
  if (busy) return false;
  if (!POSTFLOP_STREETS.has(street)) return false;
  const foldedSeats = state?.foldedSeats ?? [];
  const activeSeats = scenario.seats
    .map((seat) => seat.seatId)
    .filter((seatId) => !foldedSeats.includes(seatId));
  if (activeSeats.length !== 2) return false;
  if (scenario.heroRange && scenario.villainRange) return true;
  const rangesBySeat = scenario.rangesBySeat ?? {};
  return (
    Object.keys(rangesBySeat).length >= 2 &&
    activeSeats.every((seatId) => Boolean(rangesBySeat[String(seatId)]))
  );
}
