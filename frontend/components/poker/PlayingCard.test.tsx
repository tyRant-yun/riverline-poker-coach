import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import PlayingCard from "./PlayingCard";

describe("PlayingCard", () => {
  it("renders rank with the correct suit glyph for all four suits", () => {
    const cases: [string, string][] = [
      ["As", "♠"],
      ["Kh", "♥"],
      ["Qd", "♦"],
      ["Jc", "♣"],
    ];
    for (const [card, glyph] of cases) {
      const { unmount } = render(<PlayingCard card={card} />);
      expect(screen.getByLabelText(card.replace(/[shdc]$/, glyph))).toBeInTheDocument();
      unmount();
    }
  });

  it("colors hearts and diamonds red, spades and clubs black", () => {
    const { container } = render(
      <>
        <PlayingCard card="Ah" />
        <PlayingCard card="As" />
      </>,
    );
    const cards = container.querySelectorAll(".playing-card");
    expect(cards[0]).toHaveClass("playing-card--red");
    expect(cards[1]).toHaveClass("playing-card--black");
  });

  it("renders a card back when face down", () => {
    render(<PlayingCard faceDown />);
    expect(screen.getByLabelText("card back")).toHaveClass("playing-card--back");
  });

  it("renders an empty placeholder for missing cards", () => {
    render(<PlayingCard card={null} />);
    expect(screen.getByLabelText("empty card")).toBeInTheDocument();
  });

  it("accepts raw card strings and parsed view models", () => {
    const { container } = render(
      <>
        <PlayingCard card="Td" />
        <PlayingCard card={{ rank: "9", suit: "h" }} />
      </>,
    );
    expect(container.textContent).toContain("T♦");
    expect(container.textContent).toContain("9♥");
  });
});
