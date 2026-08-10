// Saved scenarios, revisions and analysis history with cross-version compare.

import type {
  AnalysisComparison,
  AnalysisRun,
  SavedScenario,
  ScenarioRevision,
} from "../../types/scenario";

type Props = {
  savedScenarios: SavedScenario[];
  historyScenarioId: string | null;
  savedRevisions: ScenarioRevision[];
  savedAnalyses: AnalysisRun[];
  compareLeft: string;
  compareRight: string;
  comparison: AnalysisComparison | null;
  /** The scenario currently loaded into the workspace (accent highlight). */
  activeScenarioId?: string | null;
  onRefresh: () => void;
  onLoad: (record: SavedScenario) => void;
  onLoadHistory: (record: SavedScenario) => void;
  onReanalyze: (record: SavedScenario) => void;
  onDelete: (record: SavedScenario) => void;
  onCopy: (record: SavedScenario) => void;
  onLoadRevision: (revision: ScenarioRevision) => void;
  onReanalyzeRevision: (revision: ScenarioRevision, title: string) => void;
  onCompareLeftChange: (value: string) => void;
  onCompareRightChange: (value: string) => void;
  onCompare: () => void;
};

export default function ScenarioHistory({
  savedScenarios,
  historyScenarioId,
  savedRevisions,
  savedAnalyses,
  compareLeft,
  compareRight,
  comparison,
  activeScenarioId = null,
  onRefresh,
  onLoad,
  onLoadHistory,
  onReanalyze,
  onDelete,
  onCopy,
  onLoadRevision,
  onReanalyzeRevision,
  onCompareLeftChange,
  onCompareRightChange,
  onCompare,
}: Props) {
  return (
    <section className="panel compact-panel panel--subtle">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">02B · HISTORY</p>
          <h2>场景历史</h2>
        </div>
        <button className="text-button" onClick={onRefresh}>
          刷新
        </button>
      </div>
      {savedScenarios.length === 0 ? (
        <p className="muted small">尚无已保存场景。</p>
      ) : (
        <div className="saved-list">
          {savedScenarios.slice(0, 8).map((record) => (
            <div
              className={`saved-row ${record.scenarioId === activeScenarioId ? "saved-row--active" : ""}`}
              key={record.scenarioId}
            >
              <button className="saved-load" onClick={() => onLoad(record)}>
                <strong>{record.title}</strong>
                <span className="saved-row__rev">rev {record.revisionNo}</span>
              </button>
              <div className="saved-row__actions">
                <button className="text-button" onClick={() => onLoadHistory(record)}>
                  历史
                </button>
                <button className="text-button" onClick={() => onReanalyze(record)}>
                  重新分析
                </button>
                <button
                  className="icon-button saved-row__copy"
                  onClick={() => onCopy(record)}
                  aria-label={`复制 ${record.title}`}
                >
                  ＋
                </button>
                <button
                  className="saved-row__delete"
                  onClick={() => onDelete(record)}
                  aria-label={`删除 ${record.title}`}
                  title="删除"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {historyScenarioId && (
        <div className="history-compare">
          <p className="eyebrow">SCENARIO REVISIONS</p>
          {savedRevisions.map((revision) => (
            <div className="revision-row" key={`${revision.scenarioId}-${revision.revisionNo}`}>
              <span>rev {revision.revisionNo}</span>
              <button className="text-button" onClick={() => onLoadRevision(revision)}>
                载入
              </button>
              <button
                className="text-button"
                onClick={() =>
                  onReanalyzeRevision(
                    revision,
                    savedScenarios.find((item) => item.scenarioId === revision.scenarioId)?.title ?? "场景",
                  )
                }
              >
                重新分析
              </button>
            </div>
          ))}
        </div>
      )}
      {historyScenarioId && (
        <div className="history-compare">
          <p className="eyebrow">ANALYSIS HISTORY</p>
          {savedAnalyses.length < 2 ? (
            <p className="muted small">至少需要两次保存分析才能比较。</p>
          ) : (
            <>
              <label>
                左侧
                <select value={compareLeft} onChange={(event) => onCompareLeftChange(event.target.value)}>
                  {savedAnalyses.map((item) => (
                    <option key={item.analysisId} value={item.analysisId}>
                      rev {item.revisionNo} · {item.analysisId.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                右侧
                <select value={compareRight} onChange={(event) => onCompareRightChange(event.target.value)}>
                  {savedAnalyses.map((item) => (
                    <option key={item.analysisId} value={item.analysisId}>
                      rev {item.revisionNo} · {item.analysisId.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <button className="secondary-button" onClick={onCompare} disabled={compareLeft === compareRight}>
                比较分析
              </button>
              {comparison && (
                <p className="muted small">
                  发现 {comparison.differences.length} 个结构化字段差异：
                  {comparison.differences.map((difference) => difference.field).join("、") || "无"}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
