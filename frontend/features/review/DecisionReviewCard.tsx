import type { DecisionReview } from "../../types/handReview";
import { SOLVER_ASSESSMENT_STATUS, solverAssessmentDetails } from "../../lib/solver/assessment";

type Props = {
  review: DecisionReview;
};

export default function DecisionReviewCard({ review }: Props) {
  const solver = review.solverAssessment;
  const range = review.rangeUpdate;
  const solverMeta = SOLVER_ASSESSMENT_STATUS[solver.status];
  const solverDetails = solverAssessmentDetails(solver);

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
        <span className={solverMeta.className}>{solverMeta.label}</span>
      </div>
      {solverDetails.length ? <p className="muted small">{solverDetails.join(" · ")}</p> : null}
      {solver.status === "unscored" && solver.reason ? (
        <p className="notice small">{solver.reason}</p>
      ) : null}

      {review.teaching?.summary ? (
        <p className="teaching-summary">{review.teaching.summary}</p>
      ) : null}
    </article>
  );
}
