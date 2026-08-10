// Chip amount formatting for poker display. The backend always speaks in
// chips; the UI can present amounts either as chips or as big blinds.
// Big blind is the poker-native unit, so it is the default display mode.

export type DisplayUnit = "bb" | "chips";

export function toBigBlinds(chips: number, bigBlind: number): number {
  if (bigBlind <= 0 || !Number.isFinite(chips)) return 0;
  return chips / bigBlind;
}

/** 150 chips / BB 100 -> "1.5 BB"; 10000 -> "100 BB"; 50 -> "0.5 BB". */
export function formatBigBlinds(chips: number, bigBlind: number): string {
  const bb = toBigBlinds(chips, bigBlind);
  const rounded = Math.round(bb * 100) / 100;
  const text = Number.isInteger(rounded)
    ? String(rounded)
    : rounded.toFixed(2).replace(/\.?0+$/, "");
  return `${text} BB`;
}

/** 9900 -> "9,900" (chips mode). */
export function formatChips(chips: number): string {
  return Math.round(chips).toLocaleString("en-US");
}

/** Format an amount in the requested unit; BB is the default. */
export function formatAmount(chips: number, bigBlind: number, unit: DisplayUnit): string {
  return unit === "bb" ? formatBigBlinds(chips, bigBlind) : formatChips(chips);
}

/** Short BB value without the unit suffix (for hints like "= 2 BB" reuse). */
export function bigBlindValue(chips: number, bigBlind: number): string {
  return formatBigBlinds(chips, bigBlind).replace(/ BB$/, "");
}
