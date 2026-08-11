import type { DecisionReview, ReviewSolverAssessment } from "../../types/handReview";

type Props = {
  review: DecisionReview;
};

const solverStatusText: Record<ReviewSolverAssessment["status"], string> = {
  primary: "符合主策略",
  mixed: "可接受混频",
  rare: "明显偏离常用策略",
  absent: "Solver 不采用该行动",
  unscored: "未进行 Solver 评分",
};

const solverStatusClass: Record<ReviewSolverAssessment["status"], string> = {
  primary: "source-tag green",
  mixed: "status-pill",
  rare: "source-tag",
  absent: "danger-button",
  unscored: "status-pill",
};

function frequencyText(value: number | string | null | undefined) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return `${Math.round(value * 100)}%`;
  return value;
}

function solverDetail(assessment: ReviewSolverAssessment) {
  const frequency = frequencyText(assessment.actualFrequency);
  const details = [
    frequency ? `实际行动频率 ${frequency}` : null,
    assessment.primaryAction ? `主策略：${assessment.primaryAction}` : null,
    assessment.source ? `来源：${assessment.source}` : null,
  ].filter(Boolean);
  return details.join(" · ");
}

export default function DecisionReviewCard({ review }: Props) {
  const solver = review.solverAssessment;
  const range = review.rangeUpdate;

  return (
    <article className="action-box" aria-label={`决策卡 ${review.actionId}`}>
      <div className="action-header">
        <div className="action-header__node">
          <span className="action-street">{review.street}</span>
          <span>Seat {review.actorSeat}</span>
          <span className="muted small">#{review.eventSequence}</span>
        </div>
        <span className="status-pill">决策前 #{review.decisionSequence}</span>
      </div>

      <div className="panel-heading">
        <strong>{review.actualAction}</strong>
        <span className="source-tag">实际行动</span>
      </div>

      <div className="range-compact" aria-label="范围更新状态">
        <strong className="range-compact__name">范围</strong>
        {range.status === "available" ? (
          <span className="source-tag green">已更新</span>
        ) : (
          <span className="status-pill">不可用</span>
        )}
        {range.source ? <span className="muted small">来源：{range.source}</span> : null}
      </div>
      {range.status === "unavailable" && range.reason ? (
        <p className="notice small">{range.reason}</p>
      ) : null}

      <div className="range-compact" aria-label="Solver 评估状态">
        <strong className="range-compact__name">Solver</strong>
        <span className={solverStatusClass[solver.status]}>
          {solverStatusText[solver.status]}
        </span>
      </div>
      {solverDetail(solver) ? <p className="muted small">{solverDetail(solver)}</p> : null}
      {solver.status === "unscored" && solver.reason ? (
        <p className="notice small">{solver.reason}</p>
      ) : null}

      {review.teaching?.summary ? (
        <p className="teaching-summary">{review.teaching.summary}</p>
      ) : null}
    </article>
  );
}
