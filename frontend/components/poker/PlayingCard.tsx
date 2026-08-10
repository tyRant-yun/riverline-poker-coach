// Unified playing card: rank + suit glyph (no image assets). Used on the
// table, board, solver combos, practice, and future history replay.

import type { CardViewModel } from "../../types/poker";
import { RED_SUITS, SUIT_SYMBOLS, cardViewModel } from "../../lib/poker/cards";

export type CardSize = "sm" | "md" | "lg";

type Props = {
  /** Either a raw card string ("As") or a parsed view model. */
  card?: CardViewModel | string | null;
  /** Render the card back (unknown / hidden card). */
  faceDown?: boolean;
  size?: CardSize;
  ariaLabel?: string;
};

export default function PlayingCard({ card, faceDown = false, size = "md", ariaLabel }: Props) {
  const vm = typeof card === "string" ? cardViewModel(card) : card;
  const className = `playing-card playing-card--${size} ${faceDown || !vm ? "playing-card--back" : RED_SUITS.has(vm.suit) ? "playing-card--red" : "playing-card--black"}`;
  if (faceDown || !vm) {
    return (
      <span className={className} aria-label={ariaLabel ?? (faceDown ? "card back" : "empty card")}>
        <span className="playing-card__back-inner" />
      </span>
    );
  }
  return (
    <span className={className} aria-label={ariaLabel ?? `${vm.rank}${SUIT_SYMBOLS[vm.suit]}`}>
      <span className="playing-card__rank">{vm.rank}</span>
      <span className="playing-card__suit">{SUIT_SYMBOLS[vm.suit]}</span>
    </span>
  );
}
