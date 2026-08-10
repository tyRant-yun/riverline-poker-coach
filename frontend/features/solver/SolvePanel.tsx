// Solver job panel: submit, status, metadata and primary-action summary.
// Numeric semantics come straight from the backend SolveJob payload; the
// frontend never recomputes exploitability or strategy frequencies.

import type { SolveJob, SolverNodePayload } from "../../types/api";

function solvePrimary(node?: SolverNodePayload | null): { action: string; frequency: number } | null {
  if (!node || !node.hands.length) return null;
  const total = node.hands.reduce((sum, hand) => sum + hand.weight, 0) || 1;
  const weighted: Record<string, number> = {};
  for (const hand of node.hands) {
    for (const [action, frequency] of Object.entries(hand.strategy)) {
      weighted[action] = (weighted[action] ?? 0) + hand.weight * frequency;
    }
  }
  const action = Object.keys(weighted).sort((a, b) => weighted[b] - weighted[a])[0];
  return { action, frequency: (weighted[action] ?? 0) / total };
}

function solveHeroCombo(
  node: SolverNodePayload | undefined | null,
  cards: string[],
): SolverNodePayload["hands"][number] | null {
  if (!node || cards.length !== 2) return null;
  return (
    node.hands.find((hand) => {
      const comboSet = new Set([hand.combo.slice(0, 2), hand.combo.slice(2, 4)]);
      return cards.every((card) => comboSet.has(card));
    }) ?? null
  );
}

type Props = {
  solveJob: SolveJob | null;
  canSubmit: boolean;
  heroHoleCards: string[];
  onSubmit: () => void;
};

export default function SolvePanel({ solveJob, canSubmit, heroHoleCards, onSubmit }: Props) {
  return (
    <section className="panel solve-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">06 · SOLVER</p>
          <h2>Solver 策略求解</h2>
        </div>
        <span className="source-tag">solver_backed{solveJob ? ` · ${solveJob.status}` : ""}</span>
      </div>
      {!solveJob ? (
        <div className="action-buttons">
          <button onClick={onSubmit} disabled={!canSubmit}>
            提交 Solver 求解（独立容器）
          </button>
          <p className="muted small">
            需要 Hero 与 Villain 范围（用上方范围面板选择默认范围或手动输入）。求解约 1–3 分钟。
          </p>
        </div>
      ) : (
        <div>
          {solveJob.status === "solved" && solveJob.result?.metadata ? (
            <div className="teaching-columns">
              <div>
                <p className="eyebrow">求解质量</p>
                <p className="result-line">
                  <strong>exploitability</strong> {solveJob.result.metadata.exploitabilityChips.toFixed(3)} chips
                </p>
                <p className="result-line">
                  <strong>耗时</strong> {(solveJob.result.metadata.solveTimeMs / 1000).toFixed(1)}s
                </p>
                <p className="result-line">
                  <strong>迭代</strong> {solveJob.result.metadata.maxIterations}
                </p>
                <p className="result-line">
                  <strong>引擎</strong> {solveJob.result.metadata.solver} {solveJob.result.metadata.version}
                </p>
              </div>
              <div>
                <p className="eyebrow">OOP 主导动作</p>
                {(() => {
                  const primary = solvePrimary(solveJob.result?.root);
                  return primary ? (
                    <p className="result-line">
                      <strong>{primary.action}</strong> · {primary.frequency.toFixed(3)}
                    </p>
                  ) : (
                    <p className="muted">—</p>
                  );
                })()}
                <p className="eyebrow">IP 响应主导动作</p>
                {(() => {
                  const primary = solvePrimary(solveJob.result?.responseNode);
                  return primary ? (
                    <p className="result-line">
                      <strong>{primary.action}</strong> · {primary.frequency.toFixed(3)}
                    </p>
                  ) : (
                    <p className="muted">—</p>
                  );
                })()}
                <p className="eyebrow">Hero 手牌（{heroHoleCards?.join(" ")}）</p>
                {(() => {
                  const combo =
                    solveHeroCombo(solveJob.result?.root, heroHoleCards ?? []) ??
                    solveHeroCombo(solveJob.result?.responseNode, heroHoleCards ?? []);
                  return combo ? (
                    <p className="result-line">
                      <strong>{Object.entries(combo.strategy).sort((a, b) => b[1] - a[1])[0][0]}</strong> ·{" "}
                      {Object.entries(combo.strategy).sort((a, b) => b[1] - a[1])[0][1].toFixed(3)} · EV{" "}
                      {combo.ev.toFixed(1)}
                    </p>
                  ) : (
                    <p className="muted">手牌不在当前求解范围中</p>
                  );
                })()}
              </div>
            </div>
          ) : ["queued", "running", "cancellation_requested"].includes(solveJob.status) ? (
            <p className="muted">求解进行中（独立 sidecar 容器）…</p>
          ) : solveJob.error ? (
            <p className="warning">{solveJob.error}</p>
          ) : (
            <p className="muted">状态：{solveJob.status}</p>
          )}
        </div>
      )}
    </section>
  );
}
