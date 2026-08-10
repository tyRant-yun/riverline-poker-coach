// 169-cell range editor. The full matrix stays available here; the workspace
// will surface only a compact summary and open this editor on demand.

import { RANKS, matrixCell } from "../../lib/poker/matrix";
import type { DefaultRanges, RangeCombo, RangeSide, RangeSummary } from "../../types/scenario";

type Props = {
  rangeSide: RangeSide;
  rangeText: string;
  defaultRanges: DefaultRanges;
  rangeMatrix: Record<string, string>;
  rangeSummary: RangeSummary | null;
  rangeCombos: RangeCombo[];
  onRangeSideChange: (side: RangeSide) => void;
  onRangeTextChange: (value: string) => void;
  onApplyDefault: (key: string) => void;
  onParse: () => void;
  onCycleCell: (cell: string) => void;
};

export default function RangeEditor({
  rangeSide,
  rangeText,
  defaultRanges,
  rangeMatrix,
  rangeSummary,
  rangeCombos,
  onRangeSideChange,
  onRangeTextChange,
  onApplyDefault,
  onParse,
  onCycleCell,
}: Props) {
  return (
    <section className="panel compact-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">02 · RANGE</p>
          <h2>{rangeSide === "heroRange" ? "Hero" : "Villain"} 范围</h2>
        </div>
        <span className="source-tag">假设</span>
      </div>
      <div className="range-controls">
        <label>
          编辑对象
          <select
            aria-label="范围侧"
            value={rangeSide}
            onChange={(event) => onRangeSideChange(event.target.value as RangeSide)}
          >
            <option value="villainRange">Villain 范围</option>
            <option value="heroRange">Hero 范围</option>
          </select>
        </label>
        <label>
          默认范围
          <select
            aria-label="默认范围"
            defaultValue=""
            onChange={(event) => onApplyDefault(event.target.value)}
          >
            <option value="">选择默认范围</option>
            {Object.entries(defaultRanges).map(([key, item]) => (
              <option key={key} value={key}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <textarea
        value={rangeText}
        onChange={(event) => onRangeTextChange(event.target.value)}
        aria-label="range notation"
      />
      <button className="secondary-button" onClick={onParse}>
        标准化范围
      </button>
      <div className="range-matrix" aria-label="169 格范围矩阵">
        {RANKS.map((row, rowIndex) =>
          RANKS.map((column, columnIndex) => {
            const cell = matrixCell(rowIndex, columnIndex);
            const weight = rangeMatrix[cell];
            return (
              <button
                type="button"
                className={`matrix-cell ${weight ? "active" : ""}`}
                key={cell}
                title={weight ? `${cell} · ${weight}` : `${cell} · empty`}
                aria-label={`${cell} weight`}
                onClick={() => onCycleCell(cell)}
              >
                {cell}
                {weight && <small>{weight}</small>}
              </button>
            );
          }),
        )}
      </div>
      <p className="muted small">
        点击矩阵格循环设置 0.25 / 0.5 / 0.75 / 1 权重；每次变化都由后端重新标准化。
      </p>
      {rangeSummary && (
        <p className="range-summary">
          有效组合：<strong>{rangeSummary.totalCombos}</strong> · 加权组合：
          <strong>{rangeSummary.weightedCombos}</strong> · 已展开：{rangeCombos.length}
        </p>
      )}
    </section>
  );
}
