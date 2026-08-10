// Primary action control for the table. Strictly renders the backend's legal
// actions (state.legalActions) — it never guesses legality. Amount semantics
// follow the backend contract: call -> cost, bet -> by, raise_to/all_in -> to.

import type { LegalActions } from "../../types/api";

export type { LegalActions };

type Props = {
  legal: LegalActions | null;
  currentStreet: string;
  busy: boolean;
  boardLength: number;
  raiseAmount: number | "";
  onRaiseAmountChange: (value: number | "") => void;
  onAction: (actionType: string, requestedAmount?: number) => void;
  onDeal: (street: "deal_flop" | "deal_turn" | "deal_river") => void;
};

export default function ActionBar({
  legal,
  currentStreet,
  busy,
  boardLength,
  raiseAmount,
  onRaiseAmountChange,
  onAction,
  onDeal,
}: Props) {
  const actions = legal?.actions ?? [];
  const hasSizing = actions.includes("bet") || actions.includes("raise_to");
  return (
    <div className="action-box">
      <div className="action-header">
        <span>当前节点 · {currentStreet}</span>
        <span className="muted">行动者 Seat {legal?.actorSeat ?? 0}</span>
      </div>
      <div className="action-buttons">
        {actions.includes("check") && (
          <button onClick={() => onAction("check")} disabled={busy}>
            Check
          </button>
        )}
        {actions.includes("call") && (
          <button onClick={() => onAction("call")} disabled={busy}>
            Call {legal?.callAmount}
          </button>
        )}
        {actions.includes("bet") && (
          <button
            onClick={() => onAction("bet", raiseAmount === "" ? undefined : raiseAmount)}
            disabled={busy}
          >
            Bet {raiseAmount || legal?.minRaiseTo}
          </button>
        )}
        {actions.includes("raise_to") && (
          <button
            onClick={() => onAction("raise_to", raiseAmount === "" ? undefined : raiseAmount)}
            disabled={busy}
          >
            Raise to {raiseAmount || legal?.minRaiseTo}
          </button>
        )}
        {actions.includes("all_in") && (
          <button onClick={() => onAction("all_in")} disabled={busy}>
            All-in
          </button>
        )}
        {actions.includes("fold") && (
          <button className="quiet" onClick={() => onAction("fold")} disabled={busy}>
            Fold
          </button>
        )}
        {currentStreet === "preflop" && (
          <button
            className="quiet"
            onClick={() => onDeal("deal_flop")}
            disabled={busy || boardLength < 3}
          >
            Deal flop
          </button>
        )}
        {currentStreet === "flop" && (
          <button
            className="quiet"
            onClick={() => onDeal("deal_turn")}
            disabled={busy || boardLength < 4}
          >
            Deal turn
          </button>
        )}
        {currentStreet === "turn" && (
          <button
            className="quiet"
            onClick={() => onDeal("deal_river")}
            disabled={busy || boardLength < 5}
          >
            Deal river
          </button>
        )}
      </div>
      {hasSizing && (
        <label className="amount-input">
          下注 / raise-to
          <input
            type="number"
            min={legal?.minRaiseTo ?? 0}
            max={legal?.maxRaiseTo ?? undefined}
            value={raiseAmount === "" ? legal?.minRaiseTo ?? "" : raiseAmount}
            onChange={(event) =>
              onRaiseAmountChange(event.target.value === "" ? "" : Number(event.target.value))
            }
          />
        </label>
      )}
    </div>
  );
}
