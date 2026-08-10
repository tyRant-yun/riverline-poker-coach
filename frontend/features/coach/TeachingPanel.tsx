// Evidence-bound teaching explanation view.

import type { TeachingMeta, TeachingResponse } from "../../types/api";

type Props = {
  teaching: TeachingResponse["response"];
  teachingMeta: TeachingMeta | null;
};

export default function TeachingPanel({ teaching, teachingMeta }: Props) {
  return (
    <section className="panel teaching-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">05 · TEACHING</p>
          <h2>证据约束的教学解释</h2>
        </div>
        <span className="source-tag">
          {teachingMeta?.provider === "external_llm"
            ? teachingMeta.degraded
              ? `external_llm · degraded(本地回退) · ${teachingMeta.teacherVersion}`
              : `external_llm · ${teachingMeta.teacherVersion}`
            : `principle_only · ${teaching.explanationDepth}`}
        </span>
      </div>
      <p className="teaching-summary">{teaching.summary.text}</p>
      <div className="teaching-columns">
        <div>
          <p className="eyebrow">RECOMMENDED ACTIONS</p>
          {teaching.recommendedActions.map((action) => (
            <p className="result-line" key={action.action}>
              <strong>{action.action}</strong>
              {action.frequency ? ` · ${action.frequency}` : ""}
            </p>
          ))}
        </div>
        <div>
          <p className="eyebrow">KEY REASONS</p>
          {teaching.keyReasons.map((reason) => (
            <p className="muted" key={reason.text}>
              {reason.text}
            </p>
          ))}
        </div>
      </div>
      {teaching.conceptTags?.length ? (
        <p className="muted small">概念：{teaching.conceptTags.join(" · ")}</p>
      ) : null}
      {teaching.followUpQuestion ? <p className="notice">追问：{teaching.followUpQuestion}</p> : null}
      <p className="notice">{teaching.uncertainty.text}</p>
    </section>
  );
}
