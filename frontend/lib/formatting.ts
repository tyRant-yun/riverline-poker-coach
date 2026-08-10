// Number formatting helpers for chips / BB / EV display.

/** 12345 -> "12,345"; null/undefined -> "—". */
export function formatChips(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US");
}

/** BB units with one decimal when needed: 12 -> "12BB", 12.5 -> "12.5BB". */
export function formatBb(value: number | null | undefined, bigBlind: number): string {
  if (value === null || value === undefined || bigBlind <= 0) return "—";
  const bb = value / bigBlind;
  const rounded = Math.round(bb * 100) / 100;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(2)}BB`;
}

/** Solver EV / equity values: keep 2-3 significant decimals without forcing zeros. */
export function formatEv(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(2);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(0)}%`;
}
