// API response contracts (camelCase, mirrors backend JSON payloads).

import type { Scenario } from "./scenario";

export type LegalActions = {
  actorSeat: number | null;
  actions: string[];
  callAmount: number | null;
  minRaiseTo: number | null;
  maxRaiseTo: number | null;
  explanations: Record<string, string>;
};

export type FinalState = {
  street: string;
  actorSeat: number | null;
  board: string[];
  pot: number;
  stacks: Record<string, number>;
  bets: Record<string, number>;
  foldedSeats: number[];
  handInProgress: boolean;
  legalActions: LegalActions;
};

export type StateResponse = { finalState: FinalState };

export type AnalysisResponse = {
  analysis: {
    metrics: Record<string, string | number | null>;
    /** null for a fresh hand / review mode where hero has no hole cards yet. */
    hand: {
      category: string;
      madeHand: string;
      draws: string[];
      outCount: number;
      overcards: string[];
      outCards: string[];
      counterfeitRiskCards: string[];
    } | null;
    board: { labels: string[]; staticOrDynamic: string; nutComboCount: number; nextStreetChangeCards: string[] };
    equity: { heroEquity: string; villainEquity: string; tieProbability: string; sourceLevel: string } | null;
    multiwayEquity: {
      algorithm: string;
      sourceLevel: string;
      equityBySeat: Record<string, string>;
      activePlayerCount: number;
      tieProbability: string;
      trials: number;
      randomSeed?: number | null;
      standardErrorsBySeat?: Record<string, string> | null;
      weighted: boolean;
    } | null;
    rangeAnalysis?: {
      totalCombos: number;
      weightedCombos: string;
      valueCombos: number;
      bluffCombos: number;
      drawCombos: number;
      blockedCombos: number;
      blockedWeight: string;
      blockerCards: string[];
      polarity: string;
      heuristic: boolean;
    } | null;
    rangeComparison?: {
      rangeAdvantage: string | null;
      nutAdvantage: string | null;
      equityDistribution: Record<string, string>;
      heuristic: boolean;
    } | null;
    strategyMatch: {
      level: string;
      similarity: string;
      canQuoteFrequencies: boolean;
      explanation: string;
      differences: { field: string; requested: unknown; artifact: unknown; impact: string }[];
      recommendations: { action: string; summary: string; frequency?: string | null; ev?: string | null }[];
    } | null;
    evidence: { items: { evidenceId: string; kind: string; value: unknown; sourceLevel: string; description: string }[] };
    warnings: string[];
  };
};

export type TeachingResponse = {
  response: {
    explanationDepth: string;
    summary: { text: string };
    recommendedActions: { action: string; frequency?: string | null }[];
    keyReasons: { text: string }[];
    uncertainty: { text: string };
    conceptTags?: string[];
    followUpQuestion?: string | null;
  };
  provider?: string;
  degraded?: boolean;
  teacherVersion?: string;
  promptVersion?: string;
};

export type TeachingMeta = {
  provider: string;
  degraded: boolean;
  teacherVersion: string;
};

export type SolverNodePayload = {
  actions: string[];
  player: number;
  hands: { combo: string; weight: number; equity: number; ev: number; strategy: Record<string, number> }[];
};

export type SolveJob = {
  jobId: string;
  status: string;
  error?: string | null;
  executionMs?: number | null;
  result?: {
    metadata?: {
      solver: string;
      version: string;
      street: string;
      exploitabilityChips: number;
      targetExploitabilityChips: number;
      solveTimeMs: number;
      maxIterations: number;
      memoryUsageGb: number;
      memoryUsageCompressedGb: number;
      compressed: boolean;
    };
    root?: SolverNodePayload;
    responseNode?: SolverNodePayload;
  } | null;
};

export type PracticeQuestion = {
  questionId: string;
  profileId: string;
  prompt: string;
  conceptTags: string[];
  scenario: Scenario;
};

export type PracticeOutcome = {
  attempt: { correct: boolean; selectedAction: string };
  expectedAction: string;
  explanation: string;
  evidenceReferences: { evidenceId: string }[];
};
