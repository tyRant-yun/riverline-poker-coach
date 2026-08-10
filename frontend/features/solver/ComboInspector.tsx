// Combo Inspector: real combos of a selected hand class with per-combo
// strategy mixture (semantic colors), EV, equity and weight. This is the
// future blocker-teaching surface — data comes straight from the solver node.

import { useMemo, useState } from "react";
import type { SolverNodePayload } from "../../types/api";
import { actionLabel, actionTone, cellKey } from "../../lib/solver/aggregate";
import { formatCard } from "../../lib/poker/cards";

type Props = {
  node: SolverNodePayload | null | undefined;
  cell: string;
};

export default function ComboInspector({ node, cell }: Props) {
  const [openCombo, setOpenCombo] = useState<string | null>(null);

  const combos = useMemo(
    () => (node?.hands ?? []).filter((hand) => cellKey(hand.combo) === cell),
    [node, cell],
  );

  return (
    <div className="combo-inspector" aria-label={`combo inspector ${cell}`}>
      <p className="eyebrow">COMBOS · {cell}</p>
      {combos.length === 0 ? (
        <p className="muted small">该手牌类不在当前节点求解范围内。</p>
      ) : (
        <div className="combo-list">
          {combos.map((hand) => {
            const open = openCombo === hand.combo;
            const top = Object.entries(hand.strategy).sort((a, b) => b[1] - a[1])[0];
            return (
              <div className={`combo-row ${open ? "combo-row--open" : ""}`} key={hand.combo}>
                <button
                  type="button"
                  className="combo-row__head"
                  aria-expanded={open}
                  onClick={() => setOpenCombo(open ? null : hand.combo)}
                >
                  <span className="combo-row__cards">
                    {formatCard(hand.combo.slice(0, 2))} {formatCard(hand.combo.slice(2, 4))}
                  </span>
                  <span className="combo-row__primary">
                    {top ? (
                      <>
                        <span className={`sg-dot sg-dot--${actionTone(top[0])}`} />
                        {actionLabel(top[0])} {Math.round(top[1] * 100)}%
                      </>
                    ) : null}
                  </span>
                  <span className="combo-row__meta">
                    EV {hand.ev >= 0 ? "+" : ""}
                    {hand.ev.toFixed(2)}
                  </span>
                </button>
                {open && (
                  <div className="combo-detail">
                    <div className="combo-detail__bars">
                      {Object.entries(hand.strategy)
                        .sort((a, b) => b[1] - a[1])
                        .map(([action, frequency]) => (
                          <div className="combo-bar" key={action}>
                            <span className="combo-bar__label">
                              <span className={`sg-dot sg-dot--${actionTone(action)}`} />
                              {actionLabel(action)}
                            </span>
                            <div className="combo-bar__track">
                              <div
                                className={`combo-bar__fill combo-bar__fill--${actionTone(action)}`}
                                style={{ width: `${Math.round(frequency * 100)}%` }}
                              />
                            </div>
                            <span className="combo-bar__value">{Math.round(frequency * 100)}%</span>
                          </div>
                        ))}
                    </div>
                    <div className="combo-detail__stats">
                      <span>
                        EV <strong>{hand.ev >= 0 ? "+" : ""}{hand.ev.toFixed(2)}</strong>
                      </span>
                      <span>
                        Equity <strong>{(hand.equity * 100).toFixed(1)}%</strong>
                      </span>
                      <span>
                        Weight <strong>{hand.weight.toFixed(3)}</strong>
                      </span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
