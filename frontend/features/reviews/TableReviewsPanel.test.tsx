import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TableReviewsPanel from "./TableReviewsPanel";

const api = vi.hoisted(() => ({ reviews: vi.fn() }));
vi.mock("../../lib/api/client", () => ({ continuousTableApi: api }));

describe("TableReviewsPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("uses the current local table session to list and then retrieve an honest review", async () => {
    window.localStorage.setItem("riverline-continuous-table-session", "session-7");
    api.reviews
      .mockResolvedValueOnce({ available: true, reviews: [{ handId: "session-7:hand:4" }] })
      .mockResolvedValueOnce({ available: true, review: { handId: "session-7:hand:4", heroSeat: 0, completionSequence: 12, heroDecisions: [{ actionSequence: 8, street: "flop", action: "call" }], references: {} } });

    render(<TableReviewsPanel />);
    await waitFor(() => expect(api.reviews).toHaveBeenCalledWith("session-7"));
    fireEvent.click(await screen.findByRole("button", { name: "session-7:hand:4" }));
    await waitFor(() => expect(api.reviews).toHaveBeenCalledWith("session-7", "session-7:hand:4"));
    expect(await screen.findByTestId("selected-table-review")).toHaveTextContent("Hero 决策：1");
    expect(screen.getByText(/不提供对手私牌或深度分析/)).toBeInTheDocument();
  });
});
