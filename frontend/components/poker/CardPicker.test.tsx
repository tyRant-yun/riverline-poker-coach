import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import CardPicker from "./CardPicker";

describe("CardPicker", () => {
  it("renders all 52 cards grouped by suit", () => {
    render(<CardPicker label="Hero 手牌" usedCards={[]} onPick={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("group", { name: "选牌器 Hero 手牌" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /选牌 [AKQJT98765432][shdc]/ })).toHaveLength(52);
  });

  it("disables cards already used in the scenario", () => {
    render(
      <CardPicker label="Hero 手牌" usedCards={["As", "2c"]} onPick={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "选牌 As" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选牌 2c" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选牌 Ah" })).toBeEnabled();
  });

  it("emits the picked card and closes", () => {
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(<CardPicker label="Villain 手牌" usedCards={[]} onPick={onPick} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "选牌 Kd" }));
    expect(onPick).toHaveBeenCalledWith("Kd");

    fireEvent.click(screen.getByRole("button", { name: "关闭选牌器" }));
    expect(onClose).toHaveBeenCalled();
  });
});
