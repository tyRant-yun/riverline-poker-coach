// N-seat poker table (2..8 players). Seats are positioned around an oval;
// the hero seat anchors the bottom. No hard-coded HU geometry: seat count
// drives the layout, so 6-max / 8-max need no table rewrite.

import type { CSSProperties } from "react";
import type { SeatViewModel } from "../../types/poker";
import Board from "./Board";
import PokerSeat from "./PokerSeat";

type Props = {
  seats: SeatViewModel[];
  board: readonly (string | null | undefined)[];
  pot: number | null;
};

/** Ellipse placement as felt-fraction percentages; hero at bottom center. */
function seatStyle(index: number, total: number, heroIndex: number): CSSProperties {
  const heroAngle = Math.PI / 2; // screen y grows downward -> bottom center
  const step = (2 * Math.PI) / Math.max(total, 1);
  const angle = heroAngle + (index - heroIndex) * step;
  const radiusX = 0.34;
  const radiusY = 0.36;
  return {
    left: `${50 + radiusX * 100 * Math.cos(angle)}%`,
    top: `${50 + radiusY * 100 * Math.sin(angle)}%`,
  };
}

export default function PokerTable({ seats, board, pot }: Props) {
  const heroIndex = Math.max(
    0,
    seats.findIndex((seat) => seat.isHero),
  );
  return (
    <div className="felt" data-testid="poker-table">
      <div className="pot-label">
        POT <strong>{pot ?? "—"}</strong>
      </div>
      <Board cards={board} />
      {seats.map((seat, index) => (
        <div className="seat-anchor" style={seatStyle(index, seats.length, heroIndex)} key={seat.seatId}>
          <PokerSeat seat={seat} />
        </div>
      ))}
    </div>
  );
}
