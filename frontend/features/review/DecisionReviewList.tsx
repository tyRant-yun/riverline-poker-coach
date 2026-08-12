import type { DecisionReview } from "../../types/handReview";
import DecisionReviewCard from "./DecisionReviewCard";

type Props = {
  reviews: readonly DecisionReview[];
  title?: string;
  onSelectAction?: (actionId: string) => void;
};

export default function DecisionReviewList({ reviews, title = "整手决策复盘", onSelectAction }: Props) {
  return (
    <section className="panel" aria-label="决策复盘列表">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">HAND REVIEW</div>
          <h2>{title}</h2>
        </div>
        <span className="status-pill">{reviews.length} 个决策</span>
      </div>
      {reviews.length === 0 ? (
        <p className="muted">这手牌还没有可复盘的玩家决策。</p>
      ) : (
        <div className="saved-list">
          {reviews.map((review) => (
            <DecisionReviewCard key={review.actionId} review={review} onSelectAction={onSelectAction} />
          ))}
        </div>
      )}
    </section>
  );
}
