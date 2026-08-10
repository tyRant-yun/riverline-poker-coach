// Solver result aggregation: collapse combo-level rows into 169-cell hand
// classes (weighted averages), plus presentational action classification.
// All numbers are re-aggregations of backend values — never recomputed.

import type { SolverNodePayload } from "../../types/api";

const RANK_ORDER: Record<string, number> = { "2": 0, "3": 1, "4": 2, "5": 3, "6": 4, "7": 5, "8": 6, "9": 7, T: 8, J: 9, Q: 10, K: 11, A: 12 };

/** "AsKs" -> "AKs"; "AsKd" -> "AKo"; "AsAh" -> "AA". */
export function cellKey(combo: string): string {
  const a = combo.slice(0, 2);
  const b = combo.slice(2, 4);
  if (a[0] === b[0]) return `${a[0]}${b[0]}`;
  const ra = RANK_ORDER[a[0]];
  const rb = RANK_ORDER[b[0]];
  const high = ra >= rb ? a[0] : b[0];
  const low = ra >= rb ? b[0] : a[0];
  return `${high}${low}${a[1] === b[1] ? "s" : "o"}`;
}

export type CellAction = { action: string; frequency: number };
export type CellAggregate = {
  cell: string;
  actions: CellAction[];
  dominant: string;
  ev: number;
  equity: number;
  comboCount: number;
};

/** Weighted aggregation of a solver node into 169-cell hand classes. */
export function aggregateNode(node: SolverNodePayload | null | undefined): Map<string, CellAggregate> {
  const acc = new Map<
    string,
    { weight: number; ev: number; equity: number; comboCount: number; actions: Map<string, number> }
  >();
  for (const hand of node?.hands ?? []) {
    const key = cellKey(hand.combo);
    let entry = acc.get(key);
    if (!entry) {
      entry = { weight: 0, ev: 0, equity: 0, comboCount: 0, actions: new Map() };
      acc.set(key, entry);
    }
    entry.weight += hand.weight;
    entry.ev += hand.weight * hand.ev;
    entry.equity += hand.weight * hand.equity;
    entry.comboCount += 1;
    for (const [action, frequency] of Object.entries(hand.strategy)) {
      entry.actions.set(action, (entry.actions.get(action) ?? 0) + hand.weight * frequency);
    }
  }
  const result = new Map<string, CellAggregate>();
  for (const [key, entry] of acc) {
    const weight = entry.weight || 1;
    const actions: CellAction[] = [...entry.actions.entries()]
      .map(([action, w]) => ({ action, frequency: w / weight }))
      .filter((item) => item.frequency > 0.0005)
      .sort((a, b) => b.frequency - a.frequency);
    result.set(key, {
      cell: key,
      actions,
      dominant: actions[0]?.action ?? "",
      ev: entry.ev / weight,
      equity: entry.equity / weight,
      comboCount: entry.comboCount,
    });
  }
  return result;
}

export type ActionTone = "fold" | "check" | "call" | "bet" | "raise" | "allin" | "neutral";

/** Classify a backend action string into the global semantic tone (presentation only). */
export function actionTone(action: string): ActionTone {
  const normalized = action.toLowerCase().replace(/[\s-]/g, "_");
  if (normalized.includes("fold")) return "fold";
  if (normalized.includes("allin") || normalized.includes("all_in") || normalized === "jam") return "allin";
  if (normalized.includes("raise")) return "raise";
  if (normalized.includes("call")) return "call";
  if (normalized.includes("bet")) return "bet";
  if (normalized.includes("check")) return "check";
  return "neutral";
}

/** Human label for a backend action ("bet33" -> "Bet 33%"). */
export function actionLabel(action: string): string {
  const match = /^(bet|raise)\s*(\d+(?:\.\d+)?)?/i.exec(action);
  if (match) {
    const suffix = match[2] ? ` ${match[2].replace(/\.0$/, "")}%` : "";
    return `${match[1][0].toUpperCase()}${match[1].slice(1)}${suffix}`;
  }
  return action.charAt(0).toUpperCase() + action.slice(1);
}
