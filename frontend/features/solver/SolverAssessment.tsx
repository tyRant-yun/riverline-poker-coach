import type { ReviewSolverAssessment } from "../../types/handReview";
import { SOLVER_ASSESSMENT_STATUS, solverAssessmentDetails } from "../../lib/solver/assessment";

type Props = {
  assessment: ReviewSolverAssessment;
};

export default function SolverAssessment({ assessment }: Props) {
  const meta = SOLVER_ASSESSMENT_STATUS[assessment.status];
  const details = solverAssessmentDetails(assessment);

  return (
    <div className="action-box solver-assessment" aria-label="Solver 背离评估">
      <div className="panel-heading">
        <strong>实际行动 vs Solver 策略</strong>
        <span className={meta.className}>{meta.label}</span>
      </div>
      {details.length ? <p className="muted small">{details.join(" · ")}</p> : null}
      {assessment.status === "unscored" && assessment.reason ? (
        <p className="notice small">{assessment.reason}</p>
      ) : null}
    </div>
  );
}
