import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ActionBar from "./ActionBar";
import type { LegalActions } from "../../types/api";

const LEGAL: LegalActions = {
  actorSeat: 1,
  actions: ["check", "fold", "bet"],
  callAmount: null,
  minRaiseTo: 200,
  maxRaiseTo: 9900,
  explanations: {},
};

describe("ActionBar", () => {
  it("renders only the backend legal actions", () => {
    render(
      <ActionBar
        legal={LEGAL}
        currentStreet="flop"
        busy={false}
        boardLength={3}
        raiseAmount=""
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /Check/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Bet/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fold" })).toBeInTheDocument();
    // Not legal -> absent (no call / raise / all-in buttons).
    expect(screen.queryByRole("button", { name: /Call/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Raise to/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "All-in" })).not.toBeInTheDocument();
  });

  it("shows the call amount from the backend contract", () => {
    render(
      <ActionBar
        legal={{ ...LEGAL, actions: ["call"], callAmount: 50, actorSeat: 0 }}
        currentStreet="preflop"
        busy={false}
        boardLength={0}
        raiseAmount=""
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    // BB mode keeps the chip amount in the accessible name (E2E "Call 50"
    // hook) while displaying the big-blind figure visually.
    expect(screen.getByRole("button", { name: /Call 50/ })).toBeInTheDocument();
    expect(screen.getByText("0.5 BB")).toBeInTheDocument();
    expect(screen.getByText("50 chips")).toBeInTheDocument();
  });

  it("shows plain chip amounts in chips mode", () => {
    render(
      <ActionBar
        legal={{ ...LEGAL, actions: ["call"], callAmount: 50, actorSeat: 0 }}
        currentStreet="preflop"
        busy={false}
        boardLength={0}
        raiseAmount=""
        unit="chips"
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Call 50" })).toBeInTheDocument();
    expect(screen.queryByText("50 chips")).not.toBeInTheDocument();
  });

  it("shows the pot and sizing hint in big blinds by default", () => {
    render(
      <ActionBar
        legal={LEGAL}
        currentStreet="flop"
        busy={false}
        boardLength={3}
        raiseAmount=""
        pot={150}
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    expect(screen.getByText("1.5 BB")).toBeInTheDocument(); // pot
    expect(screen.getByText("= 2 BB")).toBeInTheDocument(); // sizing hint (min raise 200)
  });

  it("emits the action with the requested amount", () => {
    const onAction = vi.fn();
    render(
      <ActionBar
        legal={LEGAL}
        currentStreet="flop"
        busy={false}
        boardLength={3}
        raiseAmount={250}
        onRaiseAmountChange={() => {}}
        onAction={onAction}
        onDeal={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Bet/ }));
    expect(onAction).toHaveBeenCalledWith("bet", 250);
  });

  it("shows the sizing input only when a bet or raise is legal", () => {
    const { rerender } = render(
      <ActionBar
        legal={LEGAL}
        currentStreet="flop"
        busy={false}
        boardLength={3}
        raiseAmount=""
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    expect(screen.getByLabelText(/下注 \/ raise-to/)).toBeInTheDocument();
    rerender(
      <ActionBar
        legal={{ ...LEGAL, actions: ["check", "fold"] }}
        currentStreet="flop"
        busy={false}
        boardLength={3}
        raiseAmount=""
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    expect(screen.queryByLabelText(/下注 \/ raise-to/)).not.toBeInTheDocument();
  });

  it("enables street-deal buttons per the current street and board length", () => {
    const onDeal = vi.fn();
    render(
      <ActionBar
        legal={{ ...LEGAL, actions: ["check"] }}
        currentStreet="preflop"
        busy={false}
        boardLength={3}
        raiseAmount=""
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={onDeal}
      />,
    );
    const dealFlop = screen.getByRole("button", { name: "Deal flop" });
    expect(dealFlop).toBeEnabled();
    fireEvent.click(dealFlop);
    expect(onDeal).toHaveBeenCalledWith("deal_flop");
  });

  it("disables deal when the board lacks enough cards", () => {
    render(
      <ActionBar
        legal={{ ...LEGAL, actions: ["check"] }}
        currentStreet="preflop"
        busy={false}
        boardLength={2}
        raiseAmount=""
        onRaiseAmountChange={() => {}}
        onAction={() => {}}
        onDeal={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Deal flop" })).toBeDisabled();
  });
});
