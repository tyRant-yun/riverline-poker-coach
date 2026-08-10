import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ScenarioEditor from "./ScenarioEditor";
import type { Scenario } from "../../types/scenario";

function makeScenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    schemaVersion: 1,
    gameVariant: "nlhe",
    tableSize: 2,
    smallBlind: 50,
    bigBlind: 100,
    buttonSeat: 0,
    heroSeat: 0,
    seats: [
      { seatId: 0, startingStack: 10000, position: "button" },
      { seatId: 1, startingStack: 10000, position: "big_blind" },
    ],
    heroHoleCards: ["As", "Kd"],
    villainHoleCards: ["Qh", "Jc"],
    board: [],
    actionHistory: [],
    decisionPoint: { street: "preflop", actorSeat: 0, afterSequence: 0 },
    assumptions: {},
    ...overrides,
  };
}

function renderEditor(scenario = makeScenario()) {
  const onUpdateScenario = vi.fn();
  const onUpdateBoard = vi.fn();
  const utils = render(
    <ScenarioEditor
      scenario={scenario}
      boardInput={[...scenario.board, "", "", "", "", ""].slice(0, 5)}
      busy={false}
      canUndo={false}
      canRedo={false}
      onReset={vi.fn()}
      onUndo={vi.fn()}
      onRedo={vi.fn()}
      onUpdateScenario={onUpdateScenario}
      onUpdateBoard={onUpdateBoard}
    />,
  );
  return { ...utils, onUpdateScenario, onUpdateBoard };
}

describe("ScenarioEditor review mode (hero-only)", () => {
  it("clears villain cards and disables the input when enabled", () => {
    const { onUpdateScenario } = renderEditor();

    fireEvent.click(screen.getByLabelText(/复盘模式/));
    expect(onUpdateScenario).toHaveBeenCalledWith({ villainHoleCards: undefined });
    expect(screen.getByLabelText("Villain 手牌")).toBeDisabled();
    expect(screen.getByPlaceholderText("对手手牌未知（复盘模式）")).toBeInTheDocument();
  });

  it("keeps keyboard input working for the hero hand", () => {
    const { onUpdateScenario } = renderEditor();

    fireEvent.change(screen.getByLabelText("Hero 手牌"), { target: { value: "Ah Kh" } });
    expect(onUpdateScenario).toHaveBeenLastCalledWith({ heroHoleCards: ["Ah", "Kh"] });
  });
});

describe("ScenarioEditor 52-card picker", () => {
  it("opens the picker for the hero hand and appends a picked card", () => {
    const { onUpdateScenario } = renderEditor(makeScenario({ heroHoleCards: ["As"] }));

    fireEvent.click(screen.getByRole("button", { name: "为 Hero 手牌选牌" }));
    expect(screen.getByRole("group", { name: "选牌器 Hero 手牌" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "选牌 Qs" }));
    expect(onUpdateScenario).toHaveBeenCalledWith({ heroHoleCards: ["As", "Qs"] });
  });

  it("ignores picks once the hand is full but keeps the picker open", () => {
    const { onUpdateScenario } = renderEditor();

    fireEvent.click(screen.getByRole("button", { name: "为 Hero 手牌选牌" }));
    fireEvent.click(screen.getByRole("button", { name: "选牌 Qs" }));
    expect(onUpdateScenario).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "选牌器 Hero 手牌" })).toBeInTheDocument();
  });

  it("disables already-used cards inside the picker", () => {
    renderEditor();

    fireEvent.click(screen.getByRole("button", { name: "为 Hero 手牌选牌" }));
    expect(screen.getByRole("button", { name: "选牌 As" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选牌 Qh" })).toBeDisabled();
  });

  it("picks a board card into the target slot", () => {
    const { onUpdateBoard } = renderEditor();

    fireEvent.click(screen.getByRole("button", { name: "为 牌面 1 选牌" }));
    fireEvent.click(screen.getByRole("button", { name: "选牌 2c" }));
    expect(onUpdateBoard).toHaveBeenCalledWith(0, "2c");
  });

  it("closes the picker via its close button", () => {
    renderEditor();

    fireEvent.click(screen.getByRole("button", { name: "为 Hero 手牌选牌" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭选牌器" }));
    expect(screen.queryByRole("group", { name: "选牌器 Hero 手牌" })).not.toBeInTheDocument();
  });
});
