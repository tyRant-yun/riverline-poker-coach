import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Home from "../app/page";

const api = vi.hoisted(() => ({ health: vi.fn() }));

vi.mock("../lib/api/client", () => ({ systemApi: api }));
vi.mock("../features/table/ContinuousTablePage", () => ({
  default: () => <div data-testid="continuous-table-page">持续牌桌内容</div>,
}));
vi.mock("../features/reviews/TableReviewsPanel", () => ({
  default: () => <div data-testid="table-reviews-panel">最近完成手牌</div>,
}));

describe("MVP frontend shell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens the table by default, keeps only table/reviews navigation, and gives an honest offline status", async () => {
    api.health.mockRejectedValueOnce(new Error("offline"));
    render(<Home />);

    expect(screen.getByTestId("continuous-table-page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "牌桌" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "复盘" })).toBeInTheDocument();
    expect(screen.queryByText("Hand Lab")).not.toBeInTheDocument();
    expect(screen.queryByText("Solver")).not.toBeInTheDocument();
    expect(screen.queryByText("Train")).not.toBeInTheDocument();
    expect(screen.queryByText("Library")).not.toBeInTheDocument();

    expect(await screen.findByText("服务状态：离线")).toBeInTheDocument();
    expect(screen.getByText(/启动后端后重试：本地 SQLite/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "复盘" }));
    expect(screen.getByTestId("table-reviews-panel")).toBeInTheDocument();
  });
});
