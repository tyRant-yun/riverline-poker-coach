// Structured evidence bundle view: metrics, hand/board, equity, range
// analysis, strategy match and evidence rows.

import type { AnalysisResponse } from "../../types/api";

type Analysis = AnalysisResponse["analysis"];

type Props = {
  analysis: Analysis;
  analysisStale: boolean;
};

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{String(value)}</strong>
    </div>
  );
}

export default function AnalysisPanel({ analysis, analysisStale }: Props) {
  return (
    <section className="panel results-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">04 · EVIDENCE BUNDLE</p>
          <h2>结构化分析</h2>
        </div>
        <div className="heading-actions">
          {analysisStale && <span className="source-tag">结果已过期</span>}
          <span className="source-tag green">{analysis.equity?.sourceLevel ?? "principle_only"}</span>
        </div>
      </div>
      <div className="metric-grid">
        <Metric label="Pot" value={analysis.metrics.currentPot ?? "—"} />
        <Metric label="Call cost" value={analysis.metrics.callCost ?? "—"} />
        <Metric label="SPR" value={analysis.metrics.spr ?? "—"} />
        <Metric label="Pot odds" value={analysis.metrics.potOdds ?? "—"} />
        <Metric label="Hand" value={analysis.hand.madeHand} />
        <Metric label="Outs" value={analysis.hand.outCount} />
      </div>
      <div className="result-columns">
        <div>
          <p className="eyebrow">HAND / BOARD</p>
          <p className="result-line">
            <strong>{analysis.hand.category}</strong> · {analysis.hand.draws.join(", ") || "no draw"}
          </p>
          <p className="muted">
            Board: {analysis.board.labels.join(" · ")} · {analysis.board.staticOrDynamic}
          </p>
          <p className="muted small">
            Outs: {analysis.hand.outCards.join(", ") || "—"} · 反制牌：
            {analysis.hand.counterfeitRiskCards.join(", ") || "—"}
          </p>
        </div>
        <div>
          <p className="eyebrow">EQUITY</p>
          {analysis.equity ? (
            <p className="result-line">
              <strong>{analysis.equity.heroEquity}</strong> Hero · {analysis.equity.villainEquity}{" "}
              Villain · tie {analysis.equity.tieProbability}
            </p>
          ) : (
            <p className="muted">缺少 Villain 手牌或范围，未计算 Equity。</p>
          )}
        </div>
      </div>
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
