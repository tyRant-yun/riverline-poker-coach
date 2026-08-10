// ScenarioSpec wire contract (camelCase, mirrors backend domain/models.py).
// This is the frontend view of the backend contract; never rename backend JSON fields.

export type ActionEvent = {
  actionId: string;
  sequence: number;
  street: string;
  actorSeat: number;
  actionType: string;
  amount?: number;
  amountType?: string;
};

export type SeatSpec = {
  seatId: number;
  startingStack: number;
  position: string;
};

export type RangeSpecPayload = {
  rangeId: string;
  name: string;
  version: string;
  source: string;
  isDefaultAssumption?: boolean;
  matrix169: Record<string, string>;
};

export type Scenario = {
  schemaVersion: number;
  gameVariant: string;
  tableSize: number;
  smallBlind: number;
  bigBlind: number;
  buttonSeat: number;
  heroSeat: number;
  seats: SeatSpec[];
  heroHoleCards: string[];
  villainHoleCards?: string[];
  board: string[];
  actionHistory: ActionEvent[];
  decisionPoint: { street: string; actorSeat: number; afterSequence: number };
  assumptions: Record<string, unknown>;
  heroRange?: RangeSpecPayload;
  villainRange?: RangeSpecPayload;
};

export type RangeSide = "heroRange" | "villainRange";

export type RangeCombo = { cards: string[]; weight: string };
export type RangeSummary = { totalCombos: number; weightedCombos: string };
export type DefaultRanges = Record<string, RangeSpecPayload>;

export type SavedScenario = {
  scenarioId: string;
  title: string;
  scenario: Scenario;
  revisionNo: number;
  updatedAt: string;
};

export type ScenarioRevision = {
  scenarioId: string;
  revisionNo: number;
  scenario: Scenario;
  createdAt: string;
};

export type AnalysisRun = {
  analysisId: string;
  revisionNo: number;
  createdAt: string;
  output?: { board?: { board?: string[] } };
};

export type AnalysisComparison = {
  differences: { field: string; left: unknown; right: unknown }[];
  versions: Record<string, { rulesEngineVersion: string; analysisVersion: string }>;
};
