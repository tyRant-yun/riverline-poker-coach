// Solver workspace: job lifecycle UX (idle/queued/running/solved/failed/
// cancelled/cancellation_requested with cancel), solver metadata, and the
// strategy / EV / equity grids with combo inspection. All numbers come from
// the backend SolveJob payload; the frontend only re-aggregates per-cell.

import { useMemo, useState } from "react";
import type { SolveJob, SolverNodePayload } from "../../types/api";
import type { ReviewSolverAssessment } from "../../types/handReview";
import type { SolveGateReasons } from "../../lib/poker/solve";
import {
  ACTIVE_SOLVE_STATUSES,
  solveStatus,
  SOLVE_STATUS_META,
} from "../../lib/solver/status";
import { aggregateNode } from "../../lib/solver/aggregate";
import StrategyGrid, { type StrategyGridMode } from "../../components/solver/StrategyGrid";
import ComboInspector from "./ComboInspector";
import NodeNavigator from "./NodeNavigator";
import SolverAssessment from "./SolverAssessment";

type Props = {
  solveJob: SolveJob | null;
  canSubmit: boolean;
  heroHoleCards: string[];
  /** Per-condition gate state, shown when submit is disabled. */
  gate?: SolveGateReasons | null;
  onSubmit: () => void;
  onCancel: () => void;
  /** Optional selected-decision assessment; page/FE-06 may supply it later. */
  solverAssessment?: ReviewSolverAssessment | null;
};

const NODE_OPTIONS: { id: "root" | "response"; label: string }[] = [
  { id: "root", label: "OOP 节点" },
  { id: "response", label: "IP 响应" },
];

const MODE_OPTIONS: { id: StrategyGridMode; label: string }[] = [
  { id: "strategy", label: "Strategy" },
  { id: "ev", label: "EV" },
  { id: "equity", label: "Equity" },
];

export default function SolverWorkspace({ solveJob, canSubmit, heroHoleCards, gate, onSubmit, onCancel, solverAssessment }: Props) {
  const [nodeId, setNodeId] = useState<"root" | "response">("root");
  const [mode, setMode] = useState<StrategyGridMode>("strategy");
  const [activeCell, setActiveCell] = useState<string | null>(null);

  const status = solveStatus(solveJob?.status);
  const node: SolverNodePayload | null | undefined =
    nodeId === "root" ? solveJob?.result?.root : solveJob?.result?.responseNode;
  const cells = useMemo(() => aggregateNode(node), [node]);
  const metadata = solveJob?.result?.metadata;

  const statusMeta = SOLVE_STATUS_META[status];

  return (
    <section className="panel solve-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">06 · SOLVER</p>
          <h2>Solver 策略求解</h2>
        </div>
        <div className="heading-actions">
          <span className={`solve-status solve-status--${statusMeta.tone}`}>{statusMeta.label}</span>
          {ACTIVE_SOLVE_STATUSES.has(status) && solveJob && (
            <button className="danger-button solve-cancel" onClick={onCancel}>
              取消求解
            </button>
          )}
        </div>
      </div>

      {solveJob?.spot?.assumptions?.includes("bunching_ignored") && (
        <p className="muted small solve-assumption">
          近似假设：bunching_ignored — 本决策点源自多人桌，已弃牌玩家的手牌对剩余牌堆的影响被忽略（标准 HU 近似）。
        </p>
      )}

      {solverAssessment ? <SolverAssessment assessment={solverAssessment} /> : null}

      {status === "idle" || status === "failed" || status === "cancelled" ? (
        <div className="action-buttons">
          <button onClick={onSubmit} disabled={!canSubmit}>
            提交 Solver 求解（独立容器）
          </button>
          <p className="muted small">
            需要两个仍在局中的玩家的范围（HU 用 Hero/Villain 范围，多人桌用 rangesBySeat）。求解约 1–3 分钟。
            {status !== "idle" && solveJob?.error ? ` · ${solveJob.error}` : ""}
          </p>
          {gate && !canSubmit && (
            <ul className="solve-gate" aria-label="solver 提交条件">
              <li className={gate.postflop ? "solve-gate__ok" : "solve-gate__no"}>
                {gate.postflop ? "✓" : "✗"} 翻后节点（flop / turn / river）
              </li>
              <li className={gate.twoActive ? "solve-gate__ok" : "solve-gate__no"}>
                {gate.twoActive ? "✓" : "✗"} 仅剩 2 位 active players
              </li>
              <li className={gate.ranges ? "solve-gate__ok" : "solve-gate__no"}>
                {gate.ranges ? "✓" : "✗"} 两位玩家范围就绪
              </li>
            </ul>
          )}
        </div>
      ) : status === "queued" || status === "running" || status === "cancellation_requested" ? (
        <div className="solve-progress">
          <p className="muted">
            {status === "queued"
              ? "已排队，等待 Solver worker 领取…"
              : status === "cancellation_requested"
                ? "正在取消（协作式取消，等待 worker 响应）…"
                : "求解进行中（独立 sidecar 容器）…"}
          </p>
          {metadata ? (
            <div className="solve-metrics">
              <SolveMetric label="引擎" value={`${metadata.solver} ${metadata.version}`} />
              <SolveMetric label="迭代" value={String(metadata.maxIterations)} />
              <SolveMetric label="目标 exploitability" value={metadata.targetExploitabilityChips.toFixed(4)} />
            </div>
          ) : null}
        </div>
      ) : status === "solved" && solveJob?.result ? (
        <>
          <div className="solve-metrics">
            <SolveMetric label="引擎" value={`${metadata?.solver ?? "—"} ${metadata?.version ?? ""}`} />
            <SolveMetric label="迭代" value={String(metadata?.maxIterations ?? "—")} />
            <SolveMetric label="exploitability" value={`${metadata?.exploitabilityChips.toFixed(3) ?? "—"} chips`} />
            <SolveMetric label="耗时" value={`${((metadata?.solveTimeMs ?? 0) / 1000).toFixed(1)}s`} />
            <SolveMetric label="内存" value={`${metadata?.memoryUsageGb.toFixed(2) ?? "—"} GB${metadata?.compressed ? " (compressed)" : ""}`} />
            <SolveMetric label="街" value={metadata?.street ?? "—"} />
          </div>

          <div className="solve-controls">
            <div className="solve-controls__group" role="tablist" aria-label="求解节点">
              {NODE_OPTIONS.map((option) => (
                <button
                  key={option.id}
                  role="tab"
                  aria-selected={nodeId === option.id}
                  className={`solve-toggle ${nodeId === option.id ? "solve-toggle--active" : ""}`}
                  onClick={() => setNodeId(option.id)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="solve-controls__group" role="tablist" aria-label="视图模式">
              {MODE_OPTIONS.map((option) => (
                <button
                  key={option.id}
                  role="tab"
                  aria-selected={mode === option.id}
                  className={`solve-toggle ${mode === option.id ? "solve-toggle--active" : ""}`}
                  onClick={() => setMode(option.id)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="solve-grid-layout">
            <div className="solve-grid-scroll">
              <StrategyGrid
                cells={cells}
                mode={mode}
                activeCell={activeCell}
                onSelectCell={setActiveCell}
              />
              <p className="muted small solve-grid-hint">
                {mode === "strategy"
                  ? "每格显示该手牌类在节点上的混合动作频率（按组合权重聚合）。点击格子查看真实组合。"
                  : mode === "ev"
                    ? "EV 热图：按组合权重聚合的期望值（chips）。高频与低频动作的 EV 可能非常接近。"
                    : "Equity 热图：该手牌类在节点上的平均权益。"}
              </p>
            </div>
            {activeCell ? (
              <ComboInspector node={node} cell={activeCell} />
            ) : (
              <p className="muted small solve-inspector-placeholder">点击网格中的手牌类，查看真实组合的策略 / EV / Equity。</p>
            )}
          </div>

          <NodeNavigator root={solveJob?.result?.root} responseNode={solveJob?.result?.responseNode} />
        </>
      ) : (
        <p className="muted">状态：{status}</p>
      )}

      {status === "solved" && heroHoleCards.length === 2 && (
        <HeroComboLine node={solveJob?.result?.root} responseNode={solveJob?.result?.responseNode} heroHoleCards={heroHoleCards} />
      )}
    </section>
  );
}

function SolveMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="solve-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function HeroComboLine({
  node,
  responseNode,
  heroHoleCards,
}: {
  node: SolverNodePayload | null | undefined;
  responseNode: SolverNodePayload | null | undefined;
  heroHoleCards: string[];
}) {
  const find = (n: SolverNodePayload | null | undefined) =>
    n?.hands.find((hand) => {
      const comboSet = new Set([hand.combo.slice(0, 2), hand.combo.slice(2, 4)]);
      return heroHoleCards.every((card) => comboSet.has(card));
    }) ?? null;
  const combo = find(node) ?? find(responseNode);
  if (!combo) return <p className="muted small">Hero 手牌（{heroHoleCards.join(" ")}）不在当前求解范围中。</p>;
  const top = Object.entries(combo.strategy).sort((a, b) => b[1] - a[1])[0];
  return (
    <p className="muted small solve-hero-line">
      Hero 手牌（{heroHoleCards.join(" ")}）：<strong>{top[0]}</strong> {Math.round(top[1] * 1000) / 10}% · EV{" "}
      {combo.ev >= 0 ? "+" : ""}
      {combo.ev.toFixed(2)} · Equity {(combo.equity * 100).toFixed(1)}%
    </p>
  );
}
