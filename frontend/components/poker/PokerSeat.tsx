// Single player seat on the table. Pure presentation over the SeatViewModel.
// Position leads (BTN), the seat number is secondary, the HERO tag is a
// distinct badge, and the stack reads in the active display unit.

import type { SeatViewModel } from "../../types/poker";
import type { DisplayUnit } from "../../lib/poker/format";
import { formatAmount } from "../../lib/poker/format";
import { positionLabel } from "../../lib/poker/positions";
import PlayingCard from "./PlayingCard";

type Props = {
  seat: SeatViewModel;
  /** Display unit for stack / bet (default: big blinds). */
  unit?: DisplayUnit;
  bigBlind?: number;
};

export default function PokerSeat({ seat, unit = "bb", bigBlind = 100 }: Props) {
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
        <span className="seat__position">{positionLabel(seat.position)}</span>
        {seat.isHero ? (
          <span className="seat__hero-tag">HERO</span>
        ) : (
          <span className="seat__identity">Seat {seat.seatId}</span>
        )}
        {seat.isDealer && <span className="seat__badge">D</span>}
        <strong className="seat__stack">
          {seat.stack == null ? "—" : formatAmount(seat.stack, bigBlind, unit)}
        </strong>
      </div>
      <div className="seat__cards">
        {cards.map((card, index) => (
          <PlayingCard key={index} card={card} faceDown={!card} size="sm" />
        ))}
      </div>
      {seat.bet != null && seat.bet > 0 && (
        <div className="seat__bet">
          <span>BET</span>
          <strong>{formatAmount(seat.bet, bigBlind, unit)}</strong>
        </div>
      )}
    </div>
  );
}
