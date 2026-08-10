import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ComboInspector from "./ComboInspector";
import { solverNodeFixture } from "../../test/fixtures";

const node = solverNodeFixture();

describe("ComboInspector", () => {
  it("lists the real combos of the selected hand class", () => {
    render(<ComboInspector node={node} cell="AKs" />);
    expect(screen.getByLabelText("combo inspector AKs")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { expanded: false })).toHaveLength(4);
    expect(screen.getByText("A♠ K♠")).toBeInTheDocument();
    expect(screen.getByText("A♥ K♥")).toBeInTheDocument();
  });

  it("expands a combo into strategy bars and stats", () => {
    render(<ComboInspector node={node} cell="AKs" />);
    fireEvent.click(screen.getByText("A♠ K♠"));
    const expanded = screen.getByRole("button", { expanded: true });
    expect(expanded).toBeInTheDocument();
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("Weight")).toBeInTheDocument();
  });

  it("shows a placeholder for classes outside the solved range", () => {
    render(<ComboInspector node={node} cell="72o" />);
    expect(screen.getByText(/不在当前节点求解范围内/)).toBeInTheDocument();
  });

  it("handles a missing node", () => {
    render(<ComboInspector node={null} cell="AKs" />);
    expect(screen.getByText(/不在当前节点求解范围内/)).toBeInTheDocument();
  });
});
