// 169-cell range editor. The full matrix stays available here; the workspace
// will surface only a compact summary and open this editor on demand.
//
// The editor now has two roles (V1 range belief):
//   - Prior mode: manual 169-cell prior range editor (unchanged legacy UX).
//   - Current / Delta modes: read-only views of the combo-level belief
//     engine's output (matrix169 is a derived view; no fabrication when no
//     grounded policy exists).

import { useState } from "react";
import { RANKS, matrixCell } from "../../lib/poker/matrix";
import type { DefaultRanges, RangeCombo, RangeSide, RangeSummary } from "../../types/scenario";
import type { BeliefMode, RangeBeliefView } from "../../types/rangeBelief";

type Props = {
  rangeSide: RangeSide;
  rangeText: string;
  defaultRanges: DefaultRanges;
  rangeMatrix: Record<string, string>;
  rangeSummary: RangeSummary | null;
  rangeCombos: RangeCombo[];
  belief: RangeBeliefView | null;
  beliefLoading: boolean;
  beliefMode: BeliefMode;
  onRangeSideChange: (side: RangeSide) => void;
  onRangeTextChange: (value: string) => void;
  onApplyDefault: (key: string) => void;
  onParse: () => void;
  onCycleCell: (cell: string) => void;
  onBeliefModeChange: (mode: BeliefMode) => void;
};

const DELTA_FLAT = 0.005;

/** "% of prior reach retained at this node" — the honest engine metric. */
function retainedPercent(belief: RangeBeliefView): string | null {
  if (belief.retainedFraction == null) return null;
  return `${(Number(belief.retainedFraction) * 100).toFixed(1)}%`;
}

export default function RangeEditor({
  rangeSide,
  rangeText,
  defaultRanges,
  rangeMatrix,
  rangeSummary,
  rangeCombos,
  belief,
  beliefLoading,
  beliefMode,
  onRangeSideChange,
  onRangeTextChange,
  onApplyDefault,
  onParse,
  onCycleCell,
  onBeliefModeChange,
}: Props) {
  // The full 169 matrix is heavy; the workspace starts expanded but the
  // editor can collapse into a compact summary so it never permanently
  // occupies primary space.
  const [expanded, setExpanded] = useState(true);
  const [selectedCell, setSelectedCell] = useState<string | null>(null);
  const seatLabel = rangeSide === "heroRange" ? "Hero" : "Villain";

  return (
    <section className="panel compact-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">02 · RANGE</p>
          <h2>{seatLabel} 起始范围（Prior）</h2>
        </div>
        <div className="heading-actions">
          <span className="source-tag">Prior</span>
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

      <div className="range-view-tabs" role="group" aria-label="Range View">
        <button
          type="button"
          className={beliefMode === "prior" ? "range-view-tab range-view-tab--active" : "range-view-tab"}
          aria-label="belief mode prior"
          aria-pressed={beliefMode === "prior"}
          onClick={() => onBeliefModeChange("prior")}
        >
          编辑 Prior
        </button>
        <button
          type="button"
          className={beliefMode === "current" ? "range-view-tab range-view-tab--active" : "range-view-tab"}
          aria-label="belief mode current"
          aria-pressed={beliefMode === "current"}
          onClick={() => onBeliefModeChange("current")}
        >
          Current
        </button>
        <button
          type="button"
          className={beliefMode === "delta" ? "range-view-tab range-view-tab--active" : "range-view-tab"}
          aria-label="belief mode delta"
          aria-pressed={beliefMode === "delta"}
          onClick={() => onBeliefModeChange("delta")}
        >
          Δ
        </button>
      </div>

      {!expanded ? (
        <div className="range-compact" aria-label="range summary compact">
          <span className="range-compact__name">{seatLabel} 起始范围</span>
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
      ) : beliefMode !== "prior" ? (
        <BeliefView
          belief={belief}
          loading={beliefLoading}
          mode={beliefMode}
          seatLabel={seatLabel}
          selectedCell={selectedCell}
          onSelectCell={setSelectedCell}
        />
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
        点击矩阵格循环设置 0.25 / 0.5 / 0.75 / 1 权重；每次变化都由后端重新标准化。这是
        <strong>起始范围（Prior）</strong>，Current 与 Δ 由行动策略更新引擎生成。
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

function BeliefView({
  belief,
  loading,
  mode,
  seatLabel,
  selectedCell,
  onSelectCell,
}: {
  belief: RangeBeliefView | null;
  loading: boolean;
  mode: "current" | "delta";
  seatLabel: string;
  selectedCell: string | null;
  onSelectCell: (cell: string | null) => void;
}) {
  if (loading) {
    return <p className="muted small">正在计算 {seatLabel} 的 range belief…</p>;
  }
  if (!belief || !belief.available || !belief.matrix169) {
    return (
      <div className="belief-unavailable" aria-label="current range unavailable">
        <p className="belief-unavailable__title">Current range unavailable</p>
        <p className="muted small">
          No grounded action policy is available for this node.
        </p>
        {belief?.unavailableReason ? (
          <p className="muted small belief-unavailable__reason">{belief.unavailableReason}</p>
        ) : null}
        <p className="muted small">You can still edit the Prior range manually.</p>
      </div>
    );
  }

  const nodeLabel = beliefNodeLabel(belief);
  const sourceLabel = beliefSourceLabel(belief);
  const retained = retainedPercent(belief);
  const detail = selectedCell ? belief.matrix169[selectedCell] : null;

  return (
    <div className="belief-view" aria-label="belief view">
      <div className="belief-meta">
        {nodeLabel ? (
          <p className="muted small">
            Node · <strong>{nodeLabel}</strong>
          </p>
        ) : null}
        <p className="muted small">
          Source · <strong>{sourceLabel}</strong>
        </p>
        {retained ? (
          <p className="muted small">
            Retained reach · <strong>{retained}</strong>
          </p>
        ) : null}
        {belief.update?.offTree ? (
          <p className="muted small belief-offtree">
            off-tree sizing approximation · observed {formatSize(belief.update.observedSize)} → mapped{" "}
            {formatSize(belief.update.mappedSize)}
          </p>
        ) : null}
      </div>
      <div className="range-matrix range-matrix--readonly" aria-label="belief 范围矩阵">
        {RANKS.map((row, rowIndex) =>
          RANKS.map((column, columnIndex) => {
            const cell = matrixCell(rowIndex, columnIndex);
            const entry = belief.matrix169![cell];
            const tone = mode === "delta" ? deltaTone(entry?.delta) : currentTone(entry?.probabilityMass);
            const value =
              mode === "delta"
                ? formatDelta(entry?.delta)
                : formatPercent(entry?.probabilityMass);
            return (
              <button
                type="button"
                className={`matrix-cell matrix-cell--belief ${tone} ${selectedCell === cell ? "active" : ""}`}
                key={cell}
                title={beliefCellTitle(entry, cell)}
                aria-label={`belief cell ${cell}`}
                onClick={() => onSelectCell(selectedCell === cell ? null : cell)}
              >
                {cell}
                {entry && value ? <small>{value}</small> : null}
              </button>
            );
          }),
        )}
      </div>
      {detail ? (
        <div className="belief-detail" aria-label={`belief detail ${selectedCell}`}>
          <p className="belief-detail__cell">{selectedCell}</p>
          <p className="muted small">
            Prior <strong>{formatPercent(detail.priorProbabilityMass)}</strong> · Current{" "}
            <strong>{formatPercent(detail.probabilityMass)}</strong> · Δ{" "}
            <strong className={deltaTone(detail.delta)}>{formatDelta(detail.delta)}</strong>
            {detail.multiplier != null ? (
              <>
                {" "}
                · <strong>{formatMultiplier(detail.multiplier)}</strong>
              </>
            ) : null}
          </p>
        </div>
      ) : (
        <p className="muted small">点击任一格查看 Prior / Current / Δ 详情。</p>
      )}
    </div>
  );
}

function beliefNodeLabel(belief: RangeBeliefView): string | null {
  if (!belief.street) return null;
  const action = belief.update?.actionLabel;
  if (!action) return belief.street;
  const actionLabel = action.replace(/^deal /i, "Deal ").replace(/^deal_/i, "Deal ");
  return `${belief.street} · after ${actionLabel}`;
}

function beliefSourceLabel(belief: RangeBeliefView): string | null {
  switch (belief.source) {
    case "solver":
      return "solver-backed";
    case "fixture":
      return "fixture / manual policy";
    case "manual":
      return "manual prior";
    default:
      return belief.source;
  }
}

function currentTone(probabilityMass: string | undefined): string {
  const value = probabilityMass == null ? 0 : Number(probabilityMass);
  if (value <= 0) return "belief-cell--empty";
  if (value >= 0.05) return "belief-cell--high";
  if (value >= 0.015) return "belief-cell--mid";
  return "belief-cell--low";
}

function deltaTone(delta: string | undefined): string {
  const value = delta == null ? 0 : Number(delta);
  if (Math.abs(value) < DELTA_FLAT) return "belief-cell--flat";
  if (value > 0) return "belief-cell--up";
  return "belief-cell--down";
}

function formatPercent(value: string | undefined): string {
  if (value == null) return "";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatDelta(delta: string | undefined): string {
  if (delta == null) return "";
  const value = Number(delta);
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}pp`;
}

function formatMultiplier(multiplier: string): string {
  return `${Number(multiplier).toFixed(2)}×`;
}

function formatSize(size: string | null): string {
  if (size == null) return "?";
  return (Number(size) * 100).toFixed(0) + "%";
}

function beliefCellTitle(
  entry: { probabilityMass: string; priorProbabilityMass: string; delta: string } | undefined,
  cell: string,
): string {
  if (!entry) return `${cell} · no mass`;
  return `${cell} · Prior ${formatPercent(entry.priorProbabilityMass)} · Current ${formatPercent(
    entry.probabilityMass,
  )} · Δ ${formatDelta(entry.delta)}`;
}
