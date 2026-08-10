// RangeBelief wire contract (camelCase, mirrors backend ranges/views.py).
// The belief engine is combo-level; matrix169 here is a derived view.

export type RangeBeliefComboView = {
  reach: string;
  probability: string;
  priorProbability: string;
  delta: string;
  multiplier: string | null;
};

export type RangeBeliefMatrixCell = {
  reachMass: string;
  probabilityMass: string;
  comboCount: number;
  priorProbabilityMass: string;
  delta: string;
  multiplier: string | null;
};

export type RangeBeliefUpdate = {
  actionType: string;
  actionLabel: string | null;
  observedSize: string | null;
  mappedSize: string | null;
  offTree: boolean;
  policySource: string | null;
  node: string | null;
};

export type RangeBeliefView = {
  seatId: number;
  street: string | null;
  afterSequence: number;
  /** False when no grounded policy produced a current belief. */
  available: boolean;
  unavailableReason: string | null;
  source: string | null;
  confidence: string | null;
  priorMass: string | null;
  retainedMass: string | null;
  retainedFraction: string | null;
  combos: Record<string, RangeBeliefComboView> | null;
  matrix169: Record<string, RangeBeliefMatrixCell> | null;
  update: RangeBeliefUpdate | null;
};

export type RangeBeliefTraceResponse = {
  seatId: number;
  available: boolean;
  unavailableReason: string | null;
  stalledAtSequence: number | null;
  snapshots: {
    snapshotId: string;
    seatId: number;
    street: string;
    afterSequence: number;
    source: string;
    confidence: string;
    priorMass: string;
    retainedMass: string;
    combos: Record<
      string,
      { combo: string; reach: string; probability: string }
    >;
    parentSnapshotId: string | null;
    update: RangeBeliefUpdate | null;
  }[];
};

export type BeliefMode = "prior" | "current" | "delta";
