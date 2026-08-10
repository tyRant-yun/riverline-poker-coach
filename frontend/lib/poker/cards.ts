// Card parsing / rendering helpers. Pure presentation: legality and rule
// truth always come from the backend.

import type { CardViewModel, Suit } from "../../types/poker";

export const SUIT_SYMBOLS: Record<Suit, string> = { s: "♠", h: "♥", d: "♦", c: "♣" };
export const SUIT_LABELS: Record<Suit, string> = { s: "spades", h: "hearts", d: "diamonds", c: "clubs" };
export const RED_SUITS: ReadonlySet<Suit> = new Set(["h", "d"]);
const RANK_PATTERN = /^[2-9TJQKA]$/;

export function cardRank(card: string): string | null {
  const rank = card.slice(0, 1).toUpperCase();
  return RANK_PATTERN.test(rank) ? rank : null;
}

export function cardSuit(card: string): Suit | null {
  const suit = card.slice(1).toLowerCase();
  return (Object.prototype.hasOwnProperty.call(SUIT_SYMBOLS, suit) ? suit : null) as Suit | null;
}

export function isRedCard(card: string): boolean {
  const suit = cardSuit(card);
  return suit !== null && RED_SUITS.has(suit);
}

export function cardViewModel(card: string | null | undefined): CardViewModel {
  if (!card) return null;
  const rank = cardRank(card);
  const suit = cardSuit(card);
  return rank !== null && suit !== null ? { rank, suit } : null;
}

export function cardsToViewModels(cards: readonly (string | null | undefined)[]): CardViewModel[] {
  return cards.map(cardViewModel);
}

/** "As" -> "A♠"; invalid/empty input -> "?". */
export function formatCard(card: string | null | undefined): string {
  const vm = cardViewModel(card);
  if (!vm) return "?";
  return `${vm.rank}${SUIT_SYMBOLS[vm.suit]}`;
}
