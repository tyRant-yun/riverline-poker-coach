import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import StrategyGrid from "./StrategyGrid";
import { aggregateNode } from "../../lib/solver/aggregate";
import { solverNodeFixture } from "../../test/fixtures";

const cells = aggregateNode(solverNodeFixture());

describe("StrategyGrid", () => {
  it("renders the 13x13 matrix (169 cells plus headers)", () => {
    render(<StrategyGrid cells={cells} mode="strategy" activeCell={null} onSelectCell={() => {}} />);
    const grid = screen.getByLabelText("solver strategy grid");
    expect(grid).toBeInTheDocument();
    expect(grid.querySelectorAll(".sg-cell").length).toBe(169);
  });

  it("shows action mixtures with frequencies in strategy mode", () => {
    render(<StrategyGrid cells={cells} mode="strategy" activeCell={null} onSelectCell={() => {}} />);
    const aks = screen.getByLabelText(/^AKs strategy/);
    expect(aks.textContent).toContain("Check");
    expect(aks.textContent).toContain("64%");
  });

  it("renders EV values in EV mode", () => {
    render(<StrategyGrid cells={cells} mode="ev" activeCell={null} onSelectCell={() => {}} />);
    const aks = screen.getByLabelText(/^AKs ev/);
    expect(aks.textContent).toContain("+");
  });

  it("renders equity percentages in equity mode", () => {
    render(<StrategyGrid cells={cells} mode="equity" activeCell={null} onSelectCell={() => {}} />);
    const aks = screen.getByLabelText(/^AKs equity/);
    expect(aks.textContent).toMatch(/\d+%/);
  });

  it("calls onSelectCell with the clicked cell and toggles it off again", () => {
    const onSelectCell = vi.fn();
    const first = render(<StrategyGrid cells={cells} mode="strategy" activeCell={null} onSelectCell={onSelectCell} />);
    fireEvent.click(screen.getByLabelText(/^AKs strategy/));
    expect(onSelectCell).toHaveBeenCalledWith("AKs");
    first.unmount();

    render(<StrategyGrid cells={cells} mode="strategy" activeCell="AKs" onSelectCell={onSelectCell} />);
    fireEvent.click(screen.getByLabelText(/^AKs strategy/));
    expect(onSelectCell).toHaveBeenLastCalledWith(null);
  });

  it("marks cells that are not in the solved range as empty", () => {
    render(<StrategyGrid cells={cells} mode="strategy" activeCell={null} onSelectCell={() => {}} />);
    const empty = screen.getByLabelText(/^72s strategy empty/);
    expect(empty).toHaveClass("sg-cell--empty");
  });
});
