import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import RangeEditor from "./RangeEditor";
import type { DefaultRanges } from "../../types/scenario";
import type { RangeBeliefView } from "../../types/rangeBelief";

function renderEditor(overrides: { matrix?: Record<string, string>; belief?: RangeBeliefView | null; beliefLoading?: boolean; mode?: "prior" | "current" | "delta" } = {}) {
  const onCycleCell = vi.fn();
  const onBeliefModeChange = vi.fn();
  const utils = render(
    <RangeEditor
      rangeSide="villainRange"
      rangeText=""
      defaultRanges={{} as DefaultRanges}
      rangeMatrix={overrides.matrix ?? {}}
      rangeSummary={null}
      rangeCombos={[]}
      belief={overrides.belief ?? null}
      beliefLoading={overrides.beliefLoading ?? false}
      beliefMode={overrides.mode ?? "prior"}
      onRangeSideChange={vi.fn()}
      onRangeTextChange={vi.fn()}
      onApplyDefault={vi.fn()}
      onParse={vi.fn()}
      onCycleCell={onCycleCell}
      onBeliefModeChange={onBeliefModeChange}
    />,
  );
  return { ...utils, onCycleCell, onBeliefModeChange };
}

const availableBelief: RangeBeliefView = {
  seatId: 1,
  street: "flop",
  afterSequence: 4,
  available: true,
  unavailableReason: null,
  source: "solver",
  confidence: "grounded",
  priorMass: "2.9",
  retainedMass: "1.1",
  retainedFraction: "0.3793103448275862068965517241",
  combos: {},
  matrix169: {
    AKs: {
      reachMass: "1.1",
      probabilityMass: "1",
      comboCount: 2,
      priorProbabilityMass: "1",
      delta: "0",
      multiplier: "1",
    },
    AA: {
      reachMass: "0",
      probabilityMass: "0",
      comboCount: 0,
      priorProbabilityMass: "0",
      delta: "0",
      multiplier: null,
    },
  },
  update: {
    actionType: "bet",
    actionLabel: "Bet(100)",
    observedSize: null,
    mappedSize: null,
    offTree: false,
    policySource: "solver",
    node: "flop",
  },
};

const unavailableBelief: RangeBeliefView = {
  ...availableBelief,
  available: false,
  unavailableReason: "no_policy: no grounded action policy is available for this node (seat 1 at sequence 1)",
  combos: null,
  matrix169: null,
  update: null,
};

describe("RangeEditor matrix", () => {
  it("shows the full notation and weight in the cell tooltip", () => {
    renderEditor({ matrix: { AKs: "0.75" } });
    expect(screen.getByLabelText("AKs weight").getAttribute("title")).toBe("AKs · Weight 0.75");
    expect(screen.getByLabelText("AA weight").getAttribute("title")).toBe("AA · empty");
  });

  it("scales the visual intensity class with the stored weight", () => {
    renderEditor({ matrix: { AA: "0.5", KK: "1", QQ: "0.25" } });
    expect(screen.getByLabelText("AA weight")).toHaveClass("matrix-cell--w50");
    expect(screen.getByLabelText("KK weight")).toHaveClass("matrix-cell--w100");
    expect(screen.getByLabelText("QQ weight")).toHaveClass("matrix-cell--w25");
  });

  it("cycles the cell weight on click", () => {
    const { onCycleCell } = renderEditor();
    fireEvent.click(screen.getByLabelText("AKs weight"));
    expect(onCycleCell).toHaveBeenCalledWith("AKs");
  });

  it("keeps the E2E hooks (169 matrix group, collapse button)", () => {
    renderEditor();
    expect(screen.getByLabelText("169 格范围矩阵")).toBeInTheDocument();
    expect(screen.getByLabelText("收起范围矩阵")).toBeInTheDocument();
  });

  it("labels the editor as the Prior range", () => {
    renderEditor();
    expect(screen.getByRole("heading", { name: /起始范围（Prior）/ })).toBeInTheDocument();
  });
});

describe("RangeEditor belief view", () => {
  it("renders Prior / Current / Delta tabs", () => {
    renderEditor();
    expect(screen.getByLabelText("belief mode prior")).toBeInTheDocument();
    expect(screen.getByLabelText("belief mode current")).toBeInTheDocument();
    expect(screen.getByLabelText("belief mode delta")).toBeInTheDocument();
  });

  it("shows the unavailable state with a grounded warning when no policy exists", () => {
    renderEditor({ belief: unavailableBelief, mode: "current" });
    expect(screen.getByLabelText("current range unavailable")).toBeInTheDocument();
    expect(screen.getByText("Current range unavailable")).toBeInTheDocument();
    expect(screen.getByText(/No grounded action policy is available/)).toBeInTheDocument();
    expect(screen.getByText(/still edit the Prior range manually/)).toBeInTheDocument();
    // No fabricated numbers: the belief matrix is not rendered.
    expect(screen.queryByLabelText("belief 范围矩阵")).not.toBeInTheDocument();
  });

  it("shows source, node and retained reach for an available belief", () => {
    renderEditor({ belief: availableBelief, mode: "current" });
    expect(screen.getByText("solver-backed")).toBeInTheDocument();
    expect(screen.getByText(/flop · after Bet\(100\)/i)).toBeInTheDocument();
    expect(screen.getByText(/37.9%/)).toBeInTheDocument();
    expect(screen.getByLabelText("belief 范围矩阵")).toBeInTheDocument();
  });

  it("applies positive/negative delta classes in delta mode", () => {
    const belief: RangeBeliefView = {
      ...availableBelief,
      matrix169: {
        AKs: {
          reachMass: "0.8",
          probabilityMass: "0.6",
          comboCount: 4,
          priorProbabilityMass: "0.3",
          delta: "0.3",
          multiplier: "2",
        },
        AKo: {
          reachMass: "0.4",
          probabilityMass: "0.2",
          comboCount: 12,
          priorProbabilityMass: "0.5",
          delta: "-0.3",
          multiplier: "0.4",
        },
      },
    };
    renderEditor({ belief, mode: "delta" });
    expect(screen.getByLabelText("belief cell AKs")).toHaveClass("belief-cell--up");
    expect(screen.getByLabelText("belief cell AKo")).toHaveClass("belief-cell--down");
    expect(screen.getByLabelText("belief cell AKs").textContent).toContain("+30.0pp");
    expect(screen.getByLabelText("belief cell AKo").textContent).toContain("-30.0pp");
  });

  it("shows the combo detail on cell click", () => {
    renderEditor({ belief: availableBelief, mode: "current" });
    fireEvent.click(screen.getByLabelText("belief cell AKs"));
    expect(screen.getByLabelText("belief detail AKs")).toBeInTheDocument();
    // Prior mass 1.0 -> "100.0%" (appears for both Prior and Current here).
    expect(screen.getAllByText("100.0%").length).toBeGreaterThan(0);
  });

  it("switching tabs keeps the manual prior editor intact", () => {
    const { onBeliefModeChange } = renderEditor({ belief: availableBelief });
    fireEvent.click(screen.getByLabelText("belief mode delta"));
    expect(onBeliefModeChange).toHaveBeenCalledWith("delta");
    fireEvent.click(screen.getByLabelText("belief mode prior"));
    expect(onBeliefModeChange).toHaveBeenCalledWith("prior");
    // Back in prior mode the editable matrix is present again.
    expect(screen.getByLabelText("169 格范围矩阵")).toBeInTheDocument();
  });
});
