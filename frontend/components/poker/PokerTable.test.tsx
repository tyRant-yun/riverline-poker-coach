import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import PokerTable from "./PokerTable";
import { BOARD_3, seatsFixture } from "../../test/fixtures";

describe("PokerTable", () => {
  it("renders two seats for a HU fixture", () => {
    render(<PokerTable seats={seatsFixture(2, 0, 1)} board={BOARD_3} pot={200} />);
    expect(screen.getByLabelText("seat 0 button")).toBeInTheDocument();
    expect(screen.getByLabelText("seat 1 small_blind")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/board card/)).toHaveLength(3);
    expect(screen.getByText("200")).toBeInTheDocument();
  });

  it("renders six seats without losing the hero anchor", () => {
    render(<PokerTable seats={seatsFixture(6, 4)} board={BOARD_3} pot={200} />);
    expect(screen.getAllByLabelText(/^seat /)).toHaveLength(6);
    const heroSeat = screen.getByLabelText("seat 4 utg+1");
    expect(heroSeat).toBeInTheDocument();
    expect(heroSeat).toHaveClass("seat--hero");
  });

  it("renders eight seats (8-max readiness)", () => {
    render(<PokerTable seats={seatsFixture(8, 0)} board={BOARD_3} pot={200} />);
    expect(screen.getAllByLabelText(/^seat /)).toHaveLength(8);
    // All eight seat anchors exist with unique seat ids.
    const anchors = document.querySelectorAll(".seat-anchor");
    expect(anchors).toHaveLength(8);
  });

  it("highlights the current actor", () => {
    render(<PokerTable seats={seatsFixture(2, 0, 1)} board={BOARD_3} pot={200} />);
    const actorSeat = screen.getByLabelText("seat 1 small_blind");
    expect(actorSeat).toHaveClass("seat--actor");
  });

  it("marks the dealer button seat", () => {
    render(<PokerTable seats={seatsFixture(2, 0)} board={BOARD_3} pot={200} />);
    const dealerSeat = screen.getByLabelText("seat 0 button");
    expect(dealerSeat.textContent).toContain("D");
  });

  it("shows folded and all-in seat states", () => {
    render(<PokerTable seats={seatsFixture(6, 0)} board={BOARD_3} pot={200} />);
    expect(screen.getByLabelText("seat 2 big_blind")).toHaveClass("seat--folded");
    expect(screen.getByLabelText("seat 3 utg")).toHaveClass("seat--allin");
  });

  it("renders known hero hole cards and card backs for unknowns", () => {
    render(<PokerTable seats={seatsFixture(2, 0)} board={[]} pot={150} />);
    expect(screen.getByLabelText("A♠")).toBeInTheDocument();
    expect(screen.getByLabelText("K♦")).toBeInTheDocument();
    expect(screen.getAllByLabelText("card back").length).toBeGreaterThan(0);
  });
});
