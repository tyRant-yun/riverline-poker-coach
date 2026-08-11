"use client";

// Workspace composition root. Scenario state, API orchestration, undo/redo
// and cross-feature wiring live here; rendering lives in features/components.
// F2: AppShell + three-column workspace + tabbed result workspace.

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

import type {
  SolveJob,
  StateResponse,
  TeachingMeta,
  TeachingResponse,
  PracticeOutcome,
  PracticeQuestion,
  AnalysisResponse,
} from "../types/api";
import type {
  ActionEvent,
  AnalysisComparison,
  AnalysisRun,
  DefaultRanges,
  RangeCombo,
  RangeSide,
  RangeSummary,
  SavedScenario,
  Scenario,
  ScenarioRevision,
} from "../types/scenario";
import type { BeliefMode, RangeBeliefView } from "../types/rangeBelief";
import type { SeatViewModel } from "../types/poker";

import {
  analysisApi,
  coachApi,
  practiceApi,
  rangesApi,
  scenariosApi,
  solverApi,
} from "../lib/api/client";
import { notationFromMatrix, notationFromMatrixExplicit } from "../lib/poker/matrix";
import { canSubmitSolve as solveGate, solveGateReasons } from "../lib/poker/solve";
import type { DisplayUnit } from "../lib/poker/format";
import { buildSeatViewModels } from "../lib/poker/table";
import { deadCardsForSeat, heroCards, syncSeatSourcesFromLegacy } from "../lib/poker/scenario";
import { projectSelectedDecisionScenario, reconcileSelectedActionId, selectionForAction } from "../lib/poker/handReview";
import { BeliefRequestGate } from "../lib/range/beliefRequest";
import { applySolvePoll } from "../lib/solver/poll";

import AppShell, { type WorkspaceView } from "../components/AppShell";
import PokerTable from "../components/poker/PokerTable";
import ActionBar from "../components/poker/ActionBar";
import ScenarioEditor from "../features/scenario/ScenarioEditor";
import ActionTimeline from "../features/scenario/ActionTimeline";
import RangeEditor from "../features/range/RangeEditor";
import ScenarioHistory from "../features/history/ScenarioHistory";
import AnalyzeActions from "../features/workspace/AnalyzeActions";
import ResultWorkspace, { type ResultTab } from "../features/workspace/ResultWorkspace";
import TeachingPanel from "../features/coach/TeachingPanel";
import PracticePanel from "../features/practice/PracticePanel";
import SolverWorkspace from "../features/solver/SolverWorkspace";

const initialScenario: Scenario = {
  schemaVersion: 1,
  gameVariant: "nlhe",
  tableSize: 2,
  smallBlind: 50,
  bigBlind: 100,
  buttonSeat: 0,
  heroSeat: 0,
  seats: [
    { seatId: 0, startingStack: 10_000, position: "button" },
    { seatId: 1, startingStack: 10_000, position: "big_blind" },
  ],
  // A brand-new hand: no cards, no board, no actions — only the blinds.
  heroHoleCards: [],
  villainHoleCards: [],
  board: [],
  actionHistory: [],
  decisionPoint: { street: "preflop", actorSeat: 0, afterSequence: 0 },
  assumptions: {},
};

export default function Home() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [pastScenarios, setPastScenarios] = useState<Scenario[]>([]);
  const [futureScenarios, setFutureScenarios] = useState<Scenario[]>([]);
  const [state, setState] = useState<StateResponse["finalState"] | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse["analysis"] | null>(null);
  const [analysisStale, setAnalysisStale] = useState(false);
  const [teaching, setTeaching] = useState<TeachingResponse["response"] | null>(null);
  const [teachingMeta, setTeachingMeta] = useState<TeachingMeta | null>(null);
  const [solveJob, setSolveJob] = useState<SolveJob | null>(null);
  const [practice, setPractice] = useState<PracticeQuestion | null>(null);
  const [practiceOutcome, setPracticeOutcome] = useState<PracticeOutcome | null>(null);
  const [teachingDepth, setTeachingDepth] = useState("intermediate");
  const [teachingQuestion, setTeachingQuestion] = useState("");
  const [rangeSide, setRangeSide] = useState<RangeSide>("villainRange");
  const [rangeTextBySide, setRangeTextBySide] = useState<Record<RangeSide, string>>({ heroRange: "22+, A5s+, K9o+", villainRange: "22+, A5s+, K9o+" });
  const [defaultRanges, setDefaultRanges] = useState<DefaultRanges>({});
  const [rangeMatrix, setRangeMatrix] = useState<Record<string, string>>({});
  const [rangeSummary, setRangeSummary] = useState<RangeSummary | null>(null);
  const [rangeCombos, setRangeCombos] = useState<RangeCombo[]>([]);
  const [rangeBelief, setRangeBelief] = useState<RangeBeliefView | null>(null);
  const [rangeBeliefLoading, setRangeBeliefLoading] = useState(false);
  const [rangeBeliefStale, setRangeBeliefStale] = useState(false);
  const [beliefMode, setBeliefMode] = useState<BeliefMode>("prior");
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null);
  const [beliefSeatId, setBeliefSeatId] = useState<number | null>(null);
  const [savedScenarios, setSavedScenarios] = useState<SavedScenario[]>([]);
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);
  const [activeRevisionNo, setActiveRevisionNo] = useState<number | null>(null);
  const [savedScenarioDirty, setSavedScenarioDirty] = useState(false);
  const [historyScenarioId, setHistoryScenarioId] = useState<string | null>(null);
  const [savedAnalyses, setSavedAnalyses] = useState<AnalysisRun[]>([]);
  const [savedRevisions, setSavedRevisions] = useState<ScenarioRevision[]>([]);
  const [comparison, setComparison] = useState<AnalysisComparison | null>(null);
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");
  const [raiseAmount, setRaiseAmount] = useState<number | "">("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("先输入牌面，再使用合法动作按钮推进牌局。");
  const [displayUnit, setDisplayUnit] = useState<DisplayUnit>("bb");
  const [activeView, setActiveView] = useState<WorkspaceView>("handlab");
  const [resultTab, setResultTab] = useState<ResultTab>("evidence");
  // Generation token that supersedes stale solver poll loops (prevents
  // duplicate/concurrent polling when a job is resubmitted or the page
  // unmounts).
  const solvePollToken = useRef(0);
  const rangeBeliefRequestGate = useRef(new BeliefRequestGate());
  const stateRefreshToken = useRef(0);

  useEffect(() => {
    void loadSavedScenarios();
    void loadDefaultRanges();
    void refreshState(initialScenario);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stop any in-flight solver polling when the workspace unmounts.
  useEffect(() => {
    return () => {
      solvePollToken.current += 1;
    };
  }, []);

  // The result workspace follows newly arrived results.
  useEffect(() => {
    if (analysis) setResultTab("evidence");
  }, [analysis]);
  useEffect(() => {
    if (teaching) setResultTab("coach");
  }, [teaching]);
  useEffect(() => {
    if (practice) setResultTab("practice");
  }, [practice]);
  useEffect(() => {
    if (solveJob) setResultTab("solver");
  }, [solveJob]);

  const rangeText = rangeTextBySide[rangeSide];
  const selectedAction = useMemo(
    () => selectionForAction(scenario.actionHistory, selectedActionId),
    [scenario.actionHistory, selectedActionId],
  );
  const selectedDecisionScenario = useMemo(
    () => selectedAction ? projectSelectedDecisionScenario(scenario, selectedAction) : null,
    [scenario, selectedAction],
  );
  // The editor always owns `scenario`. This projection is read-only and is
  // the single scenario source for the selected decision workspace.
  const workspaceScenario = selectedDecisionScenario ?? scenario;

  const hasDealFlop = workspaceScenario.actionHistory.some((event) => event.actionType === "deal_flop");
  const hasDealTurn = workspaceScenario.actionHistory.some((event) => event.actionType === "deal_turn");
  const hasDealRiver = workspaceScenario.actionHistory.some((event) => event.actionType === "deal_river");
  const pendingDealStreet = state?.actorSeat === null
    ? (!hasDealFlop && workspaceScenario.board.length >= 3
      ? "preflop"
      : !hasDealTurn && workspaceScenario.board.length >= 4
        ? "flop"
        : !hasDealRiver && workspaceScenario.board.length >= 5
          ? "turn"
          : null)
    : null;
  const currentStreet = pendingDealStreet ?? state?.street ?? workspaceScenario.decisionPoint.street;
  const legal = state?.legalActions;
  const actorPosition =
    legal?.actorSeat != null
      ? workspaceScenario.seats.find((seat) => seat.seatId === legal.actorSeat)?.position ?? null
      : null;
  const boardInput = useMemo(() => [...scenario.board, "", "", "", "", ""].slice(0, 5), [scenario.board]);

  const tableSeats = useMemo<SeatViewModel[]>(
    () => buildSeatViewModels(workspaceScenario, state),
    [workspaceScenario, state],
  );

  function updateScenario(patch: Partial<Scenario>) {
    const seatSync = syncSeatSourcesFromLegacy(scenario, patch);
    commitScenario({ ...scenario, ...patch, ...seatSync });
    setMessage("场景已修改，需要重新校验或分析。");
  }

  function invalidateDerivedAnalysisState() {
    solvePollToken.current += 1;
    invalidateRangeBelief();
    setSolveJob(null);
  }

  function invalidateRangeBelief() {
    rangeBeliefRequestGate.current.invalidate();
    setRangeBeliefStale(Boolean(rangeBelief));
    setRangeBeliefLoading(false);
  }

  function commitScenario(next: Scenario) {
    setPastScenarios((past) => [...past, scenario]);
    setFutureScenarios([]);
    setScenario(next);
    setSelectedActionId((current) => reconcileSelectedActionId(next.actionHistory, current));
    setSavedScenarioDirty(Boolean(activeScenarioId));
    setAnalysisStale(Boolean(analysis));
    setTeaching(null);
    setPractice(null);
    setPracticeOutcome(null);
    invalidateDerivedAnalysisState();
  }

  function undo() {
    const previous = pastScenarios[pastScenarios.length - 1];
    if (!previous) return;
    const restoredSelection = selectionForAction(previous.actionHistory, selectedActionId);
    setPastScenarios((past) => past.slice(0, -1));
    setFutureScenarios((future) => [scenario, ...future]);
    setScenario(previous);
    setSelectedActionId((current) => reconcileSelectedActionId(previous.actionHistory, current));
    setSavedScenarioDirty(Boolean(activeScenarioId));
    setAnalysisStale(Boolean(analysis));
    setTeaching(null);
    setPractice(null);
    setPracticeOutcome(null);
    invalidateDerivedAnalysisState();
    void refreshState(
      restoredSelection ? projectSelectedDecisionScenario(previous, restoredSelection) : previous,
      undefined,
      !restoredSelection,
    );
  }

  function redo() {
    const next = futureScenarios[0];
    if (!next) return;
    const restoredSelection = selectionForAction(next.actionHistory, selectedActionId);
    setFutureScenarios((future) => future.slice(1));
    setPastScenarios((past) => [...past, scenario]);
    setScenario(next);
    setSelectedActionId((current) => reconcileSelectedActionId(next.actionHistory, current));
    setSavedScenarioDirty(Boolean(activeScenarioId));
    setAnalysisStale(Boolean(analysis));
    setTeaching(null);
    setPractice(null);
    setPracticeOutcome(null);
    invalidateDerivedAnalysisState();
    void refreshState(
      restoredSelection ? projectSelectedDecisionScenario(next, restoredSelection) : next,
      undefined,
      !restoredSelection,
    );
  }

  async function resetScenario() {
    const next = structuredClone(initialScenario) as Scenario;
    commitScenario(next);
    setActiveScenarioId(null);
    setActiveRevisionNo(null);
    setSavedScenarioDirty(false);
    setSelectedActionId(null);
    setBeliefSeatId(null);
    syncRangeEditor(next);
    setState(null);
    setAnalysis(null);
    setAnalysisStale(false);
    setMessage("场景已重置；原场景仍可通过撤销恢复。");
    await refreshState(next, undefined, true);
  }

  function updateBoard(index: number, value: string) {
    const board = [...boardInput];
    board[index] = value.trim();
    updateScenario({ board: board.filter(Boolean) });
  }

  async function loadSavedScenarios() {
    try {
      const payload = await scenariosApi.list();
      setSavedScenarios(payload.scenarios ?? []);
    } catch {
      // Local API may not be running on the first page load.
    }
  }

  async function loadDefaultRanges() {
    try {
      const payload = await rangesApi.defaults();
      setDefaultRanges(payload.ranges ?? {});
    } catch {
      // Default range loading is optional; manual notation remains available.
    }
  }

  function selectRangeSide(side: RangeSide) {
    invalidateRangeBelief();
    setRangeSide(side);
    const selected = side === "heroRange" ? scenario.heroRange : scenario.villainRange;
    setRangeMatrix(selected?.matrix169 ?? {});
    setRangeSummary(null);
    setRangeCombos([]);
    setBeliefSeatId(beliefSeatForSide(side));
  }

  function selectBeliefSeat(seatId: number) {
    invalidateRangeBelief();
    setBeliefSeatId(seatId);
  }

  function beliefSeatForSide(side: RangeSide): number | null {
    if (side === "heroRange") return scenario.heroSeat;
    const other = scenario.seats.find((seat) => seat.seatId !== scenario.heroSeat);
    return other?.seatId ?? null;
  }

  async function fetchRangeBelief({
    seatId,
    afterSequence,
    job = solveJob,
  }: {
    seatId: number | null;
    afterSequence: number;
    job?: SolveJob | null;
  }) {
    if (seatId == null) {
      setRangeBelief(null);
      setRangeBeliefStale(false);
      return;
    }
    // The curated preflop provider is deliberately narrow and declines every
    // non-RFI node; chaining it before the solver lets a trace ground an
    // eligible 8-max open without guessing at the rest of the hand.
    const solverPolicy = job?.status === "solved" && job.result
      ? { source: "solver" as const, jobId: job.jobId }
      : undefined;
    const policy = solverPolicy
      ? [{ source: "preflop_policy" as const }, solverPolicy]
      : { source: "preflop_policy" as const };
    const requestToken = rangeBeliefRequestGate.current.begin();
    setRangeBeliefLoading(true);
    try {
      const payload = await rangesApi.belief({ scenario, seatId, afterSequence, policy });
      if (!rangeBeliefRequestGate.current.isCurrent(requestToken)) return;
      setRangeBelief(payload);
      setRangeBeliefStale(false);
    } catch (error) {
      if (!rangeBeliefRequestGate.current.isCurrent(requestToken)) return;
      setRangeBelief(null);
      setRangeBeliefStale(false);
      setMessage(error instanceof Error ? error.message : "range belief 计算失败");
    } finally {
      if (rangeBeliefRequestGate.current.isCurrent(requestToken)) setRangeBeliefLoading(false);
    }
  }

  // A selected player action drives the after-action range view. The API gets
  // the full hand plus eventSequence so its own temporal contract can hide
  // later board cards/actions; the decision cursor remains eventSequence - 1.
  useEffect(() => {
    if (!selectedAction) return;
    const seatId = beliefSeatId ?? selectedAction.actorSeat;
    void fetchRangeBelief({ seatId, afterSequence: selectedAction.eventSequence });
    // Request identity is represented by the action id, selected seat and
    // ScenarioSpec. The gate above rejects a response from an older render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, selectedActionId, beliefSeatId]);

  function syncRangeEditor(nextScenario: Scenario) {
    setRangeTextBySide((current) => ({
      heroRange: nextScenario.heroRange ? notationFromMatrix(nextScenario.heroRange.matrix169) : current.heroRange,
      villainRange: nextScenario.villainRange ? notationFromMatrix(nextScenario.villainRange.matrix169) : current.villainRange,
    }));
    const selected = rangeSide === "heroRange" ? nextScenario.heroRange : nextScenario.villainRange;
    setRangeMatrix(selected?.matrix169 ?? {});
    setRangeSummary(null);
    setRangeCombos([]);
  }

  async function loadSaved(record: SavedScenario) {
    invalidateDerivedAnalysisState();
    setPastScenarios([]);
    setFutureScenarios([]);
    setScenario(record.scenario);
    setSelectedActionId(null);
    setBeliefSeatId(null);
    setActiveScenarioId(record.scenarioId);
    setActiveRevisionNo(record.revisionNo);
    setSavedScenarioDirty(false);
    syncRangeEditor(record.scenario);
    setState(null);
    setAnalysis(null);
    setAnalysisStale(false);
    setTeaching(null);
    await refreshState(
      record.scenario,
      `已载入「${record.title}」第 ${record.revisionNo} 个版本。`,
    );
  }

  async function copySaved(record: SavedScenario) {
    try {
      await scenariosApi.copy(record.scenarioId, `${record.title} copy`);
      await loadSavedScenarios();
      setMessage(`已复制「${record.title}」。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "复制失败");
    }
  }

  async function deleteSaved(record: SavedScenario) {
    if (!window.confirm(`确认删除「${record.title}」吗？该场景的分析历史也会删除。`)) return;
    setBusy(true);
    try {
      await scenariosApi.remove(record.scenarioId);
      if (historyScenarioId === record.scenarioId) {
        setHistoryScenarioId(null);
        setSavedAnalyses([]);
        setSavedRevisions([]);
        setComparison(null);
      }
      if (activeScenarioId === record.scenarioId) {
        setActiveScenarioId(null);
        setActiveRevisionNo(null);
        setSavedScenarioDirty(false);
      }
      await loadSavedScenarios();
      setMessage(`已删除「${record.title}」及其分析历史。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadAnalysisHistory(record: SavedScenario) {
    try {
      const [analysisPayload, revisionPayload] = await Promise.all([
        scenariosApi.analyses(record.scenarioId),
        scenariosApi.revisions(record.scenarioId),
      ]);
      const analyses = analysisPayload.analyses ?? [];
      setHistoryScenarioId(record.scenarioId);
      setSavedAnalyses(analyses);
      setSavedRevisions(revisionPayload.revisions ?? []);
      setCompareLeft(analyses[0]?.analysisId ?? "");
      setCompareRight(analyses[1]?.analysisId ?? "");
      setComparison(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "历史分析加载失败");
    }
  }

  async function compareHistory() {
    if (!historyScenarioId || !compareLeft || !compareRight || compareLeft === compareRight) return;
    try {
      const payload = await scenariosApi.compare(historyScenarioId, compareLeft, compareRight);
      setComparison(payload);
      setMessage("历史分析比较完成；差异来自保存的结构化结果。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "历史分析比较失败");
    }
  }

  async function reanalyzeSaved(record: SavedScenario) {
    setBusy(true);
    invalidateDerivedAnalysisState();
    try {
      const payload = await scenariosApi.analyze(record.scenarioId);
      setScenario(record.scenario);
      setSelectedActionId(null);
      setBeliefSeatId(null);
      setActiveScenarioId(record.scenarioId);
      setActiveRevisionNo(record.revisionNo);
      setSavedScenarioDirty(false);
      syncRangeEditor(record.scenario);
      setAnalysis(payload.analysis);
      setAnalysisStale(false);
      await loadAnalysisHistory(record);
      await refreshState(record.scenario);
      setMessage(`已重新分析「${record.title}」；结果已写入历史。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重新分析失败");
    } finally {
      setBusy(false);
    }
  }

  function loadRevision(revision: ScenarioRevision) {
    invalidateDerivedAnalysisState();
    setPastScenarios([]);
    setFutureScenarios([]);
    setScenario(revision.scenario);
    setSelectedActionId(null);
    setBeliefSeatId(null);
    setActiveScenarioId(revision.scenarioId);
    setActiveRevisionNo(revision.revisionNo);
    setSavedScenarioDirty(false);
    syncRangeEditor(revision.scenario);
    setState(null);
    setAnalysis(null);
    setAnalysisStale(false);
    setTeaching(null);
    void refreshState(
      revision.scenario,
      `已载入第 ${revision.revisionNo} 个历史版本。`,
    );
  }

  async function reanalyzeRevision(revision: ScenarioRevision, title: string) {
    setBusy(true);
    invalidateDerivedAnalysisState();
    try {
      const payload = await scenariosApi.analyzeRevision(revision.scenarioId, revision.revisionNo);
      setScenario(revision.scenario);
      setSelectedActionId(null);
      setBeliefSeatId(null);
      setActiveScenarioId(revision.scenarioId);
      setActiveRevisionNo(revision.revisionNo);
      setSavedScenarioDirty(false);
      syncRangeEditor(revision.scenario);
      setAnalysis(payload.analysis);
      setAnalysisStale(false);
      await loadAnalysisHistory({
        scenarioId: revision.scenarioId,
        title,
        scenario: revision.scenario,
        revisionNo: revision.revisionNo,
        updatedAt: revision.createdAt,
      });
      await refreshState(revision.scenario);
      setMessage(`已重新分析「${title}」第 ${revision.revisionNo} 个版本；结果已写入历史。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "历史版本重分析失败");
    } finally {
      setBusy(false);
    }
  }

  function exportScenario() {
    const blob = new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "scenario-spec.json";
    link.click();
    URL.revokeObjectURL(url);
    setMessage("ScenarioSpec 已导出为 JSON。");
  }

  async function importScenarioFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const raw = JSON.parse(await file.text());
      const importedScenario = raw?.scenario ?? raw;
      const payload = await scenariosApi.create({
        scenario: importedScenario,
        title: file.name.replace(/\.json$/i, "") || "Imported scenario",
        tags: ["imported"],
      });
      const record = payload.scenario as SavedScenario;
      invalidateDerivedAnalysisState();
      setPastScenarios([]);
      setFutureScenarios([]);
      setScenario(record.scenario);
      setSelectedActionId(null);
      setBeliefSeatId(null);
      setActiveScenarioId(record.scenarioId);
      setActiveRevisionNo(record.revisionNo);
      setSavedScenarioDirty(false);
      syncRangeEditor(record.scenario);
      setAnalysis(null);
      setTeaching(null);
      setMessage(`已导入「${record.title}」，正在校验场景。`);
      await loadSavedScenarios();
      await refreshState(record.scenario);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function refreshState(
    nextScenario = workspaceScenario,
    successMessage?: string,
    syncEditorDecision = !selectedAction,
  ) {
    const requestToken = ++stateRefreshToken.current;
    setBusy(true);
    try {
      const payload = await scenariosApi.state(nextScenario);
      if (stateRefreshToken.current !== requestToken) return;
      setState(payload.finalState);
      if (syncEditorDecision) {
        setScenario((current) => ({
          ...current,
          decisionPoint: {
            street: payload.finalState.street,
            actorSeat: payload.finalState.actorSeat ?? current.heroSeat,
            afterSequence: nextScenario.decisionPoint.afterSequence,
          },
        }));
      }
      setMessage(successMessage ?? "规则校验通过，当前状态已更新。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "规则校验失败");
    } finally {
      if (stateRefreshToken.current === requestToken) setBusy(false);
    }
  }

  async function appendAction(actionType: string, requestedAmount?: number) {
    if (!legal?.actorSeat && legal?.actorSeat !== 0) return;
    const amount = actionType === "call" ? legal.callAmount ?? undefined : ["raise_to", "bet", "all_in"].includes(actionType) ? requestedAmount ?? (actionType === "all_in" ? legal.maxRaiseTo ?? undefined : legal.minRaiseTo ?? undefined) : undefined;
    const amountType = actionType === "call" ? "cost" : actionType === "bet" ? "by" : ["raise_to", "all_in"].includes(actionType) ? "to" : undefined;
    const event: ActionEvent = {
      actionId: `${actionType}-${Date.now()}`,
      sequence: scenario.actionHistory.length + 1,
      street: currentStreet,
      actorSeat: legal.actorSeat,
      actionType,
      ...(amount === undefined ? {} : { amount }),
      ...(amountType === undefined ? {} : { amountType }),
    };
    const actionHistory = [...scenario.actionHistory, event];
    const next = { ...scenario, actionHistory, decisionPoint: { street: currentStreet, actorSeat: legal.actorSeat, afterSequence: actionHistory.length } };
    commitScenario(next);
    setSelectedActionId(event.actionId);
    setBeliefSeatId(event.actorSeat);
    await refreshState(next, undefined, true);
  }

  async function deal(street: "deal_flop" | "deal_turn" | "deal_river") {
    const actionHistory = [
      ...scenario.actionHistory,
      {
        actionId: `${street}-${Date.now()}`,
        sequence: scenario.actionHistory.length + 1,
        street: street.replace("deal_", ""),
        actorSeat: state?.actorSeat ?? scenario.heroSeat,
        actionType: street,
      },
    ];
    const next = {
      ...scenario,
      actionHistory,
      decisionPoint: { street: street.replace("deal_", ""), actorSeat: state?.actorSeat ?? scenario.heroSeat, afterSequence: actionHistory.length },
    };
    commitScenario(next);
    await refreshState(next);
  }

  function selectAction(actionId: string) {
    const selection = selectionForAction(scenario.actionHistory, actionId);
    if (!selection) return;
    invalidateRangeBelief();
    if (selectedActionId === selection.actionId) {
      setSelectedActionId(null);
      setBeliefSeatId(null);
      void refreshState(scenario, undefined, true);
      return;
    }
    setSelectedActionId(selection.actionId);
    setBeliefSeatId(selection.actorSeat);
    setBeliefMode("current");
    void refreshState(projectSelectedDecisionScenario(scenario, selection), undefined, false);
  }

  async function runAnalysis() {
    setBusy(true);
    try {
      const currentRevisionNo = activeScenarioId
        ? savedScenarios.find((item) => item.scenarioId === activeScenarioId)?.revisionNo
        : undefined;
      const historicalRevision = Boolean(
        activeScenarioId &&
        activeRevisionNo &&
        currentRevisionNo &&
        activeRevisionNo < currentRevisionNo,
      );
      const path = historicalRevision
        ? `/v1/scenarios/${activeScenarioId}/revisions/${activeRevisionNo}/analyze`
        : activeScenarioId
          ? `/v1/scenarios/${activeScenarioId}/analyze`
          : "/v1/analysis";
      const analysisPath = !selectedAction && activeScenarioId && !savedScenarioDirty ? path : "/v1/analysis";
      const payload =
        analysisPath === "/v1/analysis"
          ? await analysisApi.run(workspaceScenario)
          : historicalRevision
            ? await scenariosApi.analyzeRevision(activeScenarioId!, activeRevisionNo!)
            : await scenariosApi.analyze(activeScenarioId!);
      setAnalysis(payload.analysis);
      setAnalysisStale(false);
      setMessage("分析完成。所有定量结果都来自结构化证据。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "分析失败");
    } finally {
      setBusy(false);
    }
  }

  async function saveScenario() {
    setBusy(true);
    try {
      const payload = activeScenarioId
        ? await scenariosApi.update(activeScenarioId, { scenario, title: "Manual review", tags: [currentStreet] })
        : await scenariosApi.create({ scenario, title: "Manual review", tags: [currentStreet] });
      setActiveScenarioId(payload.scenario.scenarioId);
      setActiveRevisionNo(payload.scenario.revisionNo);
      setSavedScenarioDirty(false);
      await loadSavedScenarios();
      setMessage(activeScenarioId ? "场景已更新，已生成新的历史修订。" : "场景已保存，可在历史记录中复制和重新分析。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  function setCurrentRangeText(value: string) {
    setRangeTextBySide((current) => ({ ...current, [rangeSide]: value }));
  }

  async function applyDefaultRange(key: string) {
    const selected = defaultRanges[key];
    if (!selected) return;
    const notation = notationFromMatrix(selected.matrix169);
    setCurrentRangeText(notation);
    setRangeMatrix(selected.matrix169);
    await normalizeRange(notation, rangeSide);
  }

  async function normalizeRange(notation = rangeText, side = rangeSide) {
    try {
      const targetSeat = beliefSeatForSide(side);
      const deadCards = targetSeat == null
        ? [...scenario.board]
        : deadCardsForSeat(scenario, targetSeat);
      const payload = await rangesApi.parse(notation, deadCards);
      setRangeMatrix(payload.range.matrix169);
      setRangeSummary(payload.summary);
      setRangeCombos(payload.combos ?? []);
      setCurrentRangeText(notation);
      updateScenario({ [side]: payload.range } as Partial<Scenario>);
      setMessage(`${side === "heroRange" ? "Hero" : "Villain"} 范围已标准化为 ${Object.keys(payload.range.matrix169).length} 个矩阵格。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "范围解析失败");
    }
  }

  async function parseRange() {
    await normalizeRange();
  }

  async function cycleRangeCell(cell: string) {
    const weights = ["", "0.25", "0.5", "0.75", "1"];
    const current = rangeMatrix[cell] ?? "";
    const next = weights[(weights.indexOf(current) + 1) % weights.length];
    const nextMatrix = { ...rangeMatrix };
    if (next) nextMatrix[cell] = next;
    else delete nextMatrix[cell];
    const notation = notationFromMatrixExplicit(nextMatrix);
    setCurrentRangeText(notation);
    setRangeMatrix(nextMatrix);
    await normalizeRange(notation, rangeSide);
  }

  async function runTeaching() {
    setBusy(true);
    try {
      const payload = await coachApi.explain({ scenario: workspaceScenario, depth: teachingDepth, question: teachingQuestion || undefined });
      setTeaching(payload.response);
      setTeachingMeta({
        provider: payload.provider ?? "local",
        degraded: payload.degraded ?? false,
        teacherVersion: payload.teacherVersion ?? "unknown",
      });
      setMessage("教学解释已生成；定量结论仍受 EvidenceBundle 约束。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "教学解释失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitSolve() {
    setBusy(true);
    try {
      const payload = await solverApi.submit(workspaceScenario);
      setSolveJob(payload);
      void pollSolveJob(payload.jobId);
      setMessage("求解作业已提交（独立 Solver 容器执行，通常 1–3 分钟）。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "求解提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancelSolve() {
    if (!solveJob) return;
    setBusy(true);
    try {
      const payload = await solverApi.cancel(solveJob.jobId);
      setSolveJob((job) => (job ? { ...job, status: payload.status } : job));
      setMessage(`求解取消请求已发送（${payload.status}）。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "取消请求失败");
    } finally {
      setBusy(false);
    }
  }

  async function pollSolveJob(jobId: string) {
    const token = ++solvePollToken.current;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      if (solvePollToken.current !== token) return; // superseded by a newer poll
      try {
        const payload = await solverApi.get(jobId);
        if (solvePollToken.current !== token) return;
        // Merge onto the previous job instead of replacing it: the submit
        // response's spot (assumptions -> bunching_ignored) must survive
        // every poll cycle.
        const pollPayload = { ...payload, jobId };
        const freshJob = applySolvePoll(solveJob, pollPayload);
        // Use a functional merge for React state (the poll closure may have
        // captured the initial null job), but use the freshly returned API
        // payload for the belief request below.
        setSolveJob((previous) => applySolvePoll(previous, pollPayload));
        if (["solved", "failed", "cancelled"].includes(payload.status)) {
          setMessage(
            payload.status === "solved"
              ? "求解完成；策略频率可作为 solver_backed 证据引用。"
              : `求解${payload.status}${payload.error ? `：${payload.error}` : ""}`,
          );
          if (payload.status === "solved") {
            if (selectedAction) {
              void fetchRangeBelief({
                seatId: beliefSeatId ?? selectedAction.actorSeat,
                afterSequence: selectedAction.eventSequence,
                job: freshJob,
              });
            }
          }
          return;
        }
      } catch {
        return;
      }
    }
  }

  async function generatePractice() {
    setBusy(true);
    try {
      const payload = await practiceApi.generate({ scenario: workspaceScenario, profileId: "local-browser", mistakeTag: "pot_odds" });
      setPractice(payload.question);
      setPracticeOutcome(null);
      setMessage("验证练习已生成；先选择行动，再查看证据答案。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "练习生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function answerPractice(action: string) {
    if (!practice) return;
    setBusy(true);
    try {
      const payload = await practiceApi.attempt(practice.questionId, action);
      setPracticeOutcome(payload.outcome);
      setMessage("练习已评分；答案来自保存的验证分析。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "练习评分失败");
    } finally {
      setBusy(false);
    }
  }

  // Solve gate: the sidecar is a heads-up postflop solver, so submissions
  // require a postflop decision point, exactly two active players, and
  // ranges for them (legacy hero/villain or Schema v2 rangesBySeat). The
  // backend re-validates every spot; this only blocks obviously invalid
  // submissions.
  const canSubmitSolve = solveGate(workspaceScenario, state, currentStreet, busy);
  const solveReasons = solveGateReasons(workspaceScenario, state, currentStreet);

  const handLab = (
    <>
      <div className="workspace">
        <aside className="left-rail">
          <section className="panel editor-panel">
            <ScenarioEditor
              scenario={scenario}
              boardInput={boardInput}
              busy={busy}
              canUndo={pastScenarios.length > 0}
              canRedo={futureScenarios.length > 0}
              onReset={() => void resetScenario()}
              onUndo={undo}
              onRedo={redo}
              onUpdateScenario={updateScenario}
              onUpdateBoard={updateBoard}
            />
          </section>

          <ScenarioHistory
            savedScenarios={savedScenarios}
            historyScenarioId={historyScenarioId}
            savedRevisions={savedRevisions}
            savedAnalyses={savedAnalyses}
            compareLeft={compareLeft}
            compareRight={compareRight}
            comparison={comparison}
            activeScenarioId={activeScenarioId}
            onRefresh={() => void loadSavedScenarios()}
            onLoad={loadSaved}
            onLoadHistory={(record) => void loadAnalysisHistory(record)}
            onReanalyze={(record) => void reanalyzeSaved(record)}
            onDelete={(record) => void deleteSaved(record)}
            onCopy={(record) => void copySaved(record)}
            onLoadRevision={loadRevision}
            onReanalyzeRevision={(revision, title) => void reanalyzeRevision(revision, title)}
            onCompareLeftChange={setCompareLeft}
            onCompareRightChange={setCompareRight}
            onCompare={() => void compareHistory()}
          />

          <section className="panel compact-panel">
            <ActionTimeline
              events={scenario.actionHistory}
              selectedActionId={selectedActionId}
              onSelectAction={selectAction}
              onRefresh={() => void refreshState()}
            />
          </section>
        </aside>

        <main className="table-area">
          <section className="panel table-panel">
            <div className="table-toolbar">
              <span className="muted small">金额单位</span>
              <div className="unit-toggle" role="group" aria-label="金额单位">
                <button
                  type="button"
                  className={displayUnit === "bb" ? "unit-toggle__active" : ""}
                  onClick={() => setDisplayUnit("bb")}
                  aria-pressed={displayUnit === "bb"}
                >
                  BB
                </button>
                <button
                  type="button"
                  className={displayUnit === "chips" ? "unit-toggle__active" : ""}
                  onClick={() => setDisplayUnit("chips")}
                  aria-pressed={displayUnit === "chips"}
                >
                  Chips
                </button>
              </div>
            </div>
            <PokerTable
              seats={tableSeats}
              board={workspaceScenario.board}
              pot={state?.pot ?? null}
              unit={displayUnit}
              bigBlind={scenario.bigBlind}
            />
            <ActionBar
              legal={legal ?? null}
              currentStreet={currentStreet}
              busy={busy || Boolean(selectedAction)}
              boardLength={workspaceScenario.board.length}
              raiseAmount={raiseAmount}
              pot={state?.pot ?? null}
              actorPosition={actorPosition}
              unit={displayUnit}
              bigBlind={scenario.bigBlind}
              onRaiseAmountChange={setRaiseAmount}
              onAction={(actionType, requestedAmount) => void appendAction(actionType, requestedAmount)}
              onDeal={(street) => void deal(street)}
            />
          </section>
        </main>

        <aside className="right-rail">
          <RangeEditor
            rangeSide={rangeSide}
            rangeText={rangeText}
            defaultRanges={defaultRanges}
            rangeMatrix={rangeMatrix}
            rangeSummary={rangeSummary}
            rangeCombos={rangeCombos}
            belief={rangeBelief}
            beliefLoading={rangeBeliefLoading}
            beliefStale={rangeBeliefStale}
            beliefMode={beliefMode}
            beliefSeatId={beliefSeatId ?? selectedAction?.actorSeat ?? beliefSeatForSide(rangeSide)}
            beliefSeats={scenario.seats}
            beliefEventSequence={selectedAction?.eventSequence ?? null}
            beliefDecisionSequence={selectedAction?.decisionSequence ?? null}
            onRangeSideChange={selectRangeSide}
            onRangeTextChange={setCurrentRangeText}
            onApplyDefault={(key) => void applyDefaultRange(key)}
            onParse={() => void parseRange()}
            onCycleCell={(cell) => void cycleRangeCell(cell)}
            onBeliefModeChange={setBeliefMode}
            onBeliefSeatChange={selectBeliefSeat}
          />

          <AnalyzeActions
            busy={busy}
            teachingDepth={teachingDepth}
            teachingQuestion={teachingQuestion}
            message={message}
            onTeachingDepthChange={setTeachingDepth}
            onTeachingQuestionChange={setTeachingQuestion}
            onValidate={() => void refreshState()}
            onAnalyze={() => void runAnalysis()}
            onTeach={() => void runTeaching()}
            onPractice={() => void generatePractice()}
            onSave={() => void saveScenario()}
            onExport={exportScenario}
            onImportFile={(event) => void importScenarioFile(event)}
          />
        </aside>
      </div>

      <ResultWorkspace
        activeTab={resultTab}
        onTabChange={setResultTab}
        analysis={analysis}
        analysisStale={analysisStale}
        teaching={teaching}
        teachingMeta={teachingMeta}
        practice={practice}
        practiceOutcome={practiceOutcome}
        legalActions={state?.legalActions.actions ?? []}
        busy={busy}
        solveJob={solveJob}
        canSubmitSolve={canSubmitSolve}
        heroHoleCards={heroCards(workspaceScenario)}
        seats={workspaceScenario.seats}
        heroSeat={workspaceScenario.heroSeat}
        solveGate={solveReasons}
        onSolveSubmit={() => void submitSolve()}
        onSolveCancel={() => void cancelSolve()}
        onPracticeAnswer={(action) => void answerPractice(action)}
      />
    </>
  );

  const solverView = (
    <div className="focused-view">
      <section className="panel table-panel">
        <PokerTable
          seats={tableSeats}
          board={workspaceScenario.board}
          pot={state?.pot ?? null}
          unit={displayUnit}
          bigBlind={scenario.bigBlind}
        />
      </section>
      <SolverWorkspace
        solveJob={solveJob}
        canSubmit={canSubmitSolve}
        heroHoleCards={heroCards(workspaceScenario)}
        gate={solveReasons}
        onSubmit={() => void submitSolve()}
        onCancel={() => void cancelSolve()}
      />
    </div>
  );

  const trainView = (
    <div className="focused-view">
      {teaching ? (
        <TeachingPanel teaching={teaching} teachingMeta={teachingMeta} />
      ) : (
        <p className="muted view-placeholder">先在 Hand Lab 中点击「教学解释」生成教学回答。</p>
      )}
      {practice ? (
        <PracticePanel
          practice={practice}
          practiceOutcome={practiceOutcome}
          legalActions={state?.legalActions.actions ?? []}
          busy={busy}
          onAnswer={(action) => void answerPractice(action)}
        />
      ) : (
        <p className="muted view-placeholder">先在 Hand Lab 中点击「生成练习」创建验证练习。</p>
      )}
    </div>
  );

  const libraryView = (
    <div className="focused-view">
      <ScenarioHistory
        savedScenarios={savedScenarios}
        historyScenarioId={historyScenarioId}
        savedRevisions={savedRevisions}
        savedAnalyses={savedAnalyses}
        compareLeft={compareLeft}
        compareRight={compareRight}
        comparison={comparison}
        activeScenarioId={activeScenarioId}
        onRefresh={() => void loadSavedScenarios()}
        onLoad={loadSaved}
        onLoadHistory={(record) => void loadAnalysisHistory(record)}
        onReanalyze={(record) => void reanalyzeSaved(record)}
        onDelete={(record) => void deleteSaved(record)}
        onCopy={(record) => void copySaved(record)}
        onLoadRevision={loadRevision}
        onReanalyzeRevision={(revision, title) => void reanalyzeRevision(revision, title)}
        onCompareLeftChange={setCompareLeft}
        onCompareRightChange={setCompareRight}
        onCompare={() => void compareHistory()}
      />
    </div>
  );

  return (
    <AppShell activeView={activeView} onViewChange={setActiveView}>
      {activeView === "handlab" && handLab}
      {activeView === "solver" && solverView}
      {activeView === "train" && trainView}
      {activeView === "library" && libraryView}
      <footer>
        <span>ScenarioSpec → Replay → EvidenceBundle</span>
        <span>无 Solver 频率 · 无自动行动</span>
      </footer>
    </AppShell>
  );
}
