// Structured evidence bundle view: metrics, hand/board, equity, range
// analysis, strategy match and evidence rows.
//
// A fresh hand / review-mode scenario legitimately produces hand === null
// (no hero hole cards yet). Every hand-dependent section degrades instead
// of crashing, and no hand facts are fabricated.

import type { AnalysisResponse } from "../../types/api";
import type { SeatSpec } from "../../types/scenario";
import { positionLabel } from "../../lib/poker/positions";

type Analysis = AnalysisResponse["analysis"];

type Props = {
  analysis: Analysis;
  analysisStale: boolean;
  /** Table seats, used to label multiway equity rows with positions. */
  seats?: SeatSpec[];
  heroSeat?: number;
};

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{String(value)}</strong>
    </div>
  );
}

function seatLabel(
  seatId: number,
  seats: SeatSpec[] | undefined,
  heroSeat: number | undefined,
): string {
  const seat = seats?.find((entry) => entry.seatId === seatId);
  const position = seat ? positionLabel(seat.position) : `Seat ${seatId}`;
  return seatId === heroSeat ? `${position} · HERO` : `${position}`;
}

function equityPercent(share: string): string {
  const value = Number(share);
  if (!Number.isFinite(value)) return share;
  return `${(value * 100).toFixed(1)}%`;
}

export default function AnalysisPanel({ analysis, analysisStale, seats, heroSeat }: Props) {
  const hand = analysis.hand;
  return (
    <section className="panel results-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">04 · EVIDENCE BUNDLE</p>
          <h2>结构化分析</h2>
        </div>
        <div className="heading-actions">
          {analysisStale && <span className="source-tag">结果已过期</span>}
          <span className="source-tag green">{analysis.multiwayEquity?.sourceLevel ?? analysis.equity?.sourceLevel ?? "principle_only"}</span>
        </div>
      </div>
      <div className="metric-grid">
        <Metric label="Pot" value={analysis.metrics.currentPot ?? "—"} />
        <Metric label="Call cost" value={analysis.metrics.callCost ?? "—"} />
        <Metric label="SPR" value={analysis.metrics.spr ?? "—"} />
        <Metric label="Pot odds" value={analysis.metrics.potOdds ?? "—"} />
        <Metric label="Hand" value={hand ? hand.madeHand : "未输入 Hero 手牌"} />
        <Metric label="Outs" value={hand ? hand.outCount : "—"} />
      </div>
      <div className="result-columns">
        <div>
          <p className="eyebrow">HAND / BOARD</p>
          {hand ? (
            <>
              <p className="result-line">
                <strong>{hand.category}</strong> · {hand.draws.join(", ") || "no draw"}
              </p>
              <p className="muted">
                Board: {analysis.board.labels.join(" · ")} · {analysis.board.staticOrDynamic}
              </p>
              <p className="muted small">
                Outs: {hand.outCards.join(", ") || "—"} · 反制牌：
                {hand.counterfeitRiskCards.join(", ") || "—"}
              </p>
            </>
          ) : (
            <>
              <p className="muted">
                Board: {analysis.board.labels.join(" · ")} · {analysis.board.staticOrDynamic}
              </p>
              <p className="muted small">
                牌力分析需要 Hero 手牌；当前仍可查看牌面、规则状态和可用的其他证据。
              </p>
            </>
          )}
        </div>
        <div>
          <p className="eyebrow">EQUITY</p>
          {analysis.equity ? (
            <p className="result-line">
              <strong>{analysis.equity.heroEquity}</strong> Hero · {analysis.equity.villainEquity}{" "}
              Villain · tie {analysis.equity.tieProbability}
            </p>
          ) : analysis.multiwayEquity ? (
            <p className="muted">多路底池 equity 见下方 MULTIWAY EQUITY。</p>
          ) : (
            <p className="muted">
              {hand === null
                ? "缺少 Hero 手牌或范围，未计算 Equity。"
                : "缺少 Villain 手牌或范围，未计算 Equity。"}
            </p>
          )}
        </div>
      </div>
      {analysis.multiwayEquity && (
        <div className="multiway-equity-card">
          <p className="eyebrow">MULTIWAY EQUITY</p>
          {Object.entries(analysis.multiwayEquity.equityBySeat)
            .sort(([, left], [, right]) => Number(right) - Number(left))
            .map(([seatId, share]) => (
              <p className="result-line" key={seatId}>
                <strong>{equityPercent(share)}</strong>{" "}
                {seatLabel(Number(seatId), seats, heroSeat)}
              </p>
            ))}
          <p className="muted small">
            Tie probability {equityPercent(analysis.multiwayEquity.tieProbability)} · Trials{" "}
            {analysis.multiwayEquity.trials} · {analysis.multiwayEquity.weighted ? "weighted" : "unweighted"}{" "}
            · {analysis.multiwayEquity.activePlayerCount} active
          </p>
        </div>
      )}
      {analysis.rangeAnalysis && (
        <div className="range-result-card">
          <p className="eyebrow">RANGE / COMBOS</p>
          <p className="result-line">
            <strong>{analysis.rangeAnalysis.totalCombos}</strong> combos · 加权{" "}
            {analysis.rangeAnalysis.weightedCombos} · blocked {analysis.rangeAnalysis.blockedCombos}
          </p>
          <p className="muted">
            value {analysis.rangeAnalysis.valueCombos} · bluff {analysis.rangeAnalysis.bluffCombos} ·
            draw {analysis.rangeAnalysis.drawCombos} · polarity {analysis.rangeAnalysis.polarity}
          </p>
          <p className="muted small">
            Blocker：{analysis.rangeAnalysis.blockerCards.join(", ") || "—"} · 分类标记：
            {analysis.rangeAnalysis.heuristic ? "heuristic" : "calculated"}
          </p>
        </div>
      )}
      {analysis.strategyMatch && (
        <div className="strategy-card">
          <div>
            <p className="eyebrow">STRATEGY MATCH</p>
            <p className="result-line">
              <strong>{analysis.strategyMatch.level}</strong> · similarity{" "}
              {analysis.strategyMatch.similarity}
            </p>
            <p className="muted">{analysis.strategyMatch.explanation}</p>
          </div>
          <div>
            {analysis.strategyMatch.recommendations.map((recommendation) => (
              <div className="recommendation-row" key={recommendation.action}>
                <strong>{recommendation.action}</strong>
                <span>{recommendation.summary}</span>
                {recommendation.frequency && <em>{recommendation.frequency}</em>}
              </div>
            ))}
          </div>
          {analysis.strategyMatch.differences.length > 0 && (
            <p className="muted small">
              差异：
              {analysis.strategyMatch.differences.map((difference) => difference.field).join("、")}
            </p>
          )}
        </div>
      )}
      <div className="evidence-list">
        {analysis.evidence.items.slice(0, 12).map((item) => (
          <div className="evidence-row" key={item.evidenceId}>
            <span>{item.evidenceId}</span>
            <strong>{String(item.value)}</strong>
            <em>{item.sourceLevel}</em>
            <small>{item.description}</small>
          </div>
        ))}
      </div>
      {analysis.warnings.map((warning) => (
        <p className="warning" key={warning}>
          {warning}
        </p>
      ))}
    </section>
  );
}
