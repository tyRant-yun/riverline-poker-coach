import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ActionTimeline from "./ActionTimeline";

const events = [
  { actionId: "fold-1", sequence: 1, street: "preflop", actorSeat: 3, actionType: "fold" },
  { actionId: "deal-2", sequence: 2, street: "flop", actorSeat: 0, actionType: "deal_flop" },
];

describe("ActionTimeline", () => {
  it("selects player actions by actionId and renders deals as non-decision events", () => {
    const onSelectAction = vi.fn();
    render(
      <ActionTimeline
        events={events}
        selectedActionId="fold-1"
        onSelectAction={onSelectAction}
        onRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Seat 3 · fold/i }));
    expect(onSelectAction).toHaveBeenCalledWith("fold-1");
    expect(screen.getByLabelText("状态事件 deal_flop")).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("button", { name: /deal_flop/i })).not.toBeInTheDocument();
  });
});
