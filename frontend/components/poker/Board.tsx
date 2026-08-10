// Community board display: always renders five slots. Dealt cards are real
// faces; un-dealt positions are WEAK empty slots (no card-back pattern), so
// a preflop board never reads as "five hidden cards". Board *input* lives in
// the scenario editor; this is the read-only table view.

import PlayingCard, { type CardSize } from "./PlayingCard";

type Props = {
  cards: readonly (string | null | undefined)[];
  size?: CardSize;
};

export default function Board({ cards, size = "md" }: Props) {
  const slots = [...cards, null, null, null, null, null].slice(0, 5);
  return (
    <div className="board-row">
      {slots.map((card, index) =>
        card ? (
          <PlayingCard
            key={index}
            card={card}
            size={size}
            ariaLabel={`board card ${card}`}
          />
        ) : (
          <span
            key={index}
            className={`board-slot board-slot--${size}`}
            aria-label={`empty board slot ${index + 1}`}
          />
        ),
      )}
    </div>
  );
}
