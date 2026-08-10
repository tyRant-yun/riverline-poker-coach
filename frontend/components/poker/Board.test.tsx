import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Board from "./Board";

describe("Board empty slots", () => {
  it("renders weak empty slots, not card backs, for a preflop board", () => {
    render(<Board cards={[]} />);
    expect(screen.getAllByLabelText(/empty board slot/)).toHaveLength(5);
    // The key regression: no hidden-card pattern for un-dealt positions.
    expect(screen.queryAllByLabelText("card back")).toHaveLength(0);
    expect(document.querySelectorAll(".board-slot")).toHaveLength(5);
  });

  it("renders dealt cards plus empty slots for the remaining streets", () => {
    const flop = render(<Board cards={["As", "7d", "2c"]} />); // flop
    expect(screen.getAllByLabelText(/board card/)).toHaveLength(3);
    expect(screen.getAllByLabelText(/empty board slot/)).toHaveLength(2);
    flop.unmount();

    const turn = render(<Board cards={["As", "7d", "2c", "Jh"]} />); // turn
    expect(screen.getAllByLabelText(/board card/)).toHaveLength(4);
    expect(screen.getAllByLabelText(/empty board slot/)).toHaveLength(1);
    turn.unmount();

    render(<Board cards={["As", "7d", "2c", "Jh", "9s"]} />); // river
    expect(screen.getAllByLabelText(/board card/)).toHaveLength(5);
    expect(screen.queryAllByLabelText(/empty board slot/)).toHaveLength(0);
  });
});
