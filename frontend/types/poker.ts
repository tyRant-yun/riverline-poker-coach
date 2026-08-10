// Frontend poker view models. These are display-oriented shapes, NOT rule
// truth: the backend remains the single source of rule/legality facts.
// The SeatViewModel is deliberately seat-count agnostic (2..8 players) so the
// table UI does not need to change when the backend grows past HU.

export type Suit = "s" | "h" | "d" | "c";

export type CardViewModel = { rank: string; suit: Suit } | null;

export type SeatViewModel = {
  seatId: number;
  position: string;
  /** Human-readable position + identity label, e.g. "BTN · Hero". */
  label: string;
  /** Current stack in chips (null when state has not loaded). */
  stack: number | null;
  /** Current committed bet in chips (0 / null when none). */
  bet: number | null;
  /** Known hole cards; unknown opponents render card backs. */
  cards: CardViewModel[];
  isHero: boolean;
  isDealer: boolean;
  isActor: boolean;
  isFolded: boolean;
  isAllIn: boolean;
  isActive: boolean;
};
