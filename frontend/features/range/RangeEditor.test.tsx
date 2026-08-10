import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import RangeEditor from "./RangeEditor";
import type { DefaultRanges } from "../../types/scenario";

function renderEditor(overrides: { matrix?: Record<string, string> } = {}) {
  const onCycleCell = vi.fn();
  const utils = render(
    <RangeEditor
      rangeSide="villainRange"
      rangeText=""
      defaultRanges={{} as DefaultRanges}
      rangeMatrix={overrides.matrix ?? {}}
      rangeSummary={null}
      rangeCombos={[]}
      onRangeSideChange={vi.fn()}
      onRangeTextChange={vi.fn()}
      onApplyDefault={vi.fn()}
      onParse={vi.fn()}
      onCycleCell={onCycleCell}
    />,
  );
  return { ...utils, onCycleCell };
}

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
});
