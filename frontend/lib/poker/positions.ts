// Seat position labels. The backend currently only emits button / big_blind;
// this map is written to extend to 8-max positions (utg, mp, hj, co, sb) once
// the backend derives them, without touching table layout code.

const POSITION_LABELS: Record<string, string> = {
  button: "BTN",
  big_blind: "BB",
  small_blind: "SB",
  utg: "UTG",
  "utg+1": "UTG+1",
  mp: "MP",
  hj: "HJ",
  co: "CO",
};

export function positionLabel(position: string): string {
  const key = position.trim().toLowerCase();
  return POSITION_LABELS[key] ?? position.toUpperCase();
}
