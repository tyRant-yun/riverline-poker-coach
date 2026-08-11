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
    expect(screen.getByPlaceholderText("未知")).toBeInTheDocument();
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

describe("ScenarioEditor seat-based stacks", () => {
  const eightMax: Scenario = {
    schemaVersion: 2,
    gameVariant: "nlhe",
    tableSize: 8,
    smallBlind: 50,
    bigBlind: 100,
    buttonSeat: 4,
    heroSeat: 5,
    seats: [0, 1, 2, 3, 4, 5, 6, 7].map((seatId) => ({
      seatId,
      startingStack: 10000,
      position: ["button", "small_blind", "big_blind", "utg", "utg+1", "mp", "hj", "co"][seatId],
    })),
    heroHoleCards: ["As", "Kd"],
    board: [],
    actionHistory: [],
    decisionPoint: { street: "preflop", actorSeat: 3, afterSequence: 0 },
    assumptions: {},
  };

  it("edits the hero seat's stack when heroSeat is not 0", () => {
    const { onUpdateScenario } = renderEditor(eightMax);

    const heroStackInput = screen.getByLabelText("Hero 起始筹码");
    expect(heroStackInput).toHaveValue(10000);
    fireEvent.change(heroStackInput, { target: { value: "7500" } });
    const patch = onUpdateScenario.mock.calls.at(-1)?.[0] as Partial<Scenario>;
    const edited = patch.seats?.find((seat) => seat.seatId === 5);
    expect(edited?.startingStack).toBe(7500);
    const untouched = patch.seats?.find((seat) => seat.seatId === 0);
    expect(untouched?.startingStack).toBe(10000);
  });

  it("hides the villain fields in a multiway scenario", () => {
    renderEditor(eightMax);
    expect(screen.queryByLabelText("Villain 手牌")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Villain 起始筹码")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/复盘模式/)).not.toBeInTheDocument();
  });

  it("exposes derived table controls and a compact editor for every multiway seat", () => {
    renderEditor(eightMax);

    expect(screen.getByRole("combobox", { name: "桌型" })).toHaveValue("8");
    expect(screen.getByRole("combobox", { name: "按钮位" })).toHaveValue("4");
    expect(screen.getByRole("combobox", { name: "Hero 座位" })).toHaveValue("5");
    expect(screen.getByLabelText("Seat 7 位置")).toHaveTextContent("CO");
    expect(screen.getByLabelText("Seat 7 起始筹码")).toHaveValue(10000);
    expect(screen.getByLabelText("Seat 7 手牌")).toBeInTheDocument();
  });
});
