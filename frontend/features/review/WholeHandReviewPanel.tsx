import type { WholeHandReviewState } from "../../lib/poker/wholeHandReview";
import DecisionReviewList from "./DecisionReviewList";

type Props = {
  state: WholeHandReviewState;
  busy: boolean;
  onGenerate: () => void;
  onNavigate: (actionId: string) => void;
};

export default function WholeHandReviewPanel({ state, busy, onGenerate, onNavigate }: Props) {
  const review = state.review;
  return (
    <section className="panel" aria-label="整手复盘">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">HAND REVIEW</p>
          <h2>整手复盘</h2>
        </div>
        <button className="action-button" onClick={onGenerate} disabled={busy || state.status === "loading"}>
          {state.status === "loading" ? "正在生成整手复盘…" : "生成整手复盘"}
        </button>
      </div>

      {state.status === "error" ? <p className="warning">{state.error ?? "整手复盘生成失败。"}</p> : null}
      {state.status === "stale" ? <p className="notice">场景已变化；以下整手复盘已过期，请重新生成。</p> : null}

      {review?.wholeHandSummary ? (
        <div className="strategy-card" aria-label="整手总结">
          <strong>整手总结</strong>
          <p>{review.wholeHandSummary.summary}</p>
          <p className="muted small">不确定性：{review.wholeHandSummary.uncertainty}</p>
        </div>
      ) : null}

      {review?.priorityFindings.length ? (
        <div className="range-result-card" aria-label="优先复盘点">
          <strong>优先复盘点</strong>
          <div className="saved-list">
            {review.priorityFindings.map((finding) => (
              <button
                className="saved-row"
                key={`${finding.actionId}-${finding.mistakeTag}`}
                onClick={() => onNavigate(finding.actionId)}
              >
                <span>{finding.summary}</span>
                <span className="muted small">{finding.mistakeTag} · 前往该决策</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {review ? (
        <>
          <DecisionReviewList reviews={review.decisionReviews} onSelectAction={onNavigate} />
          {review.uncertainty.length ? (
            <div className="range-result-card" aria-label="整手复盘不确定性">
              <strong>不确定性</strong>
              {review.uncertainty.map((item) => <p className="muted small" key={item}>{item}</p>)}
            </div>
          ) : null}
        </>
      ) : state.status === "idle" ? (
        <p className="muted">生成后将按真实玩家行动顺序显示教学、可用 Solver 评估与不确定性。</p>
      ) : null}
    </section>
  );
}
