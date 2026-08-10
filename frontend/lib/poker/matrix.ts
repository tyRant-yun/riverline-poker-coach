// 169-cell starting-hand matrix helpers (shared by the range editor and the
// future solver strategy/EV/equity grids).

export const RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"] as const;

/** 13x13 cell label: pairs "AA", suited "AKs", offsuit "AKo". */
export function matrixCell(row: number, column: number): string {
  if (row === column) return `${RANKS[row]}${RANKS[column]}`;
  const high = RANKS[Math.min(row, column)];
  const low = RANKS[Math.max(row, column)];
  return `${high}${low}${row < column ? "s" : "o"}`;
}

/** Matrix -> compact notation, omitting the explicit "1" weight. */
export function notationFromMatrix(matrix: Record<string, string>): string {
  return Object.entries(matrix)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([hand, weight]) => `${hand}${weight === "1" ? "" : `@${weight}`}`)
    .join(" ");
}

/** Matrix -> notation with every weight spelled out ("AKs@0.5 ..."). */
export function notationFromMatrixExplicit(matrix: Record<string, string>): string {
  return Object.entries(matrix)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([hand, weight]) => `${hand}@${weight}`)
    .join(" ");
}
