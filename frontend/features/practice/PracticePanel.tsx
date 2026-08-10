// Validated practice question + graded outcome.

import type { PracticeOutcome, PracticeQuestion } from "../../types/api";

type Props = {
  practice: PracticeQuestion;
  practiceOutcome: PracticeOutcome | null;
  legalActions: string[];
  busy: boolean;
  onAnswer: (action: string) => void;
};

const ANSWERABLE_ACTIONS = ["check", "call", "fold", "bet", "raise_to", "all_in"];

export default function PracticePanel({ practice, practiceOutcome, legalActions, busy, onAnswer }: Props) {
  const answerable = (legalActions.length ? legalActions : ["check", "call", "fold"]).filter((action) =>
    ANSWERABLE_ACTIONS.includes(action),
  );
  return (
    <section className="panel practice-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">06 · PRACTICE</p>
          <h2>验证练习</h2>
        </div>
        <span className="source-tag">validated</span>
      </div>
      <p className="teaching-summary">{practice.prompt}</p>
      <p className="muted small">概念：{practice.conceptTags.join(" · ")}</p>
      <div className="action-buttons">
        {answerable.map((action) => (
          <button key={action} onClick={() => onAnswer(action)} disabled={busy}>
            {action}
          </button>
        ))}
      </div>
      {practiceOutcome && (
        <div className={`practice-outcome ${practiceOutcome.attempt.correct ? "correct" : "incorrect"}`}>
          <strong>{practiceOutcome.attempt.correct ? "Correct" : "Review"}</strong>
          <span>{practiceOutcome.explanation}</span>
          <small>
            证据：{practiceOutcome.evidenceReferences.map((reference) => reference.evidenceId).join("、")}
          </small>
        </div>
      )}
    </section>
  );
}
