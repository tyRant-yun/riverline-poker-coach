// 13x13 starting-hand strategy/EV/equity grid. Cells are weighted
// aggregations of the backend solver node (see lib/solver/aggregate.ts).
// Action mixtures use the global action semantic colors.

import { useMemo } from "react";
import { RANKS, matrixCell } from "../../lib/poker/matrix";
import { actionLabel, actionTone, type CellAggregate } from "../../lib/solver/aggregate";

export type StrategyGridMode = "strategy" | "ev" | "equity";

type Props = {
  cells: Map<string, CellAggregate>;
  mode: StrategyGridMode;
  activeCell: string | null;
  onSelectCell: (cell: string | null) => void;
};

/** Diverging red -> green heat for EV (negative to positive). */
function evHeat(value: number, min: number, max: number): string {
  if (max === min) return "rgba(91, 147, 255, 0.16)";
  const t = Math.min(1, Math.max(0, (value - min) / (max - min)));
  const red = Math.round(255 * (1 - t));
  const green = Math.round(255 * t);
  return `rgba(${red}, ${green}, 100, 0.24)`;
}

/** Single-hue green heat for equity 0..1. */
function equityHeat(value: number): string {
  const alpha = 0.05 + 0.3 * Math.min(1, Math.max(0, value));
  return `rgba(52, 201, 141, ${alpha.toFixed(3)})`;
}

export default function StrategyGrid({ cells, mode, activeCell, onSelectCell }: Props) {
  const range = useMemo(() => {
    let min = 0;
    let max = 0;
    if (mode === "ev") {
      const values = [...cells.values()].map((cell) => cell.ev);
      if (values.length) {
        min = Math.min(...values);
        max = Math.max(...values);
      }
    }
    return { min, max };
  }, [cells, mode]);

  return (
    <div className={`sg-grid sg-grid--${mode}`} aria-label="solver strategy grid" role="grid">
      <div className="sg-corner" />
      {RANKS.map((rank) => (
        <div className="sg-header" key={`col-${rank}`}>
          {rank}
        </div>
      ))}
      {RANKS.map((row, rowIndex) => (
        <div className="sg-row" key={`row-${row}`} role="row">
          <div className="sg-header">{RANKS[rowIndex]}</div>
          {RANKS.map((_, columnIndex) => {
            const cell = matrixCell(rowIndex, columnIndex);
            const aggregate = cells.get(cell);
            const isActive = activeCell === cell;
            const className = [
              "sg-cell",
              isActive ? "sg-cell--active" : "",
              aggregate ? "" : "sg-cell--empty",
            ].join(" ");
            const style: React.CSSProperties | undefined =
              mode === "ev" && aggregate
                ? { background: evHeat(aggregate.ev, range.min, range.max) }
                : mode === "equity" && aggregate
                  ? { background: equityHeat(aggregate.equity) }
                  : undefined;
            return (
              <button
                type="button"
                key={cell}
                className={className}
                style={style}
                role="gridcell"
                aria-label={`${cell} ${mode}${aggregate ? ` ${aggregate.actions.map((a) => `${a.action} ${Math.round(a.frequency * 100)}%`).join(" ")}` : " empty"}`}
                title={aggregate ? `${cell}\n${aggregate.actions.map((a) => `${actionLabel(a.action)} ${Math.round(a.frequency * 100)}%`).join("\n")}` : `${cell} — 不在求解范围`}
                onClick={() => onSelectCell(isActive ? null : cell)}
              >
                {!aggregate ? null : mode === "strategy" ? (
                  <span className={`sg-cell__actions sg-cell__actions--${actionTone(aggregate.dominant)}`}>
                    {aggregate.actions.slice(0, 2).map((item) => (
                      <span className="sg-action" key={item.action}>
                        <em className={`sg-dot sg-dot--${actionTone(item.action)}`} />
                        {actionLabel(item.action)} {Math.round(item.frequency * 100)}%
                      </span>
                    ))}
                  </span>
                ) : mode === "ev" ? (
                  <span className="sg-cell__value">
                    {aggregate.ev >= 0 ? "+" : ""}
                    {aggregate.ev.toFixed(2)}
                  </span>
                ) : (
                  <span className="sg-cell__value">{(aggregate.equity * 100).toFixed(0)}%</span>
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
