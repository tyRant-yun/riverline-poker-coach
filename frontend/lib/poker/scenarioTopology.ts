import type { Scenario, SeatSpec } from "../../types/scenario";

const POSITION_ORDER: Record<number, readonly string[]> = {
  2: ["button", "big_blind"],
  3: ["button", "small_blind", "big_blind"],
  4: ["button", "small_blind", "big_blind", "co"],
  5: ["button", "small_blind", "big_blind", "utg", "co"],
  6: ["button", "small_blind", "big_blind", "utg", "mp", "co"],
  7: ["button", "small_blind", "big_blind", "utg", "mp", "hj", "co"],
  8: ["button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co"],
};

export type TableSize = keyof typeof POSITION_ORDER;

export function derivePosition(tableSize: TableSize, buttonSeat: number, seatId: number): string {
  return POSITION_ORDER[tableSize][(seatId - buttonSeat + tableSize) % tableSize];
}

export function initialActorSeat(tableSize: TableSize, buttonSeat: number): number {
  return tableSize === 2 ? buttonSeat : (buttonSeat + 3) % tableSize;
}

function derivedSeats(tableSize: TableSize, buttonSeat: number, previous: readonly SeatSpec[]): SeatSpec[] {
  const stacks = new Map(previous.map((seat) => [seat.seatId, seat.startingStack]));
  const defaultStack = previous[0]?.startingStack ?? 10_000;
  return Array.from({ length: tableSize }, (_, seatId) => ({
    seatId,
    startingStack: stacks.get(seatId) ?? defaultStack,
    position: derivePosition(tableSize, buttonSeat, seatId),
  }));
}

function retainedSeatMap<T>(value: Record<string, T> | undefined, tableSize: number): Record<string, T> | undefined {
  if (!value) return undefined;
  return Object.fromEntries(Object.entries(value).filter(([seatId]) => Number(seatId) >= 0 && Number(seatId) < tableSize));
}

function canonicalKnownCards(scenario: Scenario): Record<string, string[]> | undefined {
  const known = { ...(scenario.knownHoleCardsBySeat ?? {}) };
  const heroCards = scenario.heroHoleCards ?? [];
  if (heroCards.length === 2 && !known[String(scenario.heroSeat)]) known[String(scenario.heroSeat)] = heroCards;
  if (scenario.tableSize === 2) {
    const opponentSeat = scenario.seats.find((seat) => seat.seatId !== scenario.heroSeat)?.seatId;
    const villainCards = scenario.villainHoleCards ?? [];
    if (opponentSeat != null && villainCards.length === 2 && !known[String(opponentSeat)]) known[String(opponentSeat)] = villainCards;
  }
  return Object.keys(known).length > 0 ? known : undefined;
}

function canonicalRanges(scenario: Scenario): NonNullable<Scenario["rangesBySeat"]> | undefined {
  const ranges = { ...(scenario.rangesBySeat ?? {}) };
  if (scenario.heroRange && !ranges[String(scenario.heroSeat)]) ranges[String(scenario.heroSeat)] = scenario.heroRange;
  if (scenario.tableSize === 2) {
    const opponentSeat = scenario.seats.find((seat) => seat.seatId !== scenario.heroSeat)?.seatId;
    if (opponentSeat != null && scenario.villainRange && !ranges[String(opponentSeat)]) ranges[String(opponentSeat)] = scenario.villainRange;
  }
  return Object.keys(ranges).length > 0 ? ranges : undefined;
}

function viewportCards(scenario: Scenario, heroSeat: number, tableSize: number, known: Record<string, string[]> | undefined) {
  const heroHoleCards = known?.[String(heroSeat)] ?? (heroSeat === scenario.heroSeat ? scenario.heroHoleCards ?? [] : []);
  if (tableSize !== 2) return { heroHoleCards, villainHoleCards: undefined };
  const villainSeat = heroSeat === 0 ? 1 : 0;
  return {
    heroHoleCards,
    villainHoleCards: known?.[String(villainSeat)] ?? (villainSeat !== scenario.heroSeat ? scenario.villainHoleCards ?? [] : []),
  };
}

function resetTopology(scenario: Scenario, tableSize: TableSize, buttonSeat: number, heroSeat: number): Scenario {
  const knownHoleCardsBySeat = retainedSeatMap(canonicalKnownCards(scenario), tableSize);
  const rangesBySeat = retainedSeatMap(canonicalRanges(scenario), tableSize);
  const cards = viewportCards(scenario, heroSeat, tableSize, knownHoleCardsBySeat);
  return {
    ...scenario,
    schemaVersion: Math.max(scenario.schemaVersion, 2),
    tableSize,
    buttonSeat,
    heroSeat,
    seats: derivedSeats(tableSize, buttonSeat, scenario.seats),
    ...cards,
    ...(knownHoleCardsBySeat ? { knownHoleCardsBySeat } : {}),
    ...(rangesBySeat ? { rangesBySeat } : {}),
    actionHistory: [],
    decisionPoint: { street: "preflop", actorSeat: initialActorSeat(tableSize, buttonSeat), afterSequence: 0 },
  };
}

/** Resize deterministically: keep matching seat ids, drop removed seats, and reset the replay cursor. */
export function resizeTable(scenario: Scenario, tableSize: TableSize): Scenario {
  const buttonSeat = Math.min(scenario.buttonSeat, tableSize - 1);
  const heroSeat = Math.min(scenario.heroSeat, tableSize - 1);
  return resetTopology(scenario, tableSize, buttonSeat, heroSeat);
}

/** Button controls derived positions; no arbitrary position fields are accepted from the UI. */
export function changeButtonSeat(scenario: Scenario, buttonSeat: number): Scenario {
  const tableSize = scenario.tableSize as TableSize;
  return resetTopology(scenario, tableSize, buttonSeat, scenario.heroSeat);
}

/** A hero change is a viewpoint change: preserve seat-owned cards/ranges and only update legacy aliases. */
export function changeHeroSeat(scenario: Scenario, heroSeat: number): Scenario {
  const knownHoleCardsBySeat = canonicalKnownCards(scenario);
  const rangesBySeat = canonicalRanges(scenario);
  const cards = viewportCards(scenario, heroSeat, scenario.tableSize, knownHoleCardsBySeat);
  const heroRange = rangesBySeat?.[String(heroSeat)] ?? scenario.heroRange;
  const opponentSeat = scenario.seats.find((seat) => seat.seatId !== heroSeat)?.seatId;
  const villainRange = scenario.tableSize === 2 && opponentSeat != null
    ? rangesBySeat?.[String(opponentSeat)] ?? scenario.villainRange
    : scenario.villainRange;
  return {
    ...scenario,
    heroSeat,
    ...cards,
    ...(knownHoleCardsBySeat ? { knownHoleCardsBySeat } : {}),
    ...(rangesBySeat ? { rangesBySeat } : {}),
    ...(heroRange ? { heroRange } : {}),
    ...(villainRange ? { villainRange } : {}),
  };
}
