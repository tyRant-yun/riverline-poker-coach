"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { formatCard } from "../../lib/poker/cards";
import { RANKS, matrixCell } from "../../lib/poker/matrix";
import type { ContinuousTable, TableInsightsResponse, TableReviewResponse, TableSolverResponse } from "../../types/api";
import "../../styles/table-v2.css";

export type SeatStatus = "current" | "folded" | "all-in" | "showdown" | "dealer" | "waiting";
export type TableSeat = { id: string; name: string; stack: string; position: string; status: SeatStatus; cards?: string[] };
export type ActionDelta = { id: string; actor: string; actorSeat?: string; label: string; kind: "action" | "raise" | "all-in" | "showdown"; potDelta?: string };
export type PlaybackSpeed = "comfort" | "fast" | "instant" | "skip" | "slow" | "standard";
export type Scheduler = { setTimeout: (fn: () => void, ms: number) => number; clearTimeout: (id: number | undefined) => void };

const playbackTiming: Record<Exclude<PlaybackSpeed, "skip">, { think: number; readable: number; transition: number }> = {
  comfort: { think: 450, readable: 750, transition: 150 }, standard: { think: 450, readable: 750, transition: 150 }, slow: { think: 600, readable: 900, transition: 200 }, fast: { think: 220, readable: 400, transition: 90 }, instant: { think: 0, readable: 0, transition: 0 },
};
const actionNames: Record<string, string> = { fold: "弃牌", check: "过牌", call: "跟注", bet: "下注", raise: "加注", raise_to: "加注", all_in: "全压" };

export class ActionPlaybackQueue {
  private timer: number | undefined;
  private token = 0;
  constructor(private readonly scheduler: Scheduler, private readonly reducedMotion = false) {}
  play(actions: readonly ActionDelta[], speed: PlaybackSpeed, onAction: (action: ActionDelta) => void, onComplete?: () => void, onThinking?: (action?: ActionDelta) => void) {
    this.cancel();
    const token = ++this.token;
    if (speed === "skip" || this.reducedMotion) { actions.forEach(onAction); onThinking?.(); onComplete?.(); return; }
    let index = 0;
    const next = () => {
      if (token !== this.token) return;
      const action = actions[index++];
      if (!action) { onThinking?.(); onComplete?.(); return; }
      const timing = playbackTiming[speed];
      onThinking?.(action);
      this.timer = this.scheduler.setTimeout(() => {
        if (token !== this.token) return;
        onAction(action); onThinking?.();
        this.timer = this.scheduler.setTimeout(next, timing.readable + timing.transition);
      }, timing.think);
    };
    next();
  }
  cancel() { this.token++; if (this.timer !== undefined) this.scheduler.clearTimeout(this.timer); this.timer = undefined; }
}

export function ActionPlaybackController({ actions, identity, speed, reducedMotion, scheduler, onChange, onThinking, onComplete }: {
  actions: readonly ActionDelta[]; identity: string; speed: PlaybackSpeed; reducedMotion: boolean; scheduler?: Scheduler;
  onChange: (action?: ActionDelta) => void; onThinking: (action?: ActionDelta) => void; onComplete: () => void;
}) {
  const queue = useRef<ActionPlaybackQueue | null>(null);
  const callbacks = useRef({ onChange, onThinking, onComplete });
  callbacks.current = { onChange, onThinking, onComplete };
  useEffect(() => {
    queue.current = new ActionPlaybackQueue(scheduler ?? window, reducedMotion);
    if (!actions.length) { callbacks.current.onThinking(undefined); callbacks.current.onChange(undefined); callbacks.current.onComplete(); return () => queue.current?.cancel(); }
    queue.current.play(actions, speed, (action) => callbacks.current.onChange(action), () => callbacks.current.onComplete(), (action) => callbacks.current.onThinking(action));
    return () => queue.current?.cancel();
  }, [actions, identity, speed, reducedMotion, scheduler]);
  return null;
}

const defaultSeats: TableSeat[] = [
  { id: "0", name: "Hero", stack: "筹码 10,000", position: "BTN", status: "current", cards: ["A♠", "J♠"] },
  ...Array.from({ length: 5 }, (_, index) => ({ id: String(index + 1), name: `Bot ${index + 1}`, stack: "筹码 10,000", position: ["SB", "BB", "UTG", "MP", "CO"][index], status: "waiting" as const })),
];

function seatViews(table?: ContinuousTable): TableSeat[] {
  if (!table) return defaultSeats;
  return table.seats.map((seat) => ({
    id: String(seat.seatId), name: seat.seatId === table.heroSeat ? "Hero" : `Bot ${seat.seatId + 1}`,
    stack: `筹码 ${seat.stack.toLocaleString("zh-CN")}`,
    position: seat.seatId === table.buttonSeat ? "BTN" : ["SB", "BB", "UTG", "MP", "CO", "HJ"][seat.seatId] ?? `Seat ${seat.seatId}`,
    status: seat.status === "folded" ? "folded" : table.handComplete ? "showdown" : seat.seatId === table.currentActor ? "current" : "waiting",
    cards: seat.seatId === table.heroSeat ? table.heroHoleCards.map(formatCard) : seat.revealedHoleCards?.map(formatCard),
  }));
}

export function PokerTableStageV2({ seats = defaultSeats, currentAction, thinkingAction, board = ["Q♠", "J♥", "4♣"], pot = "1,240" }: { seats?: TableSeat[]; currentAction?: ActionDelta; thinkingAction?: ActionDelta; board?: string[]; pot?: string }) {
  return <section className="tv2-stage" aria-label="六人德州扑克牌桌">
    <div className="tv2-felt" />
    <div className="tv2-safe-zone" aria-label="底池与公共牌安全区"><div className="tv2-pot">底池 <strong>{pot}</strong></div><div className="tv2-board" aria-label="公共牌">{board.length ? board.map((card, index) => <i key={`${card}-${index}`}>{card}</i>) : <span>等待公共牌</span>}</div></div>
    {seats.map((seat, index) => { const thinking = thinkingAction?.actorSeat === seat.id; const acted = currentAction?.actorSeat === seat.id; return <article className={`tv2-seat tv2-seat-${index} ${seat.name === "Hero" ? "tv2-hero-seat" : ""} is-${seat.status} ${thinking ? "is-thinking" : ""}`} data-seat={seat.id} key={seat.id} aria-label={`${seat.position} ${seat.name} ${thinking ? "思考中" : seat.status}`}><span className="tv2-position">{seat.position}</span><div className="tv2-avatar">{seat.name.slice(0, 1)}</div><div className="tv2-player"><b>{seat.name}</b><small>{seat.stack}</small></div>{thinking && <span className="tv2-seat-narrative" data-testid="bot-thinking">{seat.name} 思考中…</span>}{acted && <span className="tv2-seat-narrative tv2-action-pill" data-testid="bot-action-bubble" aria-live="polite">{currentAction.label}{currentAction.potDelta ? ` ${currentAction.potDelta}` : ""}</span>}{seat.cards?.length ? <div className="tv2-holecards" aria-label="Hero 手牌">{seat.cards.map((card, cardIndex) => <i key={`${card}-${cardIndex}`} aria-label={card}>{card}</i>)}</div> : null}{seat.status === "folded" && <span className="tv2-fold">弃牌</span>}</article>; })}
  </section>;
}

export function HeroActionDockV2({ table, disabled = false, amounts = {}, onAmountChange, onAction, onNextHand, review, advisor }: {
  table?: ContinuousTable; disabled?: boolean; amounts?: Record<string, string>; onAmountChange?: (action: string, amount: string) => void;
  onAction?: (action: ContinuousTable["heroLegalActions"][number]) => void; onNextHand?: () => void; review?: TableReviewResponse["review"] | null; advisor?: TableInsightsResponse["insights"]["advisor"];
}) {
  const legalActions = table?.heroLegalActions ?? [];
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (disabled || event.defaultPrevented || (event.target instanceof HTMLInputElement)) return;
      const action = ({ f: "fold", c: "call", r: "raise" } as Record<string, string | undefined>)[event.key.toLowerCase()];
      const legal = legalActions.find((item) => item.action === action);
      if (legal) { event.preventDefault(); onAction?.(legal); }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [disabled, legalActions, onAction]);
  const advisorText = advisor?.available ? `建议：${actionNames[advisor.result?.recommendedAction?.action ?? ""] ?? advisor.result?.recommendedAction?.action ?? "暂未给出行动"}` : advisor?.unavailableReason ?? "Advisor 暂不可用；请以合法行动与桌面事实为准。";
  if (table?.handComplete) return <section className="tv2-dock" aria-label="Hero 操作区"><div className="tv2-advisor-summary" aria-label="Advisor 摘要">{advisorText}</div><div><small>本手已结算</small><strong data-testid="table-review-status">{review ? `复盘可用：${review.heroDecisions.length} 个 Hero 决策` : "复盘未就绪"}</strong></div><button className="primary" disabled={disabled} onClick={onNextHand} data-testid="next-hand">下一手</button></section>;
  return <section className="tv2-dock" aria-label="Hero 操作区" aria-busy={disabled}><div className="tv2-advisor-summary" aria-label="Advisor 摘要">{advisorText}</div><div><small>{disabled ? "Bot 行动播放中" : "轮到你 · 按 F / C / R 快捷操作"}</small><strong>{table ? `Hero · ${table.heroHoleCards.map(formatCard).join(" ")}` : "Hero"}</strong></div><div className="tv2-actions" data-testid="hero-legal-actions">{legalActions.map((legal) => <div key={legal.action}>{legal.minAmount != null && <input aria-label={`${legal.action} amount`} type="number" min={legal.minAmount} max={legal.maxAmount} value={amounts[legal.action] ?? String(legal.minAmount)} disabled={disabled} onChange={(event) => onAmountChange?.(legal.action, event.target.value)} />}<button aria-label={actionNames[legal.action] ?? legal.action} disabled={disabled} onClick={() => onAction?.(legal)} data-testid={`hero-action-${legal.action}`}>{actionNames[legal.action] ?? legal.action}{legal.minAmount != null ? ` ${legal.minAmount}-${legal.maxAmount}` : ""} {legal.action === "fold" ? <kbd>F</kbd> : legal.action === "call" ? <kbd>C</kbd> : legal.action === "raise" ? <kbd>R</kbd> : null}</button></div>)}</div></section>;
}

function rangeMessage(reason?: string) {
  if (reason === "stack_bucket_unsupported") return "当前筹码档位暂无可用 Range 估计。";
  if (reason === "private_event_forbidden") return "当前事件不是公开行动前缀，无法安全估计范围。";
  return reason ? `当前暂无 Range 数据：${reason.replaceAll("_", " ")}` : "当前未返回座位 Range Belief。";
}
function approximationLabel(reason?: string | null) {
  const match = reason?.match(/^nearest_stack_bucket:(.+)$/);
  return match ? `近似：${match[1].toUpperCase()} 最近档` : "近似估计";
}
function percent(value?: string | number | null) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}
function chips(value?: string | number | null) { return value == null || !Number.isFinite(Number(value)) ? "—" : Math.round(Number(value)).toLocaleString("zh-CN"); }
function ev(value?: string | number | null) { return value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(1)}`; }
function candidateLabel(candidate: { action: string; amount?: number | null }, pot?: number) {
  if (candidate.action === "all_in") return `全压${candidate.amount != null ? ` · ${pot && pot > 0 ? `${Math.round(Number(candidate.amount) / pot * 100)}% pot · ` : ""}${chips(candidate.amount)}` : ""}`;
  const label = actionNames[candidate.action] ?? candidate.action;
  return candidate.amount != null ? `${label}${pot && pot > 0 ? ` ${Math.round(Number(candidate.amount) / pot * 100)}% pot ·` : ""} ${chips(candidate.amount)}` : label;
}
function RangeHeatmap({ belief }: { belief: NonNullable<TableInsightsResponse["insights"]["seatBeliefs"]>[number] }) {
  const matrix = belief.matrix169;
  if (!matrix) return null;
  return <div className="tv2-range-heatmap" aria-label={`座位 ${belief.seatId + 1} Range 热图`}>
    {RANKS.flatMap((_, row) => RANKS.map((__, column) => {
      const hand = matrixCell(row, column); const cell = matrix[hand]; const mass = Number(cell?.probabilityMass ?? 0);
      return <button type="button" key={hand} className="tv2-range-cell" style={{ "--range-mass": Math.min(1, mass * 10) } as React.CSSProperties} title={`${hand}：概率质量 ${(mass * 100).toFixed(2)}%，${cell?.comboCount ?? 0} 个合法组合`}>{hand}</button>;
    }))}
  </div>;
}
function statText(stats: NonNullable<TableInsightsResponse["insights"]["stats"]>) {
  return stats.bySeat.map((stat) => `座位 ${stat.seatId + 1}：入池率 ${(stat.vpip * 100).toFixed(0)}% · 翻前加注率 ${(stat.pfr * 100).toFixed(0)}% · 3Bet ${(stat.threeBet * 100).toFixed(0)}%`).join("；");
}

export function InsightRailV2({ insights, solver, table, solverLoading = false, solverElapsedMs }: { insights?: TableInsightsResponse["insights"] | null; solver?: TableSolverResponse["solver"] | null; table?: ContinuousTable; solverLoading?: boolean; solverElapsedMs?: number | null }) {
  const [rangeSeatId, setRangeSeatId] = useState<number | null>(null);
  const range = insights?.seatBeliefs ?? [];
  const selectedRange = range.find((belief) => belief.seatId === rangeSeatId) ?? range.find((belief) => belief.available) ?? range[0];
  const rangeContent = range.length ? <><div className="tv2-range-seats">{range.map((belief) => <button key={belief.seatId} aria-pressed={selectedRange?.seatId === belief.seatId} onClick={() => setRangeSeatId(belief.seatId)}>座位 {belief.seatId + 1}</button>)}</div>{selectedRange?.available ? <><p>范围宽度 {selectedRange.rangeWidthPct?.toFixed(1) ?? "—"}% · {selectedRange.rangeWidthCombos?.toFixed(0) ?? "—"} combos · 置信度 {selectedRange.confidenceScore != null ? `${(selectedRange.confidenceScore * 100).toFixed(0)}%` : selectedRange.confidence === "heuristic" ? "启发式" : selectedRange.confidence ?? "未提供"}</p><p>最近变化：{selectedRange.changeReason ?? "初始先验"}{selectedRange.approximate ? ` · ${approximationLabel(selectedRange.approximationReason)}` : ""}</p><small>{selectedRange.limitations?.join("；") ?? "构成分析将在 Range Explorer 中提供。"}</small></> : <p>{rangeMessage(selectedRange?.unavailableReason)}</p>}</> : <p>{rangeMessage()}</p>;
  const advisor = insights?.advisor;
  const advisorAction = advisor?.result?.recommendedAction;
  const solverAction = solver?.recommendedAction ?? solver?.candidates?.slice().sort((a, b) => Number(b.approximateEvChips) - Number(a.approximateEvChips))[0];
  const disagreement = Boolean(advisorAction && solverAction && advisorAction.action !== solverAction.action);
  const ordered = solver?.candidates.slice().sort((a, b) => Number(b.approximateEvChips) - Number(a.approximateEvChips)) ?? [];
  const solverContent = solverLoading ? <p>模拟估计计算中；规则基线仍可用。</p> : solver?.status === "ready" || solver?.status === "degraded" ? <><div className="tv2-ladder" aria-label="Solver Action Ladder">{ordered.slice(0, 3).map((candidate, index) => { const best = Number(ordered[0]?.approximateEvChips ?? 0); const delta = Number(candidate.approximateEvChips) - best; const extreme = candidate.action === "all_in" || (candidate.amount != null && table?.pot && Number(candidate.amount) / table.pot > 2); return <article key={`${candidate.action}-${candidate.amount ?? ""}`} className="tv2-ladder-row"><strong>{candidateLabel(candidate, table?.pot)}</strong><span>ΔEV {ev(delta)}</span><span>EV {ev(candidate.approximateEvChips)}</span>{candidate.confidenceInterval95 ? <small>CI {ev(candidate.confidenceInterval95.lower)}–{ev(candidate.confidenceInterval95.upper)}</small> : null}{index > 0 && Math.abs(delta) < .3 ? <small>与最佳接近</small> : null}{extreme ? <small className="risk">高风险尺度</small> : null}</article>; })}</div><details><summary>模型详情</summary><p>{solver.status === "degraded" ? "近似 EV 求解（降级）" : "近似 EV 求解"}，不是 GTO 或 Nash。</p><p>权益 {percent(solver.equity)} · 样本 {solver.sampleCount ?? solver.iterations} · ESS {solver.effectiveSampleSize ?? "—"} · 耗时 {solverElapsedMs != null ? `${solverElapsedMs}ms` : solver.elapsedMicroseconds != null ? `${Math.round(solver.elapsedMicroseconds / 1000)}ms` : "未测得"}</p>{ordered[0]?.responseMix ? <p>最佳候选响应 F/C/R {percent(ordered[0].responseMix.fold)}/{percent(ordered[0].responseMix.call)}/{percent(ordered[0].responseMix.raise)}</p> : null}<p>预算 {solver.budgetTier ?? "未提供"} / {solver.budgetMs ?? "—"}ms · 置信度 {solver.confidence ?? "未提供"}</p><p>限制：{solver.limitations.join("；") || "后端未返回限制"}</p></details></> : <p>{solver?.unavailableReason ?? "当前不是 Hero 决策；模拟估计尚未就绪。"}</p>;
  return <aside className="tv2-rail" data-testid="table-insights" aria-label="决策驾驶舱"><section className="tv2-summary" aria-label="Decision Summary"><p>轮到 Hero · {table?.street ?? "等待开局"} · Pot {chips(table?.pot)}</p><div><span>规则基线</span><strong>Advisor：{advisor?.available && advisorAction ? candidateLabel(advisorAction, table?.pot) : advisor?.unavailableReason ?? "暂不可用"}</strong></div><div><span>模拟估计</span><strong>Solver：{solverAction ? candidateLabel(solverAction, table?.pot) : solverLoading ? "计算中" : "暂不可用"}</strong></div><b className={disagreement ? "disagreement" : "agreement"}>{disagreement ? "存在分歧 · 原因尚未确定" : advisorAction && solverAction ? "结论一致" : "等待可比较结果"}</b></section><section className="tv2-analysis-panel" aria-label="Solver 结果"><h2>模拟估计</h2>{solverContent}</section><section className="tv2-analysis-panel tv2-range-summary" aria-label="Range Belief"><h2>Range 摘要</h2><p>座位独立边际估计，不含对手私牌</p>{rangeContent}</section></aside>;
}

export function TableTimelineV2({ table }: { table: ContinuousTable }) {
  const provenance = new Map(table.botDecisionProvenance.map((item) => [item.sequence, item]));
  return <section className="tv2-timeline" aria-label="行动时间线"><h3>行动时间线</h3><ol data-testid="table-action-history">{table.actionHistory.map((action) => { const source = provenance.get(action.sequence); return <li key={action.sequence}><time>{action.street}</time><span>座位 {action.actorSeat + 1} {actionNames[action.action] ?? action.action}{action.amount != null ? ` ${action.amount}` : ""}</span>{source ? <small>Bot 来源：{source.profileId} · {source.provider}{source.degraded ? ` · 降级${source.fallbackReason ? `：${source.fallbackReason}` : ""}` : ""}</small> : null}</li>; })}</ol><ul data-testid="bot-provenance" className="sr-only">{table.botDecisionProvenance.map((item) => <li key={item.sequence}>座位 {item.actorSeat + 1} · {item.profileId} · {item.provider}</li>)}</ul></section>;
}

export function TableWorkspaceV2({ table, insights, solver, solverLoading, solverElapsedMs, playbackActions = [], playbackIdentity, playbackSpeed, onPlaybackComplete, actionDisabled, amounts, onAmountChange, onAction, onNextHand, review }: {
  table: ContinuousTable; insights: TableInsightsResponse["insights"] | null; solver: TableSolverResponse["solver"] | null; solverLoading: boolean; solverElapsedMs: number | null;
  playbackActions?: readonly ActionDelta[]; playbackIdentity: string; playbackSpeed: PlaybackSpeed; onPlaybackComplete: () => void; actionDisabled: boolean;
  amounts: Record<string, string>; onAmountChange: (action: string, amount: string) => void; onAction: (action: ContinuousTable["heroLegalActions"][number]) => void; onNextHand: () => void; review: TableReviewResponse["review"] | null;
}) {
  const [currentAction, setCurrentAction] = useState<ActionDelta>();
  const [thinkingAction, setThinkingAction] = useState<ActionDelta>();
  const reducedMotion = typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const seats = useMemo(() => seatViews(table), [table]);
  return <main className="tv2-workspace" data-testid="table-workspace-v2"><ActionPlaybackController actions={playbackActions} identity={playbackIdentity} speed={playbackSpeed} reducedMotion={reducedMotion} onChange={setCurrentAction} onThinking={setThinkingAction} onComplete={() => { setThinkingAction(undefined); setCurrentAction(undefined); onPlaybackComplete(); }} /><PokerTableStageV2 seats={seats} currentAction={currentAction} thinkingAction={thinkingAction} board={table.board.map(formatCard)} pot={table.pot.toLocaleString("zh-CN")} /><InsightRailV2 table={table} insights={insights} solver={solver} solverLoading={solverLoading} solverElapsedMs={solverElapsedMs} /><TableTimelineV2 table={table} /><HeroActionDockV2 table={table} advisor={insights?.advisor} disabled={actionDisabled} amounts={amounts} onAmountChange={onAmountChange} onAction={onAction} onNextHand={onNextHand} review={review} /></main>;
}
