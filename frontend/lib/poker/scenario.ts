// Seat-based scenario accessors. Schema v2 scenarios carry the canonical
// per-seat sources (knownHoleCardsBySeat / rangesBySeat); legacy v1
// scenarios use hero/villain fields. Components never branch on schema
// version themselves — they go through these helpers so both shapes work.

import type { Scenario, SeatSpec } from "../../types/scenario";

export function heroCards(scenario: Scenario): string[] {
  return scenario.heroHoleCards ?? [];
}

export function villainCards(scenario: Scenario): string[] {
  return scenario.villainHoleCards ?? [];
}

/** Seat whose id is the scenario's hero seat (fallback: seats[0]). */
export function heroSeatSpec(scenario: Scenario): SeatSpec {
  return (
    scenario.seats.find((seat) => seat.seatId === scenario.heroSeat) ??
    scenario.seats[0]
  );
}

/** The other seat in a heads-up scenario (fallback: seats[1]). */
export function opponentSeatSpec(scenario: Scenario): SeatSpec | null {
  if (scenario.tableSize !== 2) return null;
  return (
    scenario.seats.find((seat) => seat.seatId !== scenario.heroSeat) ??
    scenario.seats[1] ??
    null
  );
}

/**
 * All known hole cards for a seat: the Schema v2 seat-based source wins,
 * legacy hero/villain fields are the fallback for v1 scenarios.
 */
export function getKnownCardsForSeat(scenario: Scenario, seatId: number): string[] {
  const bySeat = scenario.knownHoleCardsBySeat?.[String(seatId)];
  if (bySeat && bySeat.length === 2) return bySeat;
  if (seatId === scenario.heroSeat) return heroCards(scenario);
  const opponent = opponentSeatSpec(scenario);
  if (opponent && seatId === opponent.seatId) return villainCards(scenario);
  return [];
}

/** Range attached to a seat: seat-based source first, legacy fields last. */
export function getRangeForSeat(
  scenario: Scenario,
  seatId: number,
): Scenario["heroRange"] | null {
  const bySeat = scenario.rangesBySeat?.[String(seatId)];
  if (bySeat) return bySeat;
  if (seatId === scenario.heroSeat) return scenario.heroRange ?? null;
  const opponent = opponentSeatSpec(scenario);
  if (opponent && seatId === opponent.seatId) return scenario.villainRange ?? null;
  return null;
}

/** Keep the v2 seat-based view in sync with a legacy hero/villain patch. */
export function syncSeatSourcesFromLegacy(
  scenario: Scenario,
  patch: Partial<Scenario>,
): Partial<Scenario> {
  const known = { ...(scenario.knownHoleCardsBySeat ?? {}) };
  if (Object.prototype.hasOwnProperty.call(patch, "heroHoleCards")) {
    const cards = patch.heroHoleCards ?? [];
    if (cards.length === 2) known[String(scenario.heroSeat)] = [...cards];
    else delete known[String(scenario.heroSeat)];
  }
  if (Object.prototype.hasOwnProperty.call(patch, "villainHoleCards")) {
    const opponent = opponentSeatSpec(scenario);
    const cards = patch.villainHoleCards ?? [];
    if (opponent && cards.length === 2) known[String(opponent.seatId)] = [...cards];
    else if (opponent) delete known[String(opponent.seatId)];
  }

  const ranges = { ...(scenario.rangesBySeat ?? {}) };
  if (Object.prototype.hasOwnProperty.call(patch, "heroRange")) {
    if (patch.heroRange) ranges[String(scenario.heroSeat)] = patch.heroRange;
    else delete ranges[String(scenario.heroSeat)];
  }
  if (Object.prototype.hasOwnProperty.call(patch, "villainRange")) {
    const opponent = opponentSeatSpec(scenario);
    if (opponent) {
      if (patch.villainRange) ranges[String(opponent.seatId)] = patch.villainRange;
      else delete ranges[String(opponent.seatId)];
    }
  }

  const sync: Partial<Scenario> = {};
  if (JSON.stringify(known) !== JSON.stringify(scenario.knownHoleCardsBySeat ?? {})) {
    sync.knownHoleCardsBySeat = known;
  }
  if (JSON.stringify(ranges) !== JSON.stringify(scenario.rangesBySeat ?? {})) {
    sync.rangesBySeat = ranges;
  }
  return sync;
}
