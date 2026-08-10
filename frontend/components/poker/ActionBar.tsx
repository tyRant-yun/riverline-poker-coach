// Primary action control for the table. Strictly renders the backend's legal
// actions (state.legalActions) — it never guesses legality. Amount semantics
// follow the backend contract: call -> cost, bet -> by, raise_to/all_in -> to.
// Amounts display in the active unit (BB by default); the sizing INPUT stays
// in chips and the backend wire values are never touched.

import type { LegalActions } from "../../types/api";
import type { DisplayUnit } from "../../lib/poker/format";
import { formatAmount, formatBigBlinds } from "../../lib/poker/format";
import { positionLabel } from "../../lib/poker/positions";

export type { LegalActions };

type Props = {
  legal: LegalActions | null;
  currentStreet: string;
  busy: boolean;
  boardLength: number;
  raiseAmount: number | "";
  pot?: number | null;
  actorPosition?: string | null;
  unit?: DisplayUnit;
  bigBlind?: number;
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
  pot,
  actorPosition,
  unit = "bb",
  bigBlind = 100,
  onRaiseAmountChange,
  onAction,
  onDeal,
}: Props) {
  const actions = legal?.actions ?? [];
  const hasSizing = actions.includes("bet") || actions.includes("raise_to");
  const sizingAmount = raiseAmount === "" ? legal?.minRaiseTo ?? 0 : raiseAmount;
  const bbMode = unit === "bb";

  // Accessible names keep the chip amount first ("Call 50（0.5 BB）") so the
  // E2E "Call 50" hook keeps matching while the visual reads in big blinds.
  const actionName = (label: string, chips: number) =>
    bbMode ? `${label} ${chips}（${formatBigBlinds(chips, bigBlind)}）` : `${label} ${chips}`;

  return (
    <div className="action-box">
      <div className="action-header">
        <div className="action-header__node">
          <span className="action-street">{currentStreet.toUpperCase()}</span>
          <span className="muted">
            行动者{" "}
            {actorPosition
              ? `${positionLabel(actorPosition)} · Seat ${legal?.actorSeat ?? 0}`
              : `Seat ${legal?.actorSeat ?? 0}`}
          </span>
        </div>
        {pot != null && (
          <div className="action-pot" title={`${pot} chips`}>
            <span>POT</span>
            <strong>{formatAmount(pot, bigBlind, unit)}</strong>
          </div>
        )}
      </div>
      <div className="action-buttons">
        {actions.includes("check") && (
          <button
            className="action-btn action-btn--check"
            onClick={() => onAction("check")}
            disabled={busy}
          >
            Check
          </button>
        )}
        {actions.includes("call") && (
          <button
            className="action-btn action-btn--call"
            onClick={() => onAction("call")}
            disabled={busy}
            aria-label={legal?.callAmount != null ? actionName("Call", legal.callAmount) : "Call"}
          >
            <span className="action-btn__label">Call</span>
            {legal?.callAmount != null && (
              <>
                <strong className="action-btn__amount">
                  {bbMode ? formatBigBlinds(legal.callAmount, bigBlind) : legal.callAmount}
                </strong>
                {bbMode && <small className="action-btn__hint">{legal.callAmount} chips</small>}
              </>
            )}
          </button>
        )}
        {actions.includes("bet") && (
          <button
            className="action-btn action-btn--bet"
            onClick={() => onAction("bet", raiseAmount === "" ? undefined : raiseAmount)}
            disabled={busy}
            aria-label={actionName("Bet", sizingAmount)}
          >
            <span className="action-btn__label">Bet</span>
            <strong className="action-btn__amount">
              {bbMode ? formatBigBlinds(sizingAmount, bigBlind) : sizingAmount}
            </strong>
          </button>
        )}
        {actions.includes("raise_to") && (
          <button
            className="action-btn action-btn--raise"
            onClick={() => onAction("raise_to", raiseAmount === "" ? undefined : raiseAmount)}
            disabled={busy}
            aria-label={actionName("Raise to", sizingAmount)}
          >
            <span className="action-btn__label">Raise to</span>
            <strong className="action-btn__amount">
              {bbMode ? formatBigBlinds(sizingAmount, bigBlind) : sizingAmount}
            </strong>
          </button>
        )}
        {actions.includes("all_in") && (
          <button
            className="action-btn action-btn--allin"
            onClick={() => onAction("all_in")}
            disabled={busy}
          >
            All-in
          </button>
        )}
        {actions.includes("fold") && (
          <button className="action-btn action-btn--fold" onClick={() => onAction("fold")} disabled={busy}>
            Fold
          </button>
        )}
        {currentStreet === "preflop" && (
          <button
            className="action-btn action-btn--deal"
            onClick={() => onDeal("deal_flop")}
            disabled={busy || boardLength < 3}
          >
            Deal flop
          </button>
        )}
        {currentStreet === "flop" && (
          <button
            className="action-btn action-btn--deal"
            onClick={() => onDeal("deal_turn")}
            disabled={busy || boardLength < 4}
          >
            Deal turn
          </button>
        )}
        {currentStreet === "turn" && (
          <button
            className="action-btn action-btn--deal"
            onClick={() => onDeal("deal_river")}
            disabled={busy || boardLength < 5}
          >
            Deal river
          </button>
        )}
      </div>
      {hasSizing && (
        <div className="amount-input">
          <label>
            下注 / raise-to（chips）
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
          {bbMode && <small className="amount-input__hint">= {formatBigBlinds(sizingAmount, bigBlind)}</small>}
        </div>
      )}
    </div>
  );
}
