// Single player seat on the table. Pure presentation over the SeatViewModel.

import type { SeatViewModel } from "../../types/poker";
import PlayingCard from "./PlayingCard";

type Props = {
  seat: SeatViewModel;
};

export default function PokerSeat({ seat }: Props) {
  const classes = ["seat"];
  if (seat.isHero) classes.push("seat--hero");
  if (seat.isActor) classes.push("seat--actor");
  if (seat.isFolded) classes.push("seat--folded");
  if (seat.isAllIn) classes.push("seat--allin");
  if (!seat.isActive) classes.push("seat--inactive");

  const cards =
    seat.cards.length === 2
      ? seat.cards
      : ([null, null] as const);

  return (
    <div
      className={classes.join(" ")}
      data-seat-id={seat.seatId}
      aria-label={`seat ${seat.seatId} ${seat.position}`}
    >
      <div className="seat__header">
        <span className="seat__position">{seat.label}</span>
        {seat.isDealer && <span className="seat__badge">D</span>}
        {seat.isHero && <span className="seat__badge seat__badge--hero">HERO</span>}
        <strong className="seat__stack">{seat.stack ?? "—"}</strong>
      </div>
      <div className="seat__cards">
        {cards.map((card, index) => (
          <PlayingCard key={index} card={card} faceDown={!card} size="sm" />
        ))}
      </div>
      {seat.bet != null && seat.bet > 0 && <div className="seat__bet">Bet {seat.bet}</div>}
    </div>
  );
}
