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

export type ContinuousTable = {
  sessionId: string;
  handId: string | null;
  handSequence: number;
  buttonSeat: number;
  heroSeat: number;
  revision: number;
  board: string[];
  pot: number;
  street: string | null;
  seats: { seatId: number; stack: number; status: string; committed: number; revealedHoleCards?: string[] }[];
  heroHoleCards: string[];
  currentActor: number | null;
  heroLegalActions: { action: string; amountSemantics: string; minAmount?: number; maxAmount?: number }[];
  actionHistory: { sequence: number; street: string; actorSeat: number; action: string; amount: number | null }[];
  handComplete: boolean;
  result: { winnerSeats: number[]; payouts: Record<string, number> } | null;
  botDecisionProvenance: { sequence: number; actorSeat: number; profileId: string; provider: string; degraded: boolean; fallbackReason: string | null }[];
  fingerprint: string;
};

export type ContinuousTableResponse = { schemaVersion: number; idempotent?: boolean; table: ContinuousTable };
export type AdvisorResult = { status: "ready" | "degraded" | "not_ready" | "not_applicable"; recommendedAction?: { action: string; amountSemantics: string; amount?: number | null; reason: string } | null; source: string; version: string; potOdds?: string; equityThreshold?: string | null; confidence: string; explanationKey: string; limitations: string[]; decision: { fingerprint: string; handId: string; sequence: number; street: string } };
export type TableInsightsResponse = { schemaVersion: number; insights: { available: boolean; unavailableReason?: string; advisor?: { available: boolean; status?: AdvisorResult["status"]; unavailableReason?: string; result?: AdvisorResult; provenance?: { source: string; version: string; degraded: boolean } }; seatBeliefs?: { seatId: number; available: boolean; unavailableReason?: string; inactive?: boolean; rangeWidthPct?: number; rangeWidthCombos?: number; confidence?: string; confidenceScore?: number; source?: string; version?: string; dataVersion?: string; evidenceGrade?: "B" | "C" | "unsupported"; coverageStatus?: "covered" | "fallback" | "unsupported"; policyFingerprint?: string | null; fallbackReason?: string | null; approximate?: boolean; approximationReason?: string | null; changeReason?: string; limitations?: string[]; decision?: { handId: string; afterSequence: number }; matrix169?: Record<string, { probabilityMass: string; comboCount: number }>; topClasses?: { hand: string; probabilityMass: string }[] }[]; stats?: { available: boolean; unavailableReason?: string; bySeat: { seatId: number; vpip: number; pfr: number; threeBet: number }[] } } };
export type TheoryRecommendation = {
  status: "ready" | "degraded" | "not_ready";
  available: boolean;
  decision: { fingerprint: string; handId: string; sequence: number; street: string; observerSeat: number };
  evidence: { sourceKind: "policy_artifact" | "l2_bounded_solver" | "formula" | "unsupported"; evidenceGrade: "B" | "C" | "unsupported"; version: string; policyFingerprint?: string | null; provenance: string; coverage: { status: "covered" | "fallback" | "unsupported"; reason?: string | null; players: number; street: string }; degradationReason?: string | null };
  recommendedAction?: { action: string; amountSemantics: string; amount?: number | null; frequency: number } | null;
  actionFrequencies: { action: string; amountSemantics: string; amount?: number | null; frequency: number }[];
  sameOracleEvLoss: { chips?: number | null; definition?: string | null; unavailableReason?: string | null };
  explanation: { formulaVersion: string; potOdds: string; spr?: string | null; assumptions: string[]; limitations: string[] };
  degradation: string[];
};
export type TableTheoryRecommendationResponse = { schemaVersion: number; recommendation: TheoryRecommendation };
export type TableAdvisorResponse = { schemaVersion: number; advisor: AdvisorResult };
export type TableReviewResponse = { schemaVersion: number; available: boolean; unavailableReason?: string | null; review?: { handId: string; heroSeat: number; completionSequence: number; heroDecisions: { actionSequence: number; street: string; action: string }[]; references: Record<string, { status: string; unavailableReason?: string | null }> } | null; reviews?: { handId: string }[] };
export type TableSolverResponse = { schemaVersion: number; solver: {
  status: "ready" | "degraded" | "unavailable" | "not_ready";
  recommendedAction?: { action: string; amountSemantics?: string; amount?: number | null; approximateEvChips?: string; showdownEquity?: string; foldEquity?: string; sampleCount?: number; effectiveSampleSize?: string; confidenceInterval95?: { lower: string; upper: string; confidence?: string }; responseMix?: { fold: string; call: string; raise: string }; responseModel?: string } | null;
  candidates: { action: string; amountSemantics?: string; amount?: number | null; approximateEvChips: string; showdownEquity?: string; foldEquity?: string; sampleCount?: number; effectiveSampleSize?: string; confidenceInterval95?: { lower: string; upper: string; confidence?: string }; potPercentage?: string; isJam?: boolean; sizingClass?: "non_sizing" | "standard" | "overbet" | "jam"; deltaEvChips?: string; deltaEvConfidenceInterval95?: { lower: string; upper: string; confidence?: string }; uncertaintyStatus?: "available" | "not_available"; recommendationTier?: "robust" | "close" | "not_available" | "not_recommended"; responseMix?: { fold: string; call: string; raise: string }; responseModel?: string }[];
  equity?: string | null; iterations: number; sampleCount?: number; effectiveSampleSize?: string; confidenceInterval95?: { lower: string; upper: string; confidence?: string } | null; elapsedMicroseconds?: number; budgetMs?: number; hardBudgetMs?: number; budgetTier?: "quick" | "standard" | "deep"; source: string; rangeStatus?: string; rangeFingerprint?: string | null; rangeModelVersion?: string | null; version: string; modelVersion?: string; confidence?: "exact" | "coarse" | "partial" | "unavailable"; decision?: { fingerprint: string; handId: string; sequence: number; street: string };
  sizingRobustness?: "robust" | "close" | "not_available"; recommendationReasonCodes?: string[]; robustnessMarginConfidenceInterval95?: { lower: string; upper: string; confidence?: string } | null; limitations: string[]; unavailableReason?: string | null;
} };
export type TableReconciliationResponse = { schemaVersion: number; reconciliation: {
  status: "ready" | "degraded" | "not_ready";
  decision: { fingerprint: string; handId: string; sequence: number; street: string };
  ruleBaseline: { role: "rule_baseline"; status: "ready" | "degraded" | "unavailable" | "not_ready"; action?: { action: string; amountSemantics: string; amountChips?: number | null; potPct?: string | null; isJam?: boolean } | null; provenance: Record<string, string | null>; limitations: string[]; unavailableReason?: string | null };
  simulationEstimate: { role: "simulation_estimate"; status: "ready" | "degraded" | "unavailable" | "not_ready"; action?: { action: string; amountSemantics: string; amountChips?: number | null; potPct?: string | null; isJam?: boolean } | null; provenance: Record<string, string | null>; limitations: string[]; unavailableReason?: string | null };
  agreement: { kind: "exact_action" | "same_action_different_sizing" | "different_action" | "insufficient_evidence"; reasonCodes: string[]; confidenceInterval: { status: "available" | "not_available"; overlap?: boolean | null }; sizingRobustness: "robust" | "close" | "not_available" };
} };

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

/** The spot echoed by POST /v1/solve/jobs (mirrors backend SolverSpot). */
export type SolverSpotPayload = {
  schemaVersion?: number;
  street: string;
  board: string[];
  turn: string | null;
  river: string | null;
  oopRange: string;
  ipRange: string;
  startingPot: number;
  effectiveStack: number;
  rakeRate: number;
  rakeCap: number;
  betSizes: string;
  raiseSizes: string;
  addAllinThreshold?: number | null;
  forceAllinThreshold?: number | null;
  mergingThreshold?: number | null;
  maxIterations: number;
  targetExploitabilityFrac: number;
  dumpResponseToAction?: number | null;
  /** Explicit approximation flags, e.g. "bunching_ignored". */
  assumptions?: string[] | null;
};

export type SolveJob = {
  jobId: string;
  status: string;
  error?: string | null;
  executionMs?: number | null;
  /** Present on the submit response only; the spot the job was built from. */
  spot?: SolverSpotPayload | null;
  provenance?: {
    scenarioFingerprint: string;
    spotFingerprint: string;
    decisionSequence: number;
    policySequence: number;
    actorSeat: number;
    activeSeats: number[];
    street: string;
  } | null;
  scenarioFingerprint?: string;
  spotFingerprint?: string;
  policySequence?: number;
  actorSeat?: number;
  activeSeats?: number[];
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
