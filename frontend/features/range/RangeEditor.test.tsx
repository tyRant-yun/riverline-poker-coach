import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import RangeEditor from "./RangeEditor";
import type { DefaultRanges, RangeSide, RangeSummary } from "../../types/scenario";

const MATRIX: Record<string, string> = { AA: "1", AKs: "0.5", "22": "1" };
const SUMMARY: RangeSummary = { totalCombos: 34, weightedCombos: "30.5" };
const DEFAULTS: DefaultRanges = {
  btn_open: { rangeId: "r1", name: "BTN open 100BB", version: "1", source: "default_preflop", matrix169: MATRIX },
};

function renderEditor(overrides: Partial<Parameters<typeof RangeEditor>[0]> = {}) {
  const props: Parameters<typeof RangeEditor>[0] = {
    rangeSide: "villainRange",
    rangeText: "22+, A5s+, K9o+",
    defaultRanges: DEFAULTS,
    rangeMatrix: MATRIX,
    rangeSummary: SUMMARY,
    rangeCombos: [],
    onRangeSideChange: vi.fn(),
    onRangeTextChange: vi.fn(),
    onApplyDefault: vi.fn(),
    onParse: vi.fn(),
    onCycleCell: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<RangeEditor {...props} />) };
}

describe("RangeEditor", () => {
  it("renders the full 169 matrix expanded by default", () => {
    renderEditor();
    expect(screen.getByLabelText("169 格范围矩阵")).toBeInTheDocument();
    expect(screen.getByLabelText("AA weight")).toBeInTheDocument();
  });

  it("collapses into a compact summary and re-expands on demand", () => {
    renderEditor();
    fireEvent.click(screen.getByLabelText("收起范围矩阵"));
    expect(screen.queryByLabelText("169 格范围矩阵")).not.toBeInTheDocument();
    const compact = screen.getByLabelText("range summary compact");
    expect(compact.textContent).toContain("加权组合：");
    expect(compact.textContent).toContain("30.5");

    fireEvent.click(screen.getAllByRole("button", { name: "编辑范围" })[0]);
    expect(screen.getByLabelText("169 格范围矩阵")).toBeInTheDocument();
  });

  it("cycles cell weights through the editor callback", () => {
    renderEditor();
    fireEvent.click(screen.getByLabelText("AA weight"));
    expect(screen.getByLabelText("AA weight").getAttribute("aria-label")).toBe("AA weight");
  });

  it("applies default ranges and parses notation", () => {
    const onApplyDefault = vi.fn();
    const onParse = vi.fn();
    renderEditor({ onApplyDefault, onParse });
    fireEvent.change(screen.getByLabelText("默认范围"), { target: { value: "btn_open" } });
    expect(onApplyDefault).toHaveBeenCalledWith("btn_open");
    fireEvent.click(screen.getByRole("button", { name: "标准化范围" }));
    expect(onParse).toHaveBeenCalled();
  });

  it("switches the edited side", () => {
    const onRangeSideChange = vi.fn();
    renderEditor({ onRangeSideChange });
    fireEvent.change(screen.getByLabelText("范围侧"), { target: { value: "heroRange" as RangeSide } });
    expect(onRangeSideChange).toHaveBeenCalledWith("heroRange");
  });
});
