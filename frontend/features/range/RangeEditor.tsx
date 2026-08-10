// 169-cell range editor. The full matrix stays available here; the workspace
// will surface only a compact summary and open this editor on demand.

import { useState } from "react";
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
  // The full 169 matrix is heavy; the workspace starts expanded but the
  // editor can collapse into a compact summary so it never permanently
  // occupies primary space.
  const [expanded, setExpanded] = useState(true);
  return (
    <section className="panel compact-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">02 · RANGE</p>
          <h2>{rangeSide === "heroRange" ? "Hero" : "Villain"} 范围</h2>
        </div>
        <div className="heading-actions">
          <span className="source-tag">假设</span>
          {expanded ? (
            <button className="text-button" onClick={() => setExpanded(false)} aria-label="收起范围矩阵">
              收起矩阵
            </button>
          ) : (
            <button className="text-button" onClick={() => setExpanded(true)} aria-label="编辑范围">
              编辑范围
            </button>
          )}
        </div>
      </div>
      {!expanded ? (
        <div className="range-compact" aria-label="range summary compact">
          <span className="range-compact__name">
            {rangeSide === "heroRange" ? "Hero" : "Villain"} 范围
          </span>
          {rangeSummary ? (
            <span className="muted small">
              加权组合：<strong>{rangeSummary.weightedCombos}</strong> · {Object.keys(rangeMatrix).length} 格
            </span>
          ) : (
            <span className="muted small">尚未标准化</span>
          )}
          <button className="secondary-button" onClick={() => setExpanded(true)}>
            编辑范围
          </button>
        </div>
      ) : (
        <>
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
            const weightClass = weight ? `matrix-cell--w${Math.round(Number(weight) * 100)}` : "";
            return (
              <button
                type="button"
                className={`matrix-cell ${weight ? "active" : ""} ${weightClass}`}
                key={cell}
                title={weight ? `${cell} · Weight ${weight}` : `${cell} · empty`}
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
        </>
      )}
    </section>
  );
}
