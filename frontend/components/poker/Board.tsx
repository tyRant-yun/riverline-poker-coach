// Community board display: always renders five slots (empty slots are
// placeholders). Board *input* lives in the scenario editor; this is the
// read-only table view.

import PlayingCard, { type CardSize } from "./PlayingCard";

type Props = {
  cards: readonly (string | null | undefined)[];
  size?: CardSize;
};

export default function Board({ cards, size = "md" }: Props) {
  const slots = [...cards, null, null, null, null, null].slice(0, 5);
  return (
    <div className="board-row">
      {slots.map((card, index) => (
        <PlayingCard
          key={index}
          card={card}
          size={size}
          ariaLabel={card ? `board card ${card}` : `empty board slot ${index + 1}`}
        />
      ))}
    </div>
  );
}
