import { describe, expect, it } from "vitest";
import { actionLabel, actionTone, aggregateNode, cellKey } from "./aggregate";
import { solverNodeFixture } from "../../test/fixtures";

describe("cellKey", () => {
  it("classifies combos into 169-cell classes", () => {
    expect(cellKey("AsKs")).toBe("AKs");
    expect(cellKey("KhKd")).toBe("KK");
    expect(cellKey("AsKd")).toBe("AKo");
    expect(cellKey("Td9h")).toBe("T9o");
    expect(cellKey("QhJs")).toBe("QJo");
  });
});

describe("aggregateNode", () => {
  it("weight-averages per-cell EV/equity and strategy frequencies", () => {
    const cells = aggregateNode(solverNodeFixture());
    const aks = cells.get("AKs");
    expect(aks).toBeDefined();
    expect(aks!.comboCount).toBe(4);
    // Weighted EV: (12.4 + 11.9 + 11.5 + 13.1*0.5) / 3.5 = 12.1
    expect(aks!.ev).toBeCloseTo(12.1, 1);
    // Weighted check frequency: (0.7 + 0.6 + 0.5 + 0.9*0.5) / 3.5 = 0.6429
    const check = aks!.actions.find((item) => item.action === "check");
    expect(check!.frequency).toBeCloseTo(0.643, 2);
    expect(aks!.dominant).toBe("check");
  });

  it("handles empty and missing nodes", () => {
    expect(aggregateNode(null).size).toBe(0);
    expect(aggregateNode(undefined).size).toBe(0);
    expect(aggregateNode({ actions: [], player: 0, hands: [] }).size).toBe(0);
  });
});

describe("actionTone / actionLabel", () => {
  it("maps backend actions to semantic tones", () => {
    expect(actionTone("check")).toBe("check");
    expect(actionTone("bet33")).toBe("bet");
    expect(actionTone("raise2_5")).toBe("raise");
    expect(actionTone("allin")).toBe("allin");
    expect(actionTone("fold")).toBe("fold");
    expect(actionTone("call")).toBe("call");
  });

  it("formats human labels", () => {
    expect(actionLabel("bet33")).toBe("Bet 33%");
    expect(actionLabel("check")).toBe("Check");
    expect(actionLabel("allin")).toBe("Allin");
  });
});
