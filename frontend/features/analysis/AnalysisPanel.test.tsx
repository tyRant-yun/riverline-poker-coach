import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import AnalysisPanel from "./AnalysisPanel";
import type { AnalysisResponse } from "../../types/api";

type Analysis = AnalysisResponse["analysis"];

function makeAnalysis(overrides: Partial<Analysis> = {}): Analysis {
  return {
    metrics: { currentPot: 150, callCost: 50, spr: "66", potOdds: "0.33" },
    hand: {
      category: "high_card",
      madeHand: "A high",
      draws: [],
      outCount: 6,
      overcards: ["As", "Kd"],
      outCards: ["Qh", "Qc", "Qs"],
      counterfeitRiskCards: [],
    },
    board: { labels: ["2c", "7d", "Jh"], staticOrDynamic: "static", nutComboCount: 0, nextStreetChangeCards: [] },
    equity: { heroEquity: "0.62", villainEquity: "0.38", tieProbability: "0.02", sourceLevel: "enumerated" },
    multiwayEquity: null,
    strategyMatch: null,
    evidence: { items: [] },
    warnings: [],
    ...overrides,
  };
}

describe("AnalysisPanel fresh hand (hand === null)", () => {
  it("renders without crashing and degrades the hand sections", () => {
    const analysis = makeAnalysis({
      hand: null,
      equity: null,
      warnings: ["hero hole cards are missing; hand analysis is unavailable"],
    });
    render(<AnalysisPanel analysis={analysis} analysisStale={false} />);
    // No crash: the explicit missing-hand messages appear.
    expect(screen.getByText("未输入 Hero 手牌")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(
      screen.getByText("牌力分析需要 Hero 手牌；当前仍可查看牌面、规则状态和可用的其他证据。"),
    ).toBeInTheDocument();
    // Board evidence is still rendered.
    expect(screen.getByText(/Board: 2c · 7d · Jh/)).toBeInTheDocument();
  });

  it("does not fabricate hand facts when hero cards are missing", () => {
    const analysis = makeAnalysis({ hand: null });
    render(<AnalysisPanel analysis={analysis} analysisStale={false} />);
    expect(screen.queryByText("A high")).not.toBeInTheDocument();
    expect(screen.queryByText(/high_card/)).not.toBeInTheDocument();
  });

  it("renders the hero/villain equity line when equity exists", () => {
    const analysis = makeAnalysis();
    const { container } = render(<AnalysisPanel analysis={analysis} analysisStale={false} />);
    expect(container.textContent).toContain("0.62 Hero · 0.38 Villain · tie 0.02");
  });
});

describe("AnalysisPanel multiway equity", () => {
  const multiway = {
    algorithm: "monte_carlo",
    sourceLevel: "simulated",
    equityBySeat: { "0": "0.314", "2": "0.241", "4": "0.445" },
    activePlayerCount: 3,
    tieProbability: "0.021",
    trials: 10000,
    randomSeed: 7,
    standardErrorsBySeat: { "0": "0.002", "2": "0.002", "4": "0.002" },
    weighted: true,
  };

  it("renders per-seat equities with position labels", () => {
    const analysis = makeAnalysis({
      hand: null,
      equity: null,
      multiwayEquity: multiway,
    });
    const seats = [
      { seatId: 0, startingStack: 10000, position: "button" },
      { seatId: 2, startingStack: 10000, position: "big_blind" },
      { seatId: 4, startingStack: 10000, position: "hj" },
    ];
    render(
      <AnalysisPanel
        analysis={analysis}
        analysisStale={false}
        seats={seats}
        heroSeat={0}
      />,
    );
    expect(screen.getByText("MULTIWAY EQUITY")).toBeInTheDocument();
    expect(screen.getByText("44.5%")).toBeInTheDocument();
    expect(screen.getByText("31.4%")).toBeInTheDocument();
    expect(screen.getByText("24.1%")).toBeInTheDocument();
    // Position labels, with the hero seat marked.
    expect(screen.getByText("BTN · HERO")).toBeInTheDocument();
    expect(screen.getByText("BB")).toBeInTheDocument();
    expect(screen.getByText("HJ")).toBeInTheDocument();
    // Trial metadata line.
    expect(screen.getByText(/Tie probability 2.1% · Trials 10000/)).toBeInTheDocument();
    // The legacy villain-missing message must not appear when multiway exists.
    expect(screen.queryByText(/缺少 Villain 手牌或范围/)).not.toBeInTheDocument();
  });

  it("falls back to seat ids when positions are unknown", () => {
    const analysis = makeAnalysis({
      hand: null,
      equity: null,
      multiwayEquity: multiway,
    });
    render(<AnalysisPanel analysis={analysis} analysisStale={false} />);
    expect(screen.getByText("Seat 0")).toBeInTheDocument();
    expect(screen.getByText("Seat 4")).toBeInTheDocument();
  });
});
