// Seat view-model construction for the table. Pure function over the
// scenario + backend state so the wiring (seat-based cards, foldedSeats,
// actor-vs-active semantics) is unit-testable.

import type { FinalState } from "../../types/api";
import type { Scenario } from "../../types/scenario";
import type { SeatViewModel } from "../../types/poker";
import { cardsToViewModels } from "./cards";
import { positionLabel } from "./positions";
import { getKnownCardsForSeat } from "./scenario";

export function buildSeatViewModels(
  scenario: Scenario,
  state: FinalState | null,
): SeatViewModel[] {
  const foldedSeats = state?.foldedSeats ?? [];
  return scenario.seats.map((seat) => {
    const isHero = seat.seatId === scenario.heroSeat;
    const isDealer = seat.seatId === scenario.buttonSeat;
    const isActor = state?.legalActions.actorSeat === seat.seatId;
    const isFolded = foldedSeats.includes(seat.seatId);
    return {
      seatId: seat.seatId,
      position: seat.position,
      label: isHero
        ? `${positionLabel(seat.position)} · Hero`
        : `${positionLabel(seat.position)} · Seat ${seat.seatId}`,
      stack: state?.stacks[String(seat.seatId)] ?? seat.startingStack,
      bet: state?.bets[String(seat.seatId)] ?? null,
      cards: cardsToViewModels(getKnownCardsForSeat(scenario, seat.seatId)),
      isHero,
      isDealer,
      isActor,
      isFolded,
      isAllIn: false,
      // Active = still in the hand (not folded). The current actor is a
      // separate concept (isActor) and may be null between streets.
      isActive: state ? !isFolded : true,
    };
  });
}
