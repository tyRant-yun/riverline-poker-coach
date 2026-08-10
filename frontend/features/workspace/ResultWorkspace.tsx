// Bottom result workspace: tabbed view over Evidence / Coach / Practice /
// Solver outputs. The active tab auto-follows newly arrived results (e.g.
// running teaching switches to Coach), so the panels stay reachable without
// manual navigation. F3 adds the solver strategy/EV/equity views inside the
// Solver tab.

import type {
  AnalysisResponse,
  PracticeOutcome,
  PracticeQuestion,
  SolveJob,
  TeachingMeta,
  TeachingResponse,
} from "../../types/api";
import AnalysisPanel from "../analysis/AnalysisPanel";
import TeachingPanel from "../coach/TeachingPanel";
import PracticePanel from "../practice/PracticePanel";
import SolverWorkspace from "../solver/SolverWorkspace";

export type ResultTab = "evidence" | "coach" | "practice" | "solver";

const TABS: { id: ResultTab; label: string }[] = [
  { id: "evidence", label: "Evidence" },
  { id: "coach", label: "Coach" },
  { id: "practice", label: "Practice" },
  { id: "solver", label: "Solver" },
];

const PLACEHOLDERS: Record<ResultTab, string> = {
  evidence: "生成分析后，此处显示 EvidenceBundle：指标、牌力、范围与证据行。",
  coach: "点击「教学解释」后，此处显示证据约束的教学回答。",
  practice: "点击「生成练习」后，此处出现验证练习题与评分。",
  solver: "提交 Solver 求解后，此处显示策略频率与求解质量。",
};

type Props = {
  activeTab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
  analysis: AnalysisResponse["analysis"] | null;
  analysisStale: boolean;
  teaching: TeachingResponse["response"] | null;
  teachingMeta: TeachingMeta | null;
  practice: PracticeQuestion | null;
  practiceOutcome: PracticeOutcome | null;
  legalActions: string[];
  busy: boolean;
  solveJob: SolveJob | null;
  canSubmitSolve: boolean;
  heroHoleCards: string[];
  onSolveSubmit: () => void;
  onSolveCancel: () => void;
  onPracticeAnswer: (action: string) => void;
};

export default function ResultWorkspace({
  activeTab,
  onTabChange,
  analysis,
  analysisStale,
  teaching,
  teachingMeta,
  practice,
  practiceOutcome,
  legalActions,
  busy,
  solveJob,
  canSubmitSolve,
  heroHoleCards,
  onSolveSubmit,
  onSolveCancel,
  onPracticeAnswer,
}: Props) {
  return (
    <section className="panel result-workspace" aria-label="结果工作区">
      <div className="result-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`result-tab ${activeTab === tab.id ? "result-tab--active" : ""}`}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="result-content" role="tabpanel">
        {activeTab === "evidence" &&
          (analysis ? (
            <AnalysisPanel analysis={analysis} analysisStale={analysisStale} />
          ) : (
            <p className="muted">{PLACEHOLDERS.evidence}</p>
          ))}
        {activeTab === "coach" &&
          (teaching ? (
            <TeachingPanel teaching={teaching} teachingMeta={teachingMeta} />
          ) : (
            <p className="muted">{PLACEHOLDERS.coach}</p>
          ))}
        {activeTab === "practice" &&
          (practice ? (
            <PracticePanel
              practice={practice}
              practiceOutcome={practiceOutcome}
              legalActions={legalActions}
              busy={busy}
              onAnswer={onPracticeAnswer}
            />
          ) : (
            <p className="muted">{PLACEHOLDERS.practice}</p>
          ))}
        {activeTab === "solver" && (
          <SolverWorkspace
            solveJob={solveJob}
            canSubmit={canSubmitSolve}
            heroHoleCards={heroHoleCards}
            onSubmit={onSolveSubmit}
            onCancel={onSolveCancel}
          />
        )}
      </div>
    </section>
  );
}
