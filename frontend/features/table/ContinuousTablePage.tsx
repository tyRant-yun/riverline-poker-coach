"use client";

import { useEffect, useRef, useState } from "react";

import { TableWorkspaceV2, type ActionDelta, type PlaybackSpeed } from "../table-v2/TableWorkspaceV2";
import { continuousTableApi } from "../../lib/api/client";
import type { ContinuousTable, TableInsightsResponse, TableReconciliationResponse, TableReviewResponse, TableSolverResponse } from "../../types/api";

const profiles = ["cautious", "balanced", "aggressive"] as const;
const actionLabels: Record<string, string> = { fold: "弃牌", check: "过牌", call: "跟注", bet: "下注", raise: "加注", raise_to: "加注", all_in: "全下" };

function commandId(prefix: string) { return `${prefix}-${crypto.randomUUID()}`; }

function botDeltas(previous: ContinuousTable | null, next: ContinuousTable): ActionDelta[] {
  if (!previous || previous.sessionId !== next.sessionId || previous.handId !== next.handId) return [];
  const known = new Set(previous.actionHistory.map((action) => action.sequence));
  const botSequences = new Set(next.botDecisionProvenance.map((item) => item.sequence));
  const delta = next.actionHistory.filter((action) => !known.has(action.sequence) && botSequences.has(action.sequence));
  return delta.map((action, index) => ({
    id: `${next.sessionId}:${next.handId}:${action.sequence}`,
    actor: `Bot ${action.actorSeat + 1}`,
    actorSeat: String(action.actorSeat),
    label: actionLabels[action.action] ?? action.action,
    kind: next.handComplete && index === delta.length - 1 ? "showdown" : action.action === "all_in" ? "all-in" : action.action === "raise" || action.action === "raise_to" ? "raise" : "action",
    ...(action.amount != null ? { potDelta: String(action.amount) } : {}),
  }));
}

export default function ContinuousTablePage() {
  const [profile, setProfile] = useState<(typeof profiles)[number]>("balanced");
  const [table, setTable] = useState<ContinuousTable | null>(null);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [insights, setInsights] = useState<TableInsightsResponse["insights"] | null>(null);
  const [review, setReview] = useState<TableReviewResponse["review"] | null>(null);
  const [solver, setSolver] = useState<TableSolverResponse["solver"] | null>(null);
  const [reconciliation, setReconciliation] = useState<TableReconciliationResponse["reconciliation"] | null>(null);
  const [solverLoading, setSolverLoading] = useState(false);
  const [solverElapsedMs, setSolverElapsedMs] = useState<number | null>(null);
  const [playbackActions, setPlaybackActions] = useState<readonly ActionDelta[]>([]);
  const [playbackIdentity, setPlaybackIdentity] = useState("initial");
  const [playbackSpeed, setPlaybackSpeed] = useState<PlaybackSpeed>("comfort");
  const [playing, setPlaying] = useState(false);
  const tableRef = useRef<ContinuousTable | null>(null);
  const insightRequest = useRef(0);
  const reviewRequest = useRef(0);
  const reviewIdentity = useRef<string | null>(null);
  const solverRequest = useRef(0);
  const solverIdentity = useRef<string | null>(null);
  const reconciliationRequest = useRef(0);
  const reconciliationIdentity = useRef<string | null>(null);

  function identityFor(next: ContinuousTable) {
    return `${next.sessionId}:${next.handId ?? "none"}:${next.fingerprint}`;
  }

  function cancelPlayback() { setPlaybackActions([]); setPlaybackIdentity((value) => `${value}:cancel`); setPlaying(false); }
  function loadInsights(next: ContinuousTable) {
    const request = ++insightRequest.current;
    const identity = identityFor(next);
    setInsights(null);
    continuousTableApi.insights(next.sessionId).then((response) => { if (request === insightRequest.current && identity === identityFor(tableRef.current ?? next)) setInsights(response.insights); }).catch(() => { if (request === insightRequest.current && identity === identityFor(tableRef.current ?? next)) setInsights(null); });
  }
  function loadReview(next: ContinuousTable) {
    const request = ++reviewRequest.current;
    const identity = next.handComplete && next.handId ? identityFor(next) : null;
    reviewIdentity.current = identity;
    setReview(null);
    if (!identity || !next.handId) return;
    continuousTableApi.reviews(next.sessionId, next.handId).then((response) => { if (request === reviewRequest.current && identity === reviewIdentity.current) setReview(response.review ?? null); }).catch(() => { if (request === reviewRequest.current && identity === reviewIdentity.current) setReview(null); });
  }
  function loadSolver(next: ContinuousTable) {
    const request = ++solverRequest.current;
    const identity = next.handId && !next.handComplete && next.currentActor === next.heroSeat ? identityFor(next) : null;
    solverIdentity.current = identity;
    setSolver(null); setSolverElapsedMs(null); setSolverLoading(Boolean(identity));
    if (!identity || !next.handId) return;
    const started = performance.now();
    continuousTableApi.solver(next.sessionId, { handId: next.handId, decisionFingerprint: next.fingerprint, budgetTier: "standard" })
      .then((response) => { if (request === solverRequest.current && identity === solverIdentity.current) { setSolver(response.solver); setSolverElapsedMs(Math.round(performance.now() - started)); } })
      .catch(() => { if (request === solverRequest.current && identity === solverIdentity.current) setSolver(null); })
      .finally(() => { if (request === solverRequest.current && identity === solverIdentity.current) setSolverLoading(false); });
  }
  function loadReconciliation(next: ContinuousTable) {
    const request = ++reconciliationRequest.current;
    const identity = next.handId && !next.handComplete && next.currentActor === next.heroSeat ? identityFor(next) : null;
    reconciliationIdentity.current = identity;
    setReconciliation(null);
    if (!identity || !next.handId) return;
    continuousTableApi.reconciliation(next.sessionId, { handId: next.handId, decisionFingerprint: next.fingerprint, budgetTier: "standard" })
      .then((response) => { if (request === reconciliationRequest.current && identity === reconciliationIdentity.current) setReconciliation(response.reconciliation); })
      .catch(() => { if (request === reconciliationRequest.current && identity === reconciliationIdentity.current) setReconciliation(null); });
  }
  function hydrate(next: ContinuousTable, mode: "snapshot" | "transition") {
    const actions = mode === "transition" ? botDeltas(tableRef.current, next) : [];
    tableRef.current = next;
    setTable(next);
    setPlaybackActions(actions);
    setPlaybackIdentity(`${next.sessionId}:${next.handId ?? "none"}:${next.revision}:${actions.map((action) => action.id).join("/")}`);
    setPlaying(actions.length > 0 && playbackSpeed !== "skip" && playbackSpeed !== "instant");
    loadInsights(next); loadSolver(next); loadReconciliation(next); loadReview(next);
  }

  useEffect(() => {
    const sessionId = window.localStorage.getItem("riverline-continuous-table-session");
    if (!sessionId) return;
    setBusy(true);
    continuousTableApi.get(sessionId).then((response) => hydrate(response.table, "snapshot")).catch((cause) => { window.localStorage.removeItem("riverline-continuous-table-session"); setError(cause instanceof Error ? cause.message : "无法重连牌桌"); }).finally(() => setBusy(false));
  }, []);

  // The authoritative snapshot is allowed to advance through bot actions in
  // one response.  A superseded visual queue must never keep a current Hero
  // decision disabled after that response says it is Hero's turn again.
  useEffect(() => {
    if (table && table.currentActor === table.heroSeat) setPlaying(false);
  }, [table?.currentActor, table?.fingerprint, table?.heroSeat]);

  async function create() {
    cancelPlayback(); setBusy(true); setError(null);
    try { const response = await continuousTableApi.create({ commandId: commandId("create"), botProfile: profile }); hydrate(response.table, "snapshot"); window.localStorage.setItem("riverline-continuous-table-session", response.table.sessionId); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "创建牌桌失败"); }
    finally { setBusy(false); }
  }
  async function submit(legal: ContinuousTable["heroLegalActions"][number]) {
    const current = tableRef.current;
    if (!current?.handId || busy || playing) return;
    setBusy(true); setError(null);
    try {
      const response = await continuousTableApi.action(current.sessionId, { commandId: commandId("hero"), handId: current.handId, expectedRevision: current.revision, action: legal.action, amountSemantics: legal.amountSemantics, ...(legal.minAmount != null ? { amount: Number(amounts[legal.action] || legal.minAmount) } : {}) });
      hydrate(response.table, "transition");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "行动未被接受"); }
    finally { setBusy(false); }
  }
  async function nextHand() {
    const current = tableRef.current;
    if (!current || busy) return;
    cancelPlayback(); setBusy(true); setError(null); setReview(null); setSolver(null); setReconciliation(null); setInsights(null);
    try { const response = await continuousTableApi.nextHand(current.sessionId, { commandId: commandId("next"), expectedRevision: current.revision }); hydrate(response.table, "snapshot"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "无法开始下一手"); }
    finally { setBusy(false); }
  }

  return <section className="continuous-table" data-testid="continuous-table-page">
    {!table && <div className="panel-heading"><div><h2>持续牌桌</h2><p>Hero + 5 bots · 6-max · 100BB</p></div><label>Bot profile <select value={profile} disabled={busy} onChange={(event) => setProfile(event.target.value as typeof profile)} data-testid="bot-profile">{profiles.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><button className="primary" onClick={create} disabled={busy} data-testid="create-continuous-table">{busy ? "连接中…" : "开始牌桌"}</button></div>}
    {error && <p className="warning" role="alert">{error}</p>}
    {table && <><div className="tv2-toolbar"><p data-testid="continuous-table-status">第 {table.handSequence} 手 · {table.street ?? "等待开局"} · {table.currentActor == null ? "本手结束" : `座位 ${table.currentActor + 1} 行动`}</p><label>Bot 节奏 <select aria-label="Bot 播放速度" value={playbackSpeed} onChange={(event) => setPlaybackSpeed(event.target.value as PlaybackSpeed)}><option value="comfort">舒适</option><option value="fast">快速</option><option value="instant">即时</option></select></label><button type="button" onClick={cancelPlayback} disabled={!playing}>跳过播放</button></div><TableWorkspaceV2 table={table} insights={insights} solver={solver} reconciliation={reconciliation} solverLoading={solverLoading} solverElapsedMs={solverElapsedMs} playbackActions={playbackActions} playbackIdentity={playbackIdentity} playbackSpeed={playbackSpeed} onPlaybackComplete={() => setPlaying(false)} actionDisabled={busy || playing} amounts={amounts} onAmountChange={(action, amount) => setAmounts((current) => ({ ...current, [action]: amount }))} onAction={submit} onNextHand={nextHand} review={review} /></>}
  </section>;
}
