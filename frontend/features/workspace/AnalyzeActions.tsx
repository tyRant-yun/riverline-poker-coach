// Workspace actions: validate / analyze / teach / practice / save / import /
// export plus the status notice. Extracted from the page monolith; state and
// handlers stay in the workspace.

import type { ChangeEvent } from "react";

type Props = {
  busy: boolean;
  teachingDepth: string;
  teachingQuestion: string;
  message: string;
  onTeachingDepthChange: (depth: string) => void;
  onTeachingQuestionChange: (question: string) => void;
  onValidate: () => void;
  onAnalyze: () => void;
  onTeach: () => void;
  onPractice: () => void;
  onSave: () => void;
  onExport: () => void;
  onImportFile: (event: ChangeEvent<HTMLInputElement>) => void;
};

export default function AnalyzeActions({
  busy,
  teachingDepth,
  teachingQuestion,
  message,
  onTeachingDepthChange,
  onTeachingQuestionChange,
  onValidate,
  onAnalyze,
  onTeach,
  onPractice,
  onSave,
  onExport,
  onImportFile,
}: Props) {
  return (
    <section className="panel compact-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">03 · ANALYZE</p>
          <h2>输出证据</h2>
        </div>
        <span className="source-tag green">grounded</span>
      </div>
      <p className="muted">编辑完成后重新分析。没有可靠策略数据时，结果只提供数学与原理层证据。</p>
      <div className="teaching-controls">
        <label>
          教学深度
          <select
            aria-label="教学深度"
            value={teachingDepth}
            onChange={(event) => onTeachingDepthChange(event.target.value)}
          >
            <option value="beginner">新手</option>
            <option value="intermediate">进阶</option>
            <option value="advanced">高级</option>
          </select>
        </label>
      </div>
      <label className="teaching-question">
        教学问题
        <textarea
          aria-label="教学问题"
          placeholder="例如：如果对手范围更紧，行动会怎样变化？"
          value={teachingQuestion}
          onChange={(event) => onTeachingQuestionChange(event.target.value)}
        />
      </label>
      <div className="primary-actions">
        <button onClick={onValidate} disabled={busy}>
          校验场景
        </button>
        <button onClick={onAnalyze} disabled={busy}>
          生成分析
        </button>
        <button onClick={onTeach} disabled={busy}>
          教学解释
        </button>
        <button onClick={onPractice} disabled={busy}>
          生成练习
        </button>
        <button className="secondary-button" onClick={onSave} disabled={busy}>
          保存场景
        </button>
        <button className="secondary-button" onClick={onExport} disabled={busy}>
          导出 JSON
        </button>
        <label className="secondary-button import-button">
          导入 JSON
          <input
            type="file"
            accept="application/json,.json"
            aria-label="导入 JSON"
            onChange={onImportFile}
            disabled={busy}
          />
        </label>
      </div>
      <p className="notice">{message}</p>
    </section>
  );
}
