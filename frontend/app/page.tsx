"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";

type ActionEvent = {
  actionId: string;
  sequence: number;
  street: string;
  actorSeat: number;
  actionType: string;
  amount?: number;
  amountType?: string;
};

type Scenario = {
  schemaVersion: number;
  gameVariant: string;
  tableSize: number;
  smallBlind: number;
  bigBlind: number;
  buttonSeat: number;
  heroSeat: number;
  seats: { seatId: number; startingStack: number; position: string }[];
  heroHoleCards: string[];
  villainHoleCards?: string[];
  board: string[];
  actionHistory: ActionEvent[];
  decisionPoint: { street: string; actorSeat: number; afterSequence: number };
  assumptions: Record<string, unknown>;
  heroRange?: RangeSpecPayload;
  villainRange?: RangeSpecPayload;
};

type RangeSpecPayload = {
  rangeId: string;
  name: string;
  version: string;
  source: string;
  isDefaultAssumption?: boolean;
  matrix169: Record<string, string>;
};

type RangeSide = "heroRange" | "villainRange";

type StateResponse = {
  finalState: {
    street: string;
    actorSeat: number | null;
    board: string[];
    pot: number;
    stacks: Record<string, number>;
    bets: Record<string, number>;
    legalActions: {
      actorSeat: number | null;
      actions: string[];
      callAmount: number | null;
      minRaiseTo: number | null;
      maxRaiseTo: number | null;
      explanations: Record<string, string>;
    };
  };
};

type AnalysisResponse = {
  analysis: {
    metrics: Record<string, string | number | null>;
    hand: { category: string; madeHand: string; draws: string[]; outCount: number; overcards: string[]; outCards: string[]; counterfeitRiskCards: string[] };
    board: { labels: string[]; staticOrDynamic: string; nutComboCount: number; nextStreetChangeCards: string[] };
    equity: { heroEquity: string; villainEquity: string; tieProbability: string; sourceLevel: string } | null;
    rangeAnalysis?: { totalCombos: number; weightedCombos: string; valueCombos: number; bluffCombos: number; drawCombos: number; blockedCombos: number; blockedWeight: string; blockerCards: string[]; polarity: string; heuristic: boolean } | null;
    rangeComparison?: { rangeAdvantage: string | null; nutAdvantage: string | null; equityDistribution: Record<string, string>; heuristic: boolean } | null;
    strategyMatch: {
      level: string;
      similarity: string;
      canQuoteFrequencies: boolean;
      explanation: string;
      differences: { field: string; requested: unknown; artifact: unknown; impact: string }[];
      recommendations: { action: string; summary: string; frequency?: string | null; ev?: string | null }[];
    } | null;
    evidence: { items: { evidenceId: string; kind: string; value: unknown; sourceLevel: string; description: string }[] };
    warnings: string[];
  };
};

type TeachingResponse = {
  response: {
    explanationDepth: string;
    summary: { text: string };
    recommendedActions: { action: string; frequency?: string | null }[];
    keyReasons: { text: string }[];
    uncertainty: { text: string };
    conceptTags?: string[];
    followUpQuestion?: string | null;
  };
  provider?: string;
  degraded?: boolean;
  teacherVersion?: string;
  promptVersion?: string;
};

type TeachingMeta = {
  provider: string;
  degraded: boolean;
  teacherVersion: string;
};

type SolverNodePayload = {
  actions: string[];
  player: number;
  hands: { combo: string; weight: number; equity: number; ev: number; strategy: Record<string, number> }[];
};

type SolveJob = {
  jobId: string;
  status: string;
  error?: string | null;
  executionMs?: number | null;
  result?: {
    metadata?: {
      solver: string;
      version: string;
      exploitabilityChips: number;
      solveTimeMs: number;
      maxIterations: number;
    };
    root?: SolverNodePayload;
    responseNode?: SolverNodePayload;
  } | null;
};

function solvePrimary(node?: SolverNodePayload | null): { action: string; frequency: number } | null {
  if (!node || !node.hands.length) return null;
  const total = node.hands.reduce((sum, hand) => sum + hand.weight, 0) || 1;
  const weighted: Record<string, number> = {};
  for (const hand of node.hands) {
    for (const [action, frequency] of Object.entries(hand.strategy)) {
      weighted[action] = (weighted[action] ?? 0) + hand.weight * frequency;
    }
  }
  const action = Object.keys(weighted).sort((a, b) => weighted[b] - weighted[a])[0];
  return { action, frequency: (weighted[action] ?? 0) / total };
}

function solveHeroCombo(node: SolverNodePayload | undefined | null, cards: string[]): SolverNodePayload["hands"][number] | null {
  if (!node || cards.length !== 2) return null;
  return node.hands.find((hand) => {
    const comboSet = new Set([hand.combo.slice(0, 2), hand.combo.slice(2, 4)]);
    return cards.every((card) => comboSet.has(card));
  }) ?? null;
}

type PracticeQuestion = {
  questionId: string;
  profileId: string;
  prompt: string;
  conceptTags: string[];
  scenario: Scenario;
};

type PracticeOutcome = {
  attempt: { correct: boolean; selectedAction: string };
  expectedAction: string;
  explanation: string;
  evidenceReferences: { evidenceId: string }[];
};

type SavedScenario = {
  scenarioId: string;
  title: string;
  scenario: Scenario;
  revisionNo: number;
  updatedAt: string;
};

type ScenarioRevision = {
  scenarioId: string;
  revisionNo: number;
  scenario: Scenario;
  createdAt: string;
};

type RangeCombo = { cards: string[]; weight: string };
type RangeSummary = { totalCombos: number; weightedCombos: string };
type DefaultRanges = Record<string, RangeSpecPayload>;
type AnalysisRun = { analysisId: string; revisionNo: number; createdAt: string; output?: { board?: { board?: string[] } } };
type AnalysisComparison = { differences: { field: string; left: unknown; right: unknown }[]; versions: Record<string, { rulesEngineVersion: string; analysisVersion: string }> };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

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
  heroHoleCards: ["As", "Kd"],
  villainHoleCards: ["Qh", "Jc"],
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

  useEffect(() => {
    void loadSavedScenarios();
    void loadDefaultRanges();
    void refreshState(initialScenario);
  }, []);

  const rangeText = rangeTextBySide[rangeSide];

  const hasDealFlop = scenario.actionHistory.some((event) => event.actionType === "deal_flop");
  const hasDealTurn = scenario.actionHistory.some((event) => event.actionType === "deal_turn");
  const hasDealRiver = scenario.actionHistory.some((event) => event.actionType === "deal_river");
  const pendingDealStreet = state?.actorSeat === null
    ? (!hasDealFlop && scenario.board.length >= 3
      ? "preflop"
      : !hasDealTurn && scenario.board.length >= 4
        ? "flop"
        : !hasDealRiver && scenario.board.length >= 5
          ? "turn"
          : null)
    : null;
  const currentStreet = pendingDealStreet ?? state?.street ?? scenario.decisionPoint.street;
  const legal = state?.legalActions;
  const boardInput = useMemo(() => [...scenario.board, "", "", "", "", ""].slice(0, 5), [scenario.board]);

  function updateScenario(patch: Partial<Scenario>) {
    commitScenario({ ...scenario, ...patch });
    setMessage("场景已修改，需要重新校验或分析。");
  }

  function commitScenario(next: Scenario) {
    setPastScenarios((past) => [...past, scenario]);
    setFutureScenarios([]);
    setScenario(next);
    setSavedScenarioDirty(Boolean(activeScenarioId));
    setAnalysisStale(Boolean(analysis));
    setTeaching(null);
    setPractice(null);
    setPracticeOutcome(null);
  }

  function undo() {
    const previous = pastScenarios[pastScenarios.length - 1];
    if (!previous) return;
    setPastScenarios((past) => past.slice(0, -1));
    setFutureScenarios((future) => [scenario, ...future]);
    setScenario(previous);
    setSavedScenarioDirty(Boolean(activeScenarioId));
    setAnalysisStale(Boolean(analysis));
    setTeaching(null);
    setPractice(null);
    setPracticeOutcome(null);
  }

  function redo() {
    const next = futureScenarios[0];
    if (!next) return;
    setFutureScenarios((future) => future.slice(1));
    setPastScenarios((past) => [...past, scenario]);
    setScenario(next);
    setSavedScenarioDirty(Boolean(activeScenarioId));
    setAnalysisStale(Boolean(analysis));
    setTeaching(null);
    setPractice(null);
    setPracticeOutcome(null);
  }

  async function resetScenario() {
    const next = structuredClone(initialScenario) as Scenario;
    commitScenario(next);
    setActiveScenarioId(null);
    setActiveRevisionNo(null);
    setSavedScenarioDirty(false);
    syncRangeEditor(next);
    setState(null);
    setAnalysis(null);
    setAnalysisStale(false);
    setMessage("场景已重置；原场景仍可通过撤销恢复。");
    await refreshState(next);
  }

  function updateCards(field: "heroHoleCards" | "villainHoleCards", index: number, value: string) {
    const cards = [...(scenario[field] ?? ["", ""])] as string[];
    cards[index] = value.trim();
    updateScenario({ [field]: cards } as Partial<Scenario>);
  }

  function updateBoard(index: number, value: string) {
    const board = [...boardInput];
    board[index] = value.trim();
    updateScenario({ board: board.filter(Boolean) });
  }

  function errorMessage(payload: unknown, fallback: string): string {
    const error = (payload as { error?: { message?: string; details?: unknown } })?.error;
    let message = error?.message ?? fallback;
    const details = error?.details;
    if (Array.isArray(details) && details.length > 0) {
      const first = details[0] as { msg?: string };
      if (first?.msg) message = `${message}：${first.msg}`;
    }
    return message;
  }

  async function request(path: string, body: unknown, method: "POST" | "PUT" = "POST") {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "请求失败"));
    return payload;
  }

  async function requestGet(path: string) {
    const response = await fetch(`${API_BASE}${path}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "请求失败"));
    return payload;
  }

  async function requestDelete(path: string) {
    const response = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "请求失败"));
    return payload;
  }

  async function loadSavedScenarios() {
    try {
      const payload = await requestGet("/v1/scenarios");
      setSavedScenarios(payload.scenarios ?? []);
    } catch {
      // Local API may not be running on the first page load.
    }
  }

  async function loadDefaultRanges() {
    try {
      const payload = await requestGet("/v1/ranges/defaults");
      setDefaultRanges(payload.ranges ?? {});
    } catch {
      // Default range loading is optional; manual notation remains available.
    }
  }

  function selectRangeSide(side: RangeSide) {
    setRangeSide(side);
    const selected = side === "heroRange" ? scenario.heroRange : scenario.villainRange;
    setRangeMatrix(selected?.matrix169 ?? {});
    setRangeSummary(null);
    setRangeCombos([]);
  }

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

  function loadSaved(record: SavedScenario) {
    setPastScenarios([]);
    setFutureScenarios([]);
    setScenario(record.scenario);
    setActiveScenarioId(record.scenarioId);
    setActiveRevisionNo(record.revisionNo);
    setSavedScenarioDirty(false);
    syncRangeEditor(record.scenario);
    setState(null);
    setAnalysis(null);
    setAnalysisStale(false);
    setTeaching(null);
    setMessage(`已载入「${record.title}」第 ${record.revisionNo} 个版本。`);
  }

  async function copySaved(record: SavedScenario) {
    try {
      await request(`/v1/scenarios/${record.scenarioId}/copy`, { title: `${record.title} copy` });
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
      await requestDelete(`/v1/scenarios/${record.scenarioId}`);
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
        requestGet(`/v1/scenarios/${record.scenarioId}/analyses`),
        requestGet(`/v1/scenarios/${record.scenarioId}/revisions`),
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
      const payload = await requestGet(`/v1/scenarios/${historyScenarioId}/analyses/compare?leftAnalysisId=${encodeURIComponent(compareLeft)}&rightAnalysisId=${encodeURIComponent(compareRight)}`);
      setComparison(payload);
      setMessage("历史分析比较完成；差异来自保存的结构化结果。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "历史分析比较失败");
    }
  }

  async function reanalyzeSaved(record: SavedScenario) {
    setBusy(true);
    try {
      const payload = await request(`/v1/scenarios/${record.scenarioId}/analyze`, {});
      setScenario(record.scenario);
      setActiveScenarioId(record.scenarioId);
      setActiveRevisionNo(record.revisionNo);
      setSavedScenarioDirty(false);
      syncRangeEditor(record.scenario);
      setAnalysis(payload.analysis);
      setAnalysisStale(false);
      await loadAnalysisHistory(record);
      setMessage(`已重新分析「${record.title}」；结果已写入历史。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重新分析失败");
    } finally {
      setBusy(false);
    }
  }

  function loadRevision(revision: ScenarioRevision) {
    setPastScenarios([]);
    setFutureScenarios([]);
    setScenario(revision.scenario);
    setActiveScenarioId(revision.scenarioId);
    setActiveRevisionNo(revision.revisionNo);
    setSavedScenarioDirty(false);
    syncRangeEditor(revision.scenario);
    setState(null);
    setAnalysis(null);
    setAnalysisStale(false);
    setTeaching(null);
    setMessage(`已载入第 ${revision.revisionNo} 个历史版本。`);
  }

  async function reanalyzeRevision(revision: ScenarioRevision, title: string) {
    setBusy(true);
    try {
      const payload = await request(
        `/v1/scenarios/${revision.scenarioId}/revisions/${revision.revisionNo}/analyze`,
        {},
      );
      setScenario(revision.scenario);
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
      const payload = await request("/v1/scenarios", {
        scenario: importedScenario,
        title: file.name.replace(/\.json$/i, "") || "Imported scenario",
        tags: ["imported"],
      });
      const record = payload.scenario as SavedScenario;
      setPastScenarios([]);
      setFutureScenarios([]);
      setScenario(record.scenario);
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

  async function refreshState(nextScenario = scenario) {
    setBusy(true);
    try {
      const payload = await request("/v1/scenarios/state", nextScenario);
      setState(payload.finalState);
      setScenario((current) => ({
        ...current,
        decisionPoint: {
          street: payload.finalState.street,
          actorSeat: payload.finalState.actorSeat ?? current.heroSeat,
          afterSequence: nextScenario.decisionPoint.afterSequence,
        },
      }));
      setMessage("规则校验通过，当前状态已更新。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "规则校验失败");
    } finally {
      setBusy(false);
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
    await refreshState(next);
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

  async function selectNode(sequence: number, street: string) {
    const next = { ...scenario, decisionPoint: { ...scenario.decisionPoint, street, afterSequence: sequence } };
    commitScenario(next);
    await refreshState(next);
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
      const analysisPath = activeScenarioId && !savedScenarioDirty ? path : "/v1/analysis";
      const payload = await request(analysisPath, analysisPath === "/v1/analysis" ? scenario : {});
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
      const path = activeScenarioId ? `/v1/scenarios/${activeScenarioId}` : "/v1/scenarios";
      const payload = await request(
        path,
        { scenario, title: "Manual review", tags: [currentStreet] },
        activeScenarioId ? "PUT" : "POST",
      );
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

  function notationFromMatrix(matrix: Record<string, string>) {
    return Object.entries(matrix)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([hand, weight]) => `${hand}${weight === "1" ? "" : `@${weight}`}`)
      .join(" ");
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
      const deadCards = side === "heroRange"
        ? [...scenario.heroHoleCards, ...(scenario.villainHoleCards ?? []), ...scenario.board]
        : [...scenario.heroHoleCards, ...scenario.board];
      const payload = await request("/v1/ranges/parse", { notation, deadCards });
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
    const notation = Object.entries(nextMatrix)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([hand, weight]) => `${hand}@${weight}`)
      .join(" ");
    setCurrentRangeText(notation);
    setRangeMatrix(nextMatrix);
    await normalizeRange(notation, rangeSide);
  }

  async function runTeaching() {
    setBusy(true);
    try {
      const payload = await request("/v1/teaching", { scenario, depth: teachingDepth, question: teachingQuestion || undefined });
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
      const payload = await request("/v1/solve/jobs", { scenario, maxIterations: 200 });
      setSolveJob({ jobId: payload.jobId, status: payload.status });
      void pollSolveJob(payload.jobId);
      setMessage("求解作业已提交（独立 Solver 容器执行，通常 1–3 分钟）。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "求解提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function pollSolveJob(jobId: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      try {
        const payload = await requestGet(`/v1/solve/jobs/${jobId}`);
        setSolveJob({
          jobId,
          status: payload.status,
          error: payload.error,
          executionMs: payload.executionMs,
          result: payload.result,
        });
        if (["solved", "failed", "cancelled"].includes(payload.status)) {
          setMessage(
            payload.status === "solved"
              ? "求解完成；策略频率可作为 solver_backed 证据引用。"
              : `求解${payload.status}${payload.error ? `：${payload.error}` : ""}`,
          );
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
      const payload = await request("/v1/practice/generate", { scenario, profileId: "local-browser", mistakeTag: "pot_odds" });
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
      const payload = await request(`/v1/practice/${practice.questionId}/attempt`, { selectedAction: action });
      setPracticeOutcome(payload.outcome);
      setMessage("练习已评分；答案来自保存的验证分析。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "练习评分失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">RIVERLINE / HU NLHE</p>
          <h1>Decision Lab</h1>
        </div>
        <div className="status-pill"><span className="pulse" />本地规则核心在线</div>
      </header>

      <div className="workspace-grid">
        <section className="panel editor-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">01 · SCENARIO</p><h2>构造决策场景</h2></div>
            <div className="heading-actions"><span className="muted">{scenario.actionHistory.length} events</span><button className="text-button" onClick={() => void resetScenario()} disabled={busy}>重置场景</button><button className="icon-button" onClick={undo} disabled={!pastScenarios.length || busy} aria-label="撤销">↶</button><button className="icon-button" onClick={redo} disabled={!futureScenarios.length || busy} aria-label="重做">↷</button></div>
          </div>

          <div className="table-card">
            <div className="felt">
              <div className="seat seat-left"><span>BB · Seat 1</span><strong>{state?.stacks["1"] ?? "10,000"}</strong></div>
              <div className="board-row">
                {boardInput.map((card, index) => <span className={`board-card ${card ? "filled" : "empty"}`} key={index}>{card || "·"}</span>)}
              </div>
              <div className="pot-label">POT <strong>{state?.pot ?? 150}</strong></div>
              <div className="seat seat-right"><span>BTN · Hero</span><strong>{state?.stacks["0"] ?? "9,950"}</strong></div>
            </div>
          </div>

          <div className="form-grid">
            <label>Hero 手牌<input value={scenario.heroHoleCards.join(" ")} onChange={(event) => updateScenario({ heroHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2) })} /></label>
            <label>Villain 手牌<input value={(scenario.villainHoleCards ?? []).join(" ")} onChange={(event) => updateScenario({ villainHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2) })} /></label>
          </div>
          <div className="settings-grid">
            <label>小盲<input type="number" min="1" value={scenario.smallBlind} onChange={(event) => updateScenario({ smallBlind: Number(event.target.value) || 1 })} /></label>
            <label>大盲<input type="number" min="1" value={scenario.bigBlind} onChange={(event) => updateScenario({ bigBlind: Number(event.target.value) || 1 })} /></label>
            <label>Hero 起始筹码<input type="number" min="1" value={scenario.seats[0].startingStack} onChange={(event) => updateScenario({ seats: scenario.seats.map((seat, index) => index === 0 ? { ...seat, startingStack: Number(event.target.value) || 1 } : seat) })} /></label>
            <label>Villain 起始筹码<input type="number" min="1" value={scenario.seats[1].startingStack} onChange={(event) => updateScenario({ seats: scenario.seats.map((seat, index) => index === 1 ? { ...seat, startingStack: Number(event.target.value) || 1 } : seat) })} /></label>
          </div>
          <div className="card-inputs">
            {boardInput.map((card, index) => <input aria-label={`board-${index}`} key={index} value={card} placeholder={index < 3 ? `牌面 ${index + 1}` : "future"} onChange={(event) => updateBoard(index, event.target.value)} />)}
          </div>

          <div className="action-box">
            <div className="action-header"><span>当前节点 · {currentStreet}</span><span className="muted">行动者 Seat {legal?.actorSeat ?? state?.actorSeat ?? 0}</span></div>
            <div className="action-buttons">
              {legal?.actions.includes("check") && <button onClick={() => appendAction("check")} disabled={busy}>Check</button>}
              {legal?.actions.includes("call") && <button onClick={() => appendAction("call")} disabled={busy}>Call {legal.callAmount}</button>}
              {legal?.actions.includes("bet") && <button onClick={() => appendAction("bet", raiseAmount === "" ? undefined : raiseAmount)} disabled={busy}>Bet {raiseAmount || legal.minRaiseTo}</button>}
              {legal?.actions.includes("raise_to") && <button onClick={() => appendAction("raise_to", raiseAmount === "" ? undefined : raiseAmount)} disabled={busy}>Raise to {raiseAmount || legal.minRaiseTo}</button>}
              {legal?.actions.includes("all_in") && <button onClick={() => appendAction("all_in")} disabled={busy}>All-in</button>}
              {legal?.actions.includes("fold") && <button className="quiet" onClick={() => appendAction("fold")} disabled={busy}>Fold</button>}
              {currentStreet === "preflop" && <button className="quiet" onClick={() => deal("deal_flop")} disabled={busy || scenario.board.length < 3}>Deal flop</button>}
              {currentStreet === "flop" && <button className="quiet" onClick={() => deal("deal_turn")} disabled={busy || scenario.board.length < 4}>Deal turn</button>}
              {currentStreet === "turn" && <button className="quiet" onClick={() => deal("deal_river")} disabled={busy || scenario.board.length < 5}>Deal river</button>}
            </div>
            {(legal?.actions.includes("bet") || legal?.actions.includes("raise_to")) && <label className="amount-input">下注 / raise-to<input type="number" min={legal.minRaiseTo ?? 0} max={legal.maxRaiseTo ?? undefined} value={raiseAmount === "" ? legal.minRaiseTo ?? "" : raiseAmount} onChange={(event) => setRaiseAmount(event.target.value === "" ? "" : Number(event.target.value))} /></label>}
          </div>

          <div className="timeline">
            <div className="subheading"><span>行动时间线</span><button className="text-button" onClick={() => refreshState()}>重新校验</button></div>
            {scenario.actionHistory.length === 0 ? <p className="muted">尚未录入行动。后端会从盲注和初始筹码推导底池。</p> : scenario.actionHistory.map((event) => <button className={`timeline-row ${scenario.decisionPoint.afterSequence === event.sequence ? "selected" : ""}`} key={event.actionId} onClick={() => void selectNode(event.sequence, event.street)}><span className="sequence">{String(event.sequence).padStart(2, "0")}</span><span>{event.street}</span><strong>Seat {event.actorSeat} · {event.actionType}</strong><span className="muted">{event.amount ?? "—"}</span></button>)}
          </div>
        </section>

        <aside className="side-column">
          <section className="panel compact-panel">
            <div className="panel-heading"><div><p className="eyebrow">02 · RANGE</p><h2>{rangeSide === "heroRange" ? "Hero" : "Villain"} 范围</h2></div><span className="source-tag">假设</span></div>
            <div className="range-controls">
              <label>编辑对象<select aria-label="范围侧" value={rangeSide} onChange={(event) => selectRangeSide(event.target.value as RangeSide)}><option value="villainRange">Villain 范围</option><option value="heroRange">Hero 范围</option></select></label>
              <label>默认范围<select aria-label="默认范围" defaultValue="" onChange={(event) => void applyDefaultRange(event.target.value)}><option value="">选择默认范围</option>{Object.entries(defaultRanges).map(([key, item]) => <option key={key} value={key}>{item.name}</option>)}</select></label>
            </div>
            <textarea value={rangeText} onChange={(event) => setCurrentRangeText(event.target.value)} aria-label="range notation" />
            <button className="secondary-button" onClick={parseRange}>标准化范围</button>
            <div className="range-matrix" aria-label="169 格范围矩阵">{RANKS.map((row, rowIndex) => RANKS.map((column, columnIndex) => { const cell = matrixCell(rowIndex, columnIndex); const weight = rangeMatrix[cell]; return <button type="button" className={`matrix-cell ${weight ? "active" : ""}`} key={cell} title={weight ? `${cell} · ${weight}` : `${cell} · empty`} aria-label={`${cell} weight`} onClick={() => void cycleRangeCell(cell)}>{cell}{weight && <small>{weight}</small>}</button>; }))}</div>
            <p className="muted small">点击矩阵格循环设置 0.25 / 0.5 / 0.75 / 1 权重；每次变化都由后端重新标准化。</p>
            {rangeSummary && <p className="range-summary">有效组合：<strong>{rangeSummary.totalCombos}</strong> · 加权组合：<strong>{rangeSummary.weightedCombos}</strong> · 已展开：{rangeCombos.length}</p>}
          </section>

          <section className="panel compact-panel">
            <div className="panel-heading"><div><p className="eyebrow">02B · HISTORY</p><h2>场景历史</h2></div><button className="text-button" onClick={() => void loadSavedScenarios()}>刷新</button></div>
            {savedScenarios.length === 0 ? <p className="muted small">尚无已保存场景。</p> : <div className="saved-list">{savedScenarios.slice(0, 8).map((record) => <div className="saved-row" key={record.scenarioId}><button className="saved-load" onClick={() => loadSaved(record)}><strong>{record.title}</strong><span>rev {record.revisionNo}</span></button><button className="text-button" onClick={() => void loadAnalysisHistory(record)}>历史</button><button className="text-button" onClick={() => void reanalyzeSaved(record)}>重新分析</button><button className="text-button danger-button" onClick={() => void deleteSaved(record)}>删除</button><button className="icon-button" onClick={() => void copySaved(record)} aria-label={`复制 ${record.title}`}>＋</button></div>)}</div>}
            {historyScenarioId && <div className="history-compare"><p className="eyebrow">SCENARIO REVISIONS</p>{savedRevisions.map((revision) => <div className="revision-row" key={`${revision.scenarioId}-${revision.revisionNo}`}><span>rev {revision.revisionNo}</span><button className="text-button" onClick={() => loadRevision(revision)}>载入</button><button className="text-button" onClick={() => void reanalyzeRevision(revision, savedScenarios.find((item) => item.scenarioId === revision.scenarioId)?.title ?? "场景")}>重新分析</button></div>)}</div>}
            {historyScenarioId && <div className="history-compare"><p className="eyebrow">ANALYSIS HISTORY</p>{savedAnalyses.length < 2 ? <p className="muted small">至少需要两次保存分析才能比较。</p> : <><label>左侧<select value={compareLeft} onChange={(event) => setCompareLeft(event.target.value)}>{savedAnalyses.map((item) => <option key={item.analysisId} value={item.analysisId}>rev {item.revisionNo} · {item.analysisId.slice(0, 8)}</option>)}</select></label><label>右侧<select value={compareRight} onChange={(event) => setCompareRight(event.target.value)}>{savedAnalyses.map((item) => <option key={item.analysisId} value={item.analysisId}>rev {item.revisionNo} · {item.analysisId.slice(0, 8)}</option>)}</select></label><button className="secondary-button" onClick={() => void compareHistory()} disabled={compareLeft === compareRight}>比较分析</button>{comparison && <p className="muted small">发现 {comparison.differences.length} 个结构化字段差异：{comparison.differences.map((difference) => difference.field).join("、") || "无"}</p>}</>}</div>}
          </section>

          <section className="panel compact-panel">
            <div className="panel-heading"><div><p className="eyebrow">03 · ANALYZE</p><h2>输出证据</h2></div><span className="source-tag green">grounded</span></div>
            <p className="muted">编辑完成后重新分析。没有可靠策略数据时，结果只提供数学与原理层证据。</p>
            <div className="teaching-controls"><label>教学深度<select aria-label="教学深度" value={teachingDepth} onChange={(event) => setTeachingDepth(event.target.value)}><option value="beginner">新手</option><option value="intermediate">进阶</option><option value="advanced">高级</option></select></label></div>
            <label className="teaching-question">教学问题<textarea aria-label="教学问题" placeholder="例如：如果对手范围更紧，行动会怎样变化？" value={teachingQuestion} onChange={(event) => setTeachingQuestion(event.target.value)} /></label>
            <div className="primary-actions"><button onClick={() => refreshState()} disabled={busy}>校验场景</button><button onClick={runAnalysis} disabled={busy}>生成分析</button><button onClick={runTeaching} disabled={busy}>教学解释</button><button onClick={generatePractice} disabled={busy}>生成练习</button><button className="secondary-button" onClick={saveScenario} disabled={busy}>保存场景</button><button className="secondary-button" onClick={exportScenario} disabled={busy}>导出 JSON</button><label className="secondary-button import-button">导入 JSON<input type="file" accept="application/json,.json" aria-label="导入 JSON" onChange={(event) => void importScenarioFile(event)} disabled={busy} /></label></div>
            <p className="notice">{message}</p>
          </section>
        </aside>
      </div>

      {analysis && <section className="panel results-panel">
        <div className="panel-heading"><div><p className="eyebrow">04 · EVIDENCE BUNDLE</p><h2>结构化分析</h2></div><div className="heading-actions">{analysisStale && <span className="source-tag">结果已过期</span>}<span className="source-tag green">{analysis.equity?.sourceLevel ?? "principle_only"}</span></div></div>
        <div className="metric-grid">
          <Metric label="Pot" value={analysis.metrics.currentPot ?? "—"} />
          <Metric label="Call cost" value={analysis.metrics.callCost ?? "—"} />
          <Metric label="SPR" value={analysis.metrics.spr ?? "—"} />
          <Metric label="Pot odds" value={analysis.metrics.potOdds ?? "—"} />
          <Metric label="Hand" value={analysis.hand.madeHand} />
          <Metric label="Outs" value={analysis.hand.outCount} />
        </div>
        <div className="result-columns">
          <div><p className="eyebrow">HAND / BOARD</p><p className="result-line"><strong>{analysis.hand.category}</strong> · {analysis.hand.draws.join(", ") || "no draw"}</p><p className="muted">Board: {analysis.board.labels.join(" · ")} · {analysis.board.staticOrDynamic}</p><p className="muted small">Outs: {analysis.hand.outCards.join(", ") || "—"} · 反制牌：{analysis.hand.counterfeitRiskCards.join(", ") || "—"}</p></div>
          <div><p className="eyebrow">EQUITY</p>{analysis.equity ? <p className="result-line"><strong>{analysis.equity.heroEquity}</strong> Hero · {analysis.equity.villainEquity} Villain · tie {analysis.equity.tieProbability}</p> : <p className="muted">缺少 Villain 手牌或范围，未计算 Equity。</p>}</div>
        </div>
        {analysis.rangeAnalysis && <div className="range-result-card"><p className="eyebrow">RANGE / COMBOS</p><p className="result-line"><strong>{analysis.rangeAnalysis.totalCombos}</strong> combos · 加权 {analysis.rangeAnalysis.weightedCombos} · blocked {analysis.rangeAnalysis.blockedCombos}</p><p className="muted">value {analysis.rangeAnalysis.valueCombos} · bluff {analysis.rangeAnalysis.bluffCombos} · draw {analysis.rangeAnalysis.drawCombos} · polarity {analysis.rangeAnalysis.polarity}</p><p className="muted small">Blocker：{analysis.rangeAnalysis.blockerCards.join(", ") || "—"} · 分类标记：{analysis.rangeAnalysis.heuristic ? "heuristic" : "calculated"}</p></div>}
        {analysis.strategyMatch && <div className="strategy-card"><div><p className="eyebrow">STRATEGY MATCH</p><p className="result-line"><strong>{analysis.strategyMatch.level}</strong> · similarity {analysis.strategyMatch.similarity}</p><p className="muted">{analysis.strategyMatch.explanation}</p></div><div>{analysis.strategyMatch.recommendations.map((recommendation) => <div className="recommendation-row" key={recommendation.action}><strong>{recommendation.action}</strong><span>{recommendation.summary}</span>{recommendation.frequency && <em>{recommendation.frequency}</em>}</div>)}</div>{analysis.strategyMatch.differences.length > 0 && <p className="muted small">差异：{analysis.strategyMatch.differences.map((difference) => difference.field).join("、")}</p>}</div>}
        <div className="evidence-list">{analysis.evidence.items.slice(0, 12).map((item) => <div className="evidence-row" key={item.evidenceId}><span>{item.evidenceId}</span><strong>{String(item.value)}</strong><em>{item.sourceLevel}</em><small>{item.description}</small></div>)}</div>
        {analysis.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
      </section>}

      {teaching && <section className="panel teaching-panel"><div className="panel-heading"><div><p className="eyebrow">05 · TEACHING</p><h2>证据约束的教学解释</h2></div><span className="source-tag">{teachingMeta?.provider === "external_llm" ? (teachingMeta.degraded ? `external_llm · degraded(本地回退) · ${teachingMeta.teacherVersion}` : `external_llm · ${teachingMeta.teacherVersion}`) : `principle_only · ${teaching.explanationDepth}`}</span></div><p className="teaching-summary">{teaching.summary.text}</p><div className="teaching-columns"><div><p className="eyebrow">RECOMMENDED ACTIONS</p>{teaching.recommendedActions.map((action) => <p className="result-line" key={action.action}><strong>{action.action}</strong>{action.frequency ? ` · ${action.frequency}` : ""}</p>)}</div><div><p className="eyebrow">KEY REASONS</p>{teaching.keyReasons.map((reason) => <p className="muted" key={reason.text}>{reason.text}</p>)}</div></div>{teaching.conceptTags?.length ? <p className="muted small">概念：{teaching.conceptTags.join(" · ")}</p> : null}{teaching.followUpQuestion ? <p className="notice">追问：{teaching.followUpQuestion}</p> : null}<p className="notice">{teaching.uncertainty.text}</p></section>}

      <section className="panel solve-panel"><div className="panel-heading"><div><p className="eyebrow">06 · SOLVER</p><h2>Solver 策略求解</h2></div><span className="source-tag">solver_backed{solveJob ? ` · ${solveJob.status}` : ""}</span></div>{!solveJob ? <div className="action-buttons"><button onClick={() => void submitSolve()} disabled={busy || !scenario.heroRange || !scenario.villainRange}>提交 Solver 求解（独立容器）</button><p className="muted small">需要 Hero 与 Villain 范围（用上方范围面板选择默认范围或手动输入）。求解约 1–3 分钟。</p></div> : <div>{solveJob.status === "solved" && solveJob.result?.metadata ? <div className="teaching-columns"><div><p className="eyebrow">求解质量</p><p className="result-line"><strong>exploitability</strong> {solveJob.result.metadata.exploitabilityChips.toFixed(3)} chips</p><p className="result-line"><strong>耗时</strong> {(solveJob.result.metadata.solveTimeMs / 1000).toFixed(1)}s</p><p className="result-line"><strong>迭代</strong> {solveJob.result.metadata.maxIterations}</p><p className="result-line"><strong>引擎</strong> {solveJob.result.metadata.solver} {solveJob.result.metadata.version}</p></div><div><p className="eyebrow">OOP 主导动作</p>{(() => { const primary = solvePrimary(solveJob.result?.root); return primary ? <p className="result-line"><strong>{primary.action}</strong> · {primary.frequency.toFixed(3)}</p> : <p className="muted">—</p>; })()}<p className="eyebrow">IP 响应主导动作</p>{(() => { const primary = solvePrimary(solveJob.result?.responseNode); return primary ? <p className="result-line"><strong>{primary.action}</strong> · {primary.frequency.toFixed(3)}</p> : <p className="muted">—</p>; })()}<p className="eyebrow">Hero 手牌（{scenario.heroHoleCards?.join(" ")}）</p>{(() => { const combo = solveHeroCombo(solveJob.result?.root, scenario.heroHoleCards ?? []) ?? solveHeroCombo(solveJob.result?.responseNode, scenario.heroHoleCards ?? []); return combo ? <p className="result-line"><strong>{Object.entries(combo.strategy).sort((a, b) => b[1] - a[1])[0][0]}</strong> · {Object.entries(combo.strategy).sort((a, b) => b[1] - a[1])[0][1].toFixed(3)} · EV {combo.ev.toFixed(1)}</p> : <p className="muted">手牌不在当前求解范围中</p>; })()}</div></div> : ["queued", "running", "cancellation_requested"].includes(solveJob.status) ? <p className="muted">求解进行中（独立 sidecar 容器）…</p> : solveJob.error ? <p className="warning">{solveJob.error}</p> : <p className="muted">状态：{solveJob.status}</p>}</div>}</section>

      {practice && <section className="panel practice-panel"><div className="panel-heading"><div><p className="eyebrow">06 · PRACTICE</p><h2>验证练习</h2></div><span className="source-tag">validated</span></div><p className="teaching-summary">{practice.prompt}</p><p className="muted small">概念：{practice.conceptTags.join(" · ")}</p><div className="action-buttons">{(state?.legalActions.actions ?? ["check", "call", "fold"]).filter((action) => ["check", "call", "fold", "bet", "raise_to", "all_in"].includes(action)).map((action) => <button key={action} onClick={() => void answerPractice(action)} disabled={busy}>{action}</button>)}</div>{practiceOutcome && <div className={`practice-outcome ${practiceOutcome.attempt.correct ? "correct" : "incorrect"}`}><strong>{practiceOutcome.attempt.correct ? "Correct" : "Review"}</strong><span>{practiceOutcome.explanation}</span><small>证据：{practiceOutcome.evidenceReferences.map((reference) => reference.evidenceId).join("、")}</small></div>}</section>}

      <footer><span>ScenarioSpec → Replay → EvidenceBundle</span><span>无 Solver 频率 · 无自动行动</span></footer>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric"><span>{label}</span><strong>{String(value)}</strong></div>;
}

const RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];

function matrixCell(row: number, column: number) {
  if (row === column) return `${RANKS[row]}${RANKS[column]}`;
  const high = RANKS[Math.min(row, column)];
  const low = RANKS[Math.max(row, column)];
  return `${high}${low}${row < column ? "s" : "o"}`;
}
